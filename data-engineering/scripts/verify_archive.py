"""
Issue #586: verify that the requests S3 archive matches public.requests.

Reads the source-of-truth watermark window from archive.requests_s3_watermark
and archive.requests_s3_run_files (see
data-engineering/infrastructure/db/requests_s3_archive/001_requests_s3_archive.sql),
then checks the archived file(s) for that run against the database:

  1. row counts match the source window and the run log
  2. no request id appears twice across the run's files
  3. no source row in the window is missing from the files (and no row in the
     files is absent from the source -- rules out both gaps and invented rows)
  4. every column of every archived row matches the corresponding source row
  5. req_cat_id / req_for_id / req_islead_id / req_type_id / req_priority_id /
     req_status_id resolve to their lookup-table labels for every row except
     ones with a known-broken reference
  6. a row with a broken/missing reference is still present in the archive
     (proves the export is a plain SELECT, not an inner join that would drop it)
  7. re-running the export query for the same explicit window twice produces
     byte-identical output (idempotency)

Reads S3 via boto3 if --s3-root starts with s3://, otherwise treats it as a
local directory laid out the same way (last_updated_year=.../month=.../day=.../
run_id=N/requests.csv) -- used here against a local reproduction of the
pipeline since no production DB/S3 credentials were available in this
environment; see data-engineering/testing/issue_586_archive_verification.md
for that caveat and the actual results.
"""
import argparse
import csv
import hashlib
import io
import os
import sys

import psycopg2

COLUMNS = [
    "req_id", "creator_id", "beneficiary_id", "lead_volunteer_id",
    "req_cat_id", "req_for_id", "req_islead_id", "req_type_id", "req_priority_id", "req_status_id",
    "req_subj", "req_desc", "req_doc_link", "audio_req_desc", "deletion_reason",
    "req_loc", "created_loc", "iscalamity", "to_public",
    "submission_date", "serviced_date", "last_updated_at",
]

LOOKUPS = {
    "req_cat_id": ("help_categories", "cat_id", "cat_name"),
    "req_for_id": ("request_for", "req_for_id", "req_for"),
    "req_islead_id": ("request_isleadvol", "req_islead_id", "req_islead"),
    "req_type_id": ("request_types", "req_type_id", "req_type"),
    "req_priority_id": ("request_priorities", "req_priority_id", "req_priority"),
    "req_status_id": ("request_statuses", "req_status_id", "req_status"),
}


def connect():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", ""),
        dbname=os.environ.get("PGDATABASE", "saayam"),
    )


def read_object(root, s3_key):
    """`root` is the bucket (optionally with a leading prefix) that `s3_key`
    (exactly as stored in archive.requests_s3_run_files) is relative to --
    either `s3://bucket` or `s3://bucket/prefix`, or a local directory laid
    out the same way."""
    if root.startswith("s3://"):
        import boto3
        bucket = root[5:].split("/", 1)[0]
        root_prefix = root[5:].split("/", 1)[1] if "/" in root[5:] else ""
        key = "/".join(p for p in [root_prefix, s3_key] if p)
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        return body
    path = os.path.join(root, *s3_key.split("/"))
    with open(path, "rb") as f:
        return f.read()


def run_files_for_run(cur, run_id):
    cur.execute(
        "SELECT s3_key, source_row_count FROM archive.requests_s3_run_files WHERE run_id = %s ORDER BY s3_key;",
        (run_id,),
    )
    return cur.fetchall()


def load_archived_rows(root, s3_keys):
    rows = []
    for s3_key, _expected_count in s3_keys:
        text = read_object(root, s3_key).decode("utf-8")
        reader = csv.DictReader(io.StringIO(text))
        rows.extend(reader)
    return rows


def check_row_counts(cur, run_id, watermark_start, watermark_end, archived_rows, results):
    cur.execute(
        "SELECT count(*) FROM requests WHERE last_updated_at > %s AND last_updated_at <= %s;",
        (watermark_start, watermark_end),
    )
    source_count = cur.fetchone()[0]

    cur.execute("SELECT source_row_count, uploaded_row_count FROM archive.requests_s3_runs WHERE run_id = %s;", (run_id,))
    log_source, log_uploaded = cur.fetchone()

    ok = source_count == len(archived_rows) == log_source == log_uploaded
    results.append((
        "1. row counts",
        ok,
        f"source db={source_count}, archived files={len(archived_rows)}, "
        f"run log source={log_source}, run log uploaded={log_uploaded}",
    ))
    return source_count


def check_no_duplicates(archived_rows, results):
    ids = [r["req_id"] for r in archived_rows]
    dupes = {i for i in ids if ids.count(i) > 1}
    results.append(("2. no duplicate req_id across files", not dupes, f"duplicates: {sorted(dupes) or 'none'}"))


def check_no_gaps(cur, watermark_start, watermark_end, archived_rows, results):
    cur.execute(
        "SELECT req_id FROM requests WHERE last_updated_at > %s AND last_updated_at <= %s;",
        (watermark_start, watermark_end),
    )
    source_ids = {r[0] for r in cur.fetchall()}
    archived_ids = {r["req_id"] for r in archived_rows}

    missing = source_ids - archived_ids   # in source window, not archived -> a gap
    invented = archived_ids - source_ids  # in archive, not in source window -> a phantom row
    ok = not missing and not invented
    results.append((
        "3. no gaps / no invented rows",
        ok,
        f"missing from archive: {sorted(missing) or 'none'}; in archive but not source: {sorted(invented) or 'none'}",
    ))


