"""
Saayam request archival.

Invoked on a schedule by EventBridge Scheduler. For each enabled table in
config.json: read the rows changed since that table's watermark, apply the
configured PII rules in SQL, write a CSV to S3, advance the watermark.

Notes:

  * Masking is done in the SELECT. For a column whose rule is drop, hash, mask
    or redact, the raw value never reaches this process.

  * Source timestamps are `timestamp without time zone`. Comparing one to
    clock_timestamp() (timestamptz) casts via the session TimeZone, so the same
    query returns different rows depending on where it runs. Connections are
    pinned to UTC and bounds are written as `now() AT TIME ZONE 'UTC'`, which
    is naive and matches the column type. Keep both.

  * The watermark advances only after S3 confirms the upload. A crash before
    that leaves it unmoved; the next run recomputes the same range and writes
    the same key.

  * State backend is pluggable: postgres, s3 or none. See state.py.

  * {"from": ..., "to": ...} in the invocation payload runs one explicit range,
    bypassing the watermark and persisting nothing. Used for backfills and for
    testing before a state store exists.
"""

import csv
import gzip
import json
import os
import re
import time
import traceback
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config as BotoConfig
import pg8000.native

import state as state_mod

BUCKET          = os.environ["BUCKET"]
DB_PARAM        = os.environ.get("DB_PARAM", "")
STREAM          = os.environ.get("STREAM", "main")
HASH_SALT_PARAM = os.environ.get("HASH_SALT_PARAM")
HASH_SALT       = os.environ.get("HASH_SALT", "")
COMPRESS        = os.environ.get("COMPRESS", "gzip").lower()
PREFIX          = os.environ.get("S3_PREFIX", "raw")
CONFIG_FILE     = os.environ.get("CONFIG_FILE", "config.json")

# Short timeouts. The boto default is a 60s connect timeout with retries, so in
# a VPC with no route to an endpoint one unreachable service burns 80+s of the
# 900s budget before raising.
_cfg = BotoConfig(connect_timeout=10, read_timeout=60,
                  retries={"max_attempts": 3, "mode": "standard"})
s3  = boto3.client("s3", config=_cfg)
ssm = boto3.client("ssm", config=_cfg)
RUN_ID = None


def log(event, **f):
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "event": event,
           "invocation": RUN_ID, "stream": STREAM}
    rec.update(f)
    print(json.dumps(rec, default=str))


def load_config():
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = json.load(open(os.path.join(here, CONFIG_FILE)))
    seen = set()
    for t in cfg["tables"]:
        if t["name"] in seen:
            raise ValueError(f"duplicate table in config: {t['name']}")
        seen.add(t["name"])
        if t.get("mode", "incremental") == "incremental" and not t.get("timestamp_column"):
            raise ValueError(f"{t['name']}: incremental mode needs timestamp_column")
        for c, a in (t.get("columns") or {}).items():
            if a not in ("keep", "drop", "hash", "mask", "redact", "scrub"):
                raise ValueError(f"{t['name']}.{c}: unknown action {a!r}")
    return cfg


def get_db_config():
    # DB_CONFIG_JSON is a workaround for a VPC with no route to the SSM
    # endpoint: the deploy script reads Parameter Store from where it does have
    # a route and passes the value in.
    #
    # EVALUATION ONLY. A Lambda environment variable is plaintext to anyone
    # with lambda:GetFunctionConfiguration, a much wider group than can decrypt
    # a SecureString. Remove this once there is an SSM interface endpoint or a
    # NAT.
    inline = os.environ.get("DB_CONFIG_JSON")
    if inline:
        log("db_config_source", source="env", warning="evaluation only, not for production")
        d = json.loads(inline)
    else:
        d = json.loads(ssm.get_parameter(Name=DB_PARAM, WithDecryption=True)["Parameter"]["Value"])
    return _shape_db(d)


def _shape_db(d):
    return {"host": d["HOST"], "user": d["USERNAME"], "password": d["PASSWORD"],
            "database": d["DATABASE NAME"], "port": int(d.get("PORT", 5432)),
            "ssl": str(d.get("SSL", "")).lower() in ("true", "require", "required", "yes", "1")}


def get_salt():
    if HASH_SALT_PARAM:
        return ssm.get_parameter(Name=HASH_SALT_PARAM, WithDecryption=True)["Parameter"]["Value"]
    return HASH_SALT


def connect(dbc):
    conn = pg8000.native.Connection(
        user=dbc["user"], password=dbc["password"], host=dbc["host"],
        database=dbc["database"], port=dbc["port"], timeout=30,
        ssl_context=True if dbc["ssl"] else None)
    conn.run("SET TIME ZONE 'UTC'")      # see the timestamp note at the top
    return conn


