"""
Saayam request archival, backup copy.

Exports the requests table to S3, incrementally, with the six lookup tables
joined in so the file reads without a lookup sheet.

This is the full fidelity copy. Nothing is hashed, masked or dropped, because
once rows are deleted from the source this file is the only one left and
anything removed here is gone for good. De-identification is a separate stage
that reads this output and writes a different bucket.

Notes:

  * The only statement issued against an application table is SELECT. The two
    tables written to, archive_watermark and archive_run_log, are the
    pipeline's own.

  * users is not joined. There is no readable label for a person that is not
    their identity, so the three user ID columns are exported as-is.

  * Every join is a LEFT JOIN. An inner join would silently drop any request
    whose reference is null or broken, and the row count would look small
    rather than wrong.

  * Source timestamps are `timestamp without time zone`. Comparing one to
    clock_timestamp() casts via the session TimeZone, so the same query returns
    different rows depending on where it runs. Connections are pinned to UTC
    and bounds are written as `now() AT TIME ZONE 'UTC'`. Keep both.

  * The window is half-open, (lo, hi], so a row on a boundary belongs to
    exactly one run. The upper bound sits lag_minutes in the past because
    last_updated_at is set when the statement runs but the row is only visible
    once the transaction commits.

  * The watermark advances only after S3 confirms the upload. A crash before
    that leaves it unmoved, the next run recomputes the same window, and the
    key is derived from the window so a repeat overwrites rather than
    duplicates.
"""

import csv
import gzip
import io
import json
import os
import time
import traceback
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config as BotoConfig
import pg8000.native

import state as state_mod

BUCKET      = os.environ["BUCKET"]
DB_PARAM    = os.environ.get("DB_PARAM", "")
STREAM      = os.environ.get("STREAM", "backup")
COMPRESS    = os.environ.get("COMPRESS", "gzip").lower()
PREFIX      = os.environ.get("S3_PREFIX", "backup")
CONFIG_FILE = os.environ.get("CONFIG_FILE", "config.json")

# The boto default is a 60s connect timeout with retries, so in a VPC with no
# route to an endpoint one unreachable service burns 80s+ before raising.
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


def qi(n):
    return '"' + str(n).replace('"', '""') + '"'


def load_config():
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = json.load(open(os.path.join(here, CONFIG_FILE)))
    seen = set()
    for j in cfg.get("joins", []):
        for k in ("column", "table", "key", "label", "as"):
            if not j.get(k):
                raise ValueError(f"join entry missing {k}: {j}")
        if j["column"] in seen:
            raise ValueError(f"duplicate join on column {j['column']}")
        seen.add(j["column"])
    if not cfg.get("timestamp_column"):
        raise ValueError("config needs timestamp_column")
    return cfg


def get_db_config():
    # DB_CONFIG_JSON is a workaround for a VPC with no route to the SSM
    # endpoint: the deploy script reads Parameter Store where it does have a
    # route and passes the value in.
    #
    # EVALUATION ONLY. A Lambda environment variable is plaintext to anyone
    # with lambda:GetFunctionConfiguration, a much wider group than can decrypt
    # a SecureString. Remove once there is an SSM interface endpoint or a NAT.
    inline = os.environ.get("DB_CONFIG_JSON")
    if inline:
        log("db_config_source", source="env", warning="evaluation only, not for production")
        d = json.loads(inline)
    else:
        d = json.loads(ssm.get_parameter(Name=DB_PARAM, WithDecryption=True)["Parameter"]["Value"])
    return {"host": d["HOST"], "user": d["USERNAME"], "password": d["PASSWORD"],
            "database": d["DATABASE NAME"], "port": int(d.get("PORT", 5432)),
            "ssl": str(d.get("SSL", "")).lower() in ("true", "require", "required", "yes", "1")}


def connect(dbc):
    conn = pg8000.native.Connection(
        user=dbc["user"], password=dbc["password"], host=dbc["host"],
        database=dbc["database"], port=dbc["port"], timeout=30,
        ssl_context=True if dbc["ssl"] else None)
    conn.run("SET TIME ZONE 'UTC'")      # see the timestamp note at the top
    return conn