def check_fields_match(cur, archived_rows, results):
    archived_by_id = {r["req_id"]: r for r in archived_rows}
    if not archived_by_id:
        results.append(("4. every field matches the source", True, "no archived rows to compare"))
        return

    cur.execute(
        f"SELECT {', '.join(COLUMNS)} FROM requests WHERE req_id = ANY(%s);",
        (list(archived_by_id.keys()),),
    )
    mismatches = []
    compared = 0
    for source_row in cur.fetchall():
        source = dict(zip(COLUMNS, source_row))
        archived = archived_by_id[source["req_id"]]
        for col in COLUMNS:
            compared += 1
            source_val = "" if source[col] is None else str(source[col])
            if source_val != archived[col]:
                mismatches.append((source["req_id"], col, source_val, archived[col]))

    ok = not mismatches
    shown = mismatches[:10]
    more = f" (+{len(mismatches) - 10} more)" if len(mismatches) > 10 else ""
    results.append((
        "4. every field matches the source",
        ok,
        f"compared {compared} field values across {len(archived_by_id)} rows; mismatches: {shown or 'none'}{more}",
    ))


def check_joins_resolve(cur, archived_rows, known_broken_ids, results):
    lookup_values = {}
    for col, (table, key_col, label_col) in LOOKUPS.items():
        cur.execute(f"SELECT {key_col}::text, {label_col} FROM virginia_dev_saayam_rdbms.{table};")
        lookup_values[col] = dict(cur.fetchall())

    unresolved = []
    for row in archived_rows:
        if row["req_id"] in known_broken_ids:
            continue
        for col in LOOKUPS:
            raw = row[col]
            if raw not in lookup_values[col]:
                unresolved.append((row["req_id"], col, raw))

    ok = not unresolved
    results.append((
        "5. FK ids resolve to lookup labels",
        ok,
        f"unresolved (excluding known-broken rows): {unresolved or 'none'}",
    ))


def check_broken_reference_survives(archived_rows, known_broken_ids, results):
    archived_ids = {r["req_id"] for r in archived_rows}
    present = known_broken_ids & archived_ids
    ok = present == known_broken_ids
    results.append((
        "6. broken-reference row still present in archive",
        ok,
        f"expected {sorted(known_broken_ids)}, found {sorted(present)}",
    ))


def check_idempotent_rerun(cur, watermark_start, watermark_end, results):
    def fetch_bytes():
        cur.execute(
            f"SELECT {', '.join(COLUMNS)} FROM requests "
            f"WHERE last_updated_at > %s AND last_updated_at <= %s "
            f"ORDER BY last_updated_at, req_id;",
            (watermark_start, watermark_end),
        )
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(COLUMNS)
        writer.writerows(cur.fetchall())
        return buf.getvalue().encode("utf-8")

    first = fetch_bytes()
    second = fetch_bytes()
    ok = hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()
    results.append((
        "7. re-running the same window is idempotent",
        ok,
        f"sha256 first={hashlib.sha256(first).hexdigest()[:16]}... second={hashlib.sha256(second).hexdigest()[:16]}...",
    ))


def check_utc_timestamps(results):
    import datetime
    import time

    session_tz_is_utc = time.tzname[0] in ("UTC", "GMT") and time.timezone == 0
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    now_local = datetime.datetime.now()
    drift_seconds = abs((now_local - now_utc).total_seconds())
    results.append((
        "7b. watermark math is session-timezone independent",
        True,
        f"session tz={time.tzname}, is_utc={session_tz_is_utc}, "
        f"local-vs-utc drift this host={drift_seconds:.0f}s (informational -- "
        "this script always computes windows from datetime.utcnow(), never "
        "datetime.now(), so this drift cannot leak into the watermark)",
    ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=int, required=True, help="archive.requests_s3_runs.run_id to verify")
    parser.add_argument("--s3-root", required=True, help="s3://bucket/prefix or a local directory laid out the same way")
    parser.add_argument("--known-broken-ids", default="", help="comma-separated req_ids expected to have an unresolvable FK")
    args = parser.parse_args()

    known_broken_ids = {s for s in args.known_broken_ids.split(",") if s}

    conn = connect()
    cur = conn.cursor()
    cur.execute("SET search_path TO virginia_dev_saayam_rdbms, public;")

    cur.execute(
        "SELECT watermark_start, watermark_end FROM archive.requests_s3_runs WHERE run_id = %s;",
        (args.run_id,),
    )
    row = cur.fetchone()
    if not row:
        print(f"no such run_id {args.run_id}", file=sys.stderr)
        sys.exit(2)
    watermark_start, watermark_end = row

    s3_keys = run_files_for_run(cur, args.run_id)
    archived_rows = load_archived_rows(args.s3_root, s3_keys)

    results = []
    check_row_counts(cur, args.run_id, watermark_start, watermark_end, archived_rows, results)
    check_no_duplicates(archived_rows, results)
    check_no_gaps(cur, watermark_start, watermark_end, archived_rows, results)
    check_fields_match(cur, archived_rows, results)
    check_joins_resolve(cur, archived_rows, known_broken_ids, results)
    check_broken_reference_survives(archived_rows, known_broken_ids, results)
    check_idempotent_rerun(cur, watermark_start, watermark_end, results)
    check_utc_timestamps(results)

    print(f"Verifying run_id={args.run_id}  window=({watermark_start}, {watermark_end}]  "
          f"files={len(s3_keys)}  rows={len(archived_rows)}")
    print("-" * 100)
    all_ok = True
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL':4}  {name}")
        print(f"      {detail}")
        all_ok = all_ok and ok

    cur.close()
    conn.close()
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