# ---------------------------------------------------------------- free text
# These run in Python on the returned rows, not in SQL, so the raw text IS in
# this process (unlike hash/mask/drop, which execute in Postgres). Never log a
# row.
#
# Patterns only. No regex recognises a name in any language, so names in
# req_subj / req_desc are not covered here. That needs a users-table lookup or
# Comprehend.
SCRUB_PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("SSN",   re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("CARD",  re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?!\d)")),
    ("URL",   re.compile(r"https?://\S+")),
]


def scrub_text(value, counts):
    """Replace patterned identifiers with a tag."""
    if value is None:
        return None
    text = str(value)
    if not text.strip():
        return value
    for tag, pat in SCRUB_PATTERNS:
        text, n = pat.subn(f"[{tag}]", text)
        if n:
            counts[tag] = counts.get(tag, 0) + n
    return text


def qi(n):
    return '"' + str(n).replace('"', '""') + '"'


def build_select(conn, schema, table, rules):
    cols = conn.run(
        """SELECT column_name FROM information_schema.columns
            WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position""",
        s=schema, t=table)
    if not cols:
        raise RuntimeError(f"{schema}.{table} does not exist or is not visible")

    parts, out, dropped, masked = [], [], 0, 0
    scrub_cols = []
    for (name,) in cols:
        action = rules.get(name, "keep")
        c = a = qi(name)
        if action == "drop":
            dropped += 1
            continue
        if action == "scrub":
            # Selected as-is; scrubbed in Python after the rows arrive.
            scrub_cols.append(name)
            parts.append(f"{c} AS {a}")
        elif action == "keep":
            parts.append(f"{c} AS {a}")
        elif action == "hash":
            masked += 1
            # NULL stays NULL. Hashing it would give every null row the same
            # non-null value.
            parts.append(f"CASE WHEN {c} IS NULL THEN NULL ELSE "
                         f"encode(sha256(convert_to({c}::text || :hash_salt,'UTF8')),'hex') END AS {a}")
        elif action == "mask":
            masked += 1
            parts.append(f"CASE WHEN {c} IS NULL THEN NULL ELSE "
                         f"left({c}::text,1) || repeat('*', greatest(length({c}::text)-1,0)) END AS {a}")
        elif action == "redact":
            masked += 1
            parts.append(f"CASE WHEN {c} IS NULL THEN NULL ELSE '[REDACTED]' END AS {a}")
        out.append(name)

    if not parts:
        raise ValueError(f"{schema}.{table}: every column dropped, nothing to write")
    return ", ".join(parts), out, dropped, masked, scrub_cols