def source_columns(conn, schema, table):
    rows = conn.run(
        """SELECT column_name FROM information_schema.columns
            WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position""",
        s=schema, t=table)
    if not rows:
        raise RuntimeError(f"{schema}.{table} does not exist or is not visible")
    return [r[0] for r in rows]


def build_query(cfg, columns):
    """Return (sql, out_cols). Every source column is exported, in order, with
    each join's readable value inserted directly after its ID column."""
    schema, table = cfg["schema"], cfg["table"]
    joins = cfg.get("joins", [])
    geom = set(cfg.get("geometry_columns", []))
    by_col = {j["column"]: (i, j) for i, j in enumerate(joins)}

    select, out = [], []
    for c in columns:
        if c in geom:
            # Decoded here so the file holds POINT(lon lat) instead of PostGIS
            # hex. Nothing downstream has to know about EWKB.
            select.append(f"ST_AsText(r.{qi(c)}) AS {qi(c)}")
        else:
            select.append(f"r.{qi(c)} AS {qi(c)}")
        out.append(c)
        if c in by_col:
            i, j = by_col[c]
            select.append(f"l{i}.{qi(j['label'])} AS {qi(j['as'])}")
            out.append(j["as"])

    missing = [j["column"] for j in joins if j["column"] not in columns]
    if missing:
        raise RuntimeError(f"join columns absent from {schema}.{table}: {missing}")

    clauses = []
    for i, j in enumerate(joins):
        clauses.append(
            f"LEFT JOIN {qi(schema)}.{qi(j['table'])} l{i} "
            f"ON r.{qi(j['column'])} = l{i}.{qi(j['key'])}")

    ts, key = qi(cfg["timestamp_column"]), qi(cfg["key_column"])
    sql = (f"SELECT {', '.join(select)} "
           f"FROM {qi(schema)}.{qi(table)} r {' '.join(clauses)} "
           f"WHERE r.{ts} > :lo AND r.{ts} <= :hi "
           # req_id breaks ties so two rows with the same timestamp always come
           # out in the same order. Without it a rerun can produce a different
           # byte stream for identical data.
           f"ORDER BY r.{ts}, r.{key}")
    return sql, out