def archive_table(conn, st, salt, schema, t, triggered_by, override):
    table = t["name"]
    mode  = t.get("mode", "incremental")
    tscol = t.get("timestamp_column")
    lag   = int(t.get("lag_minutes", 5))
    rules = t.get("columns") or {}
    started = datetime.now(timezone.utc)

    select_list, out_cols, dropped, masked, scrub_cols = build_select(
        conn, schema, table, rules)
    log("table_start", table=table, mode=mode, columns_out=len(out_cols),
        columns_dropped=dropped, columns_masked=masked, columns_scrubbed=scrub_cols)

    persist = True
    if mode == "incremental":
        if override:
            lo, hi = override["from"], override["to"]
            persist = False                      # explicit range, remember nothing
        elif not st.durable:
            # STATE_STORE=none has no watermark. Falling back to initial_value
            # would re-export the whole table every run and still report
            # success, so refuse.
            raise RuntimeError(
                f"{table}: STATE_STORE=none has no watermark, so an incremental run "
                "has no safe lower bound. Pass an explicit \"from\" and \"to\" in the "
                "invocation payload, or configure a durable state store.")
        else:
            lo = st.get_watermark(table, STREAM) or t.get("initial_value")
            if lo is None:
                raise RuntimeError(f"{table}: no watermark and no initial_value in config")
            hi = conn.run("SELECT (now() AT TIME ZONE 'UTC') - make_interval(mins => :m)",
                          m=lag)[0][0]
            if str(lo) > str(hi):
                raise RuntimeError(
                    f"{table}: watermark {lo} is ahead of bound {hi}. Refusing to run. "
                    "Check for future-dated timestamps.")
        where  = f"WHERE {qi(tscol)} > :lo AND {qi(tscol)} <= :hi"
        order  = f"ORDER BY {qi(tscol)}"
        params = {"lo": lo, "hi": hi}
    else:
        lo = hi = None
        where = order = ""
        params = {}

    n = conn.run(f"SELECT count(*) FROM {qi(schema)}.{qi(table)} {where}", **params)[0][0]
    if n == 0:
        if persist:
            st.touch(table, STREAM)
        # Log empty runs too. Without a row, "fired and found nothing" and
        # "never fired" look the same.
        st.log_run({"invocation": RUN_ID, "table": table, "stream": STREAM,
                    "mode": mode, "status": "nothing_to_do",
                    "triggered_by": triggered_by, "range_from": lo, "range_to": hi,
                    "source_rows": 0, "rows_written": 0, "bytes": 0,
                    "columns_dropped": dropped, "columns_masked": masked,
                    "started_at": started.replace(tzinfo=None).isoformat(sep=" ", timespec="milliseconds"),
                    "finished_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="milliseconds")})
        log("table_done", table=table, status="nothing_to_do", rows=0,
            range_from=lo, range_to=hi)
        return {"table": table, "status": "nothing_to_do", "rows": 0}

    day  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    tag  = lambda v: str(v).replace("-", "").replace(":", "").replace(" ", "T")[:15]
    ext  = "csv.gz" if COMPRESS == "gzip" else "csv"
    key  = (f"{PREFIX}/{table}/ingest_date={day}/"
            f"{table}_{tag(lo) if lo else 'full'}_{tag(hi) if hi else day}.{ext}")

    q = dict(params)
    if ":hash_salt" in select_list:
        q["hash_salt"] = salt

    t0 = time.time()
    rows = conn.run(f"SELECT {select_list} FROM {qi(schema)}.{qi(table)} {where} {order}", **q)

    scrub_idx = [out_cols.index(c) for c in scrub_cols]
    scrub_counts = {}
    rows_touched = 0

    path = f"/tmp/{uuid.uuid4().hex}.{ext}"
    opener = gzip.open if COMPRESS == "gzip" else open
    written = 0
    with opener(path, "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        w.writerow(out_cols)
        for r in rows:
            if scrub_idx:
                before = dict(scrub_counts)
                for i in scrub_idx:
                    r[i] = scrub_text(r[i], scrub_counts)
                if scrub_counts != before:
                    rows_touched += 1
            w.writerow(r)
            written += 1

    if scrub_cols:
        log("scrub_summary", table=table, columns=scrub_cols,
            rows_scanned=written, rows_changed=rows_touched,
            hits=scrub_counts or {"none": 0})
    size = os.path.getsize(path)

    if written != n:
        os.remove(path)
        raise RuntimeError(f"{table}: counted {n} rows but wrote {written}. "
                           "Not advancing the watermark.")

    s3.upload_file(path, BUCKET, key)
    os.remove(path)

    if mode == "incremental" and persist:
        st.set_watermark(table, STREAM, hi)      # only after the upload is confirmed

    rec = {"invocation": RUN_ID, "table": table, "stream": STREAM, "mode": mode,
           "status": "success", "triggered_by": triggered_by,
           "range_from": lo, "range_to": hi, "s3_key": key,
           "source_rows": n, "rows_written": written, "bytes": size,
           "columns_dropped": dropped, "columns_masked": masked,
           "seconds": round(time.time() - t0, 2),
           "started_at": started.replace(tzinfo=None).isoformat(sep=" ", timespec="milliseconds"),
           "finished_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="milliseconds")}
    st.log_run(rec)
    log("table_done", **{k: v for k, v in rec.items() if k != "invocation"})
    return {"table": table, "status": "success", "rows": written, "key": key}


def lambda_handler(event, context):
    global RUN_ID
    RUN_ID = getattr(context, "aws_request_id", None) or uuid.uuid4().hex
    event = event or {}
    triggered_by = event.get("triggered_by", "eventbridge")
    only = event.get("tables")

    override = None
    if event.get("from") and event.get("to"):
        override = {"from": event["from"], "to": event["to"]}

    cfg = load_config()
    schema = cfg["schema"]
    log("invocation_start", triggered_by=triggered_by, bucket=BUCKET, schema=schema,
        state_store=state_mod.STORE, explicit_range=override, only=only)

    dbc  = get_db_config()
    salt = get_salt()
    conn = connect(dbc)
    st   = state_mod.build(conn=conn, s3=s3, bucket=BUCKET, invocation=RUN_ID)

    results = []
    try:
        for t in cfg["tables"]:
            if not t.get("enabled", True):
                continue
            if only and t["name"] not in only:
                continue
            try:
                results.append(
                    archive_table(conn, st, salt, schema, t, triggered_by, override))
            except Exception as exc:
                # One table failing does not stop the others, and its watermark
                # is left untouched.
                log("table_failed", table=t["name"], error=str(exc),
                    traceback=traceback.format_exc(limit=3))
                st.log_run({"invocation": RUN_ID, "table": t["name"], "stream": STREAM,
                            "status": "failed", "triggered_by": triggered_by,
                            "error": str(exc),
                            "started_at": datetime.now(timezone.utc)
                                          .replace(tzinfo=None).isoformat(sep=" ", timespec="milliseconds")})
                results.append({"table": t["name"], "status": "failed", "error": str(exc)})
        st.flush()
    finally:
        conn.close()

    failed = [r for r in results if r["status"] == "failed"]
    total  = sum(r.get("rows", 0) for r in results)
    log("invocation_end", tables=len(results), failed=len(failed), rows=total, results=results)

    if failed:
        raise RuntimeError(f"{len(failed)} of {len(results)} tables failed: "
                           + ", ".join(f["table"] for f in failed))
    return {"tables": len(results), "rows": total, "results": results}