def handler(event, context):
    global RUN_ID
    RUN_ID = getattr(context, "aws_request_id", None) or uuid.uuid4().hex
    event = event or {}
    triggered_by = event.get("triggered_by", "eventbridge")
    started = datetime.now(timezone.utc)

    cfg = load_config()
    schema, table = cfg["schema"], cfg["table"]
    ts_col = cfg["timestamp_column"]
    log("invocation_start", triggered_by=triggered_by, bucket=BUCKET,
        schema=schema, table=table, state_store=state_mod.STORE)

    conn = connect(get_db_config())
    st = state_mod.build(conn=conn, s3=s3, bucket=BUCKET, invocation=RUN_ID)
    try:
        columns = source_columns(conn, schema, table)
        sql, out_cols = build_query(cfg, columns)

        # A new *_id column that nobody mapped exports as a bare number. Not
        # fatal, a missing label is better than a failed backup, but say so.
        known = ({j["column"] for j in cfg["joins"]}
                 | set(cfg.get("expected_unjoined", []))
                 | {cfg["key_column"]})
        unmapped = [c for c in columns if c.endswith("_id") and c not in known]
        if unmapped:
            log("unmapped_reference_columns", columns=unmapped,
                note="exported as raw identifiers, no readable label")

        if event.get("from") and event.get("to"):
            lo, hi, persist = event["from"], event["to"], False
        else:
            if not st.durable:
                raise RuntimeError(
                    "STATE_STORE=none has no watermark, so an incremental run has no "
                    "safe lower bound. Pass an explicit \"from\" and \"to\", or configure "
                    "a durable state store.")
            lo = st.get_watermark(table, STREAM) or cfg["initial_value"]
            hi = conn.run("SELECT (now() AT TIME ZONE 'UTC') - make_interval(mins => :m)",
                          m=int(cfg.get("lag_minutes", 5)))[0][0]
            persist = True
            if str(lo) > str(hi):
                raise RuntimeError(
                    f"watermark {lo} is ahead of bound {hi}. Refusing to run. "
                    "Check for future-dated timestamps.")

        n = conn.run(
            f"SELECT count(*) FROM {qi(schema)}.{qi(table)} r "
            f"WHERE r.{qi(ts_col)} > :lo AND r.{qi(ts_col)} <= :hi", lo=lo, hi=hi)[0][0]

        if n == 0:
            if persist:
                st.touch(table, STREAM)
            # Log empty runs too. Without a row, "fired and found nothing" and
            # "never fired" look the same.
            st.log_run({"invocation": RUN_ID, "table": table, "stream": STREAM,
                        "status": "nothing_to_do", "triggered_by": triggered_by,
                        "range_from": lo, "range_to": hi, "source_rows": 0,
                        "rows_written": 0, "bytes": 0,
                        "started_at": started.replace(tzinfo=None).isoformat(sep=" ", timespec="milliseconds"),
                        "finished_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="milliseconds")})
            st.flush()
            log("done", status="nothing_to_do", rows=0, range_from=lo, range_to=hi)
            return {"status": "nothing_to_do", "rows": 0}

        tag = lambda v: str(v).replace("-", "").replace(":", "").replace(" ", "T")[:15]
        ext = "csv.gz" if COMPRESS == "gzip" else "csv"
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = (f"{PREFIX}/{table}/ingest_date={day}/"
               f"{table}_{tag(lo)}_{tag(hi)}.{ext}")

        t0 = time.time()
        rows = conn.run(sql, lo=lo, hi=hi)

        path = f"/tmp/{uuid.uuid4().hex}.{ext}"
        written = 0
        # gzip.open stamps the current time into the header, so two runs over
        # the same window would produce different bytes for identical rows.
        # mtime=0 and an empty filename make the output deterministic, which is
        # what lets a rerun be checked byte for byte.
        raw = open(path, "wb")
        try:
            if COMPRESS == "gzip":
                gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
                fh = io.TextIOWrapper(gz, encoding="utf-8", newline="")
            else:
                gz = None
                fh = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            w = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
            w.writerow(out_cols)
            for r in rows:
                w.writerow(r)
                written += 1
            fh.flush()
            fh.detach()
            if gz is not None:
                gz.close()
        finally:
            raw.close()

        size = os.path.getsize(path)
        if written != n:
            os.remove(path)
            raise RuntimeError(f"counted {n} rows but wrote {written}. "
                               "Not advancing the watermark.")

        s3.upload_file(path, BUCKET, key)
        os.remove(path)

        if persist:
            st.set_watermark(table, STREAM, hi)   # only after the upload is confirmed

        rec = {"invocation": RUN_ID, "table": table, "stream": STREAM,
               "status": "success", "triggered_by": triggered_by,
               "range_from": lo, "range_to": hi, "s3_key": key,
               "source_rows": n, "rows_written": written, "bytes": size,
               "columns_dropped": 0, "columns_masked": 0,
               "seconds": round(time.time() - t0, 2),
               "started_at": started.replace(tzinfo=None).isoformat(sep=" ", timespec="milliseconds"),
               "finished_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="milliseconds")}
        st.log_run(rec)
        st.flush()
        log("done", **{k: v for k, v in rec.items() if k != "invocation"})
        return {"status": "success", "rows": written, "key": key, "columns": len(out_cols)}

    except Exception as exc:
        log("failed", error=str(exc), traceback=traceback.format_exc(limit=3))
        try:
            st.log_run({"invocation": RUN_ID, "table": cfg.get("table"), "stream": STREAM,
                        "status": "failed", "triggered_by": triggered_by, "error": str(exc),
                        "started_at": started.replace(tzinfo=None).isoformat(sep=" ", timespec="milliseconds")})
            st.flush()
        except Exception:
            pass
        raise
    finally:
        conn.close()


lambda_handler = handler      # the repo convention is lambda_handler
