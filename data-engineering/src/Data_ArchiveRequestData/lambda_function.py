"""Data_ArchiveRequestData: export the requests table as one enriched CSV (issue #574).

Every column of requests that references another table (the nine foreign keys
documented in #573) is LEFT JOINed to its lookup table and replaced by the
readable value, so the file can be understood without separate lookup files.
LEFT JOIN keeps requests whose references are null; each join is on a primary
key, so a request can never be duplicated.

Environment: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, DB_SCHEMA
(default virginia_dev_saayam_rdbms), S3_BUCKET, S3_PREFIX (default "requests"),
LOCAL_OUTPUT_DIR (default /tmp).

Event (all optional): {"last_updated_from": "2026-01-01T00:00:00",
                       "last_updated_to": "2026-02-01T00:00:00"}
selects requests with last_updated_from <= last_updated_at < last_updated_to
(timestamps are UTC by convention). With no bounds every request is exported.
"""

import csv
import json
import logging
import os
from datetime import datetime, timezone

import psycopg2
from psycopg2 import sql

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DEFAULT_SCHEMA = "virginia_dev_saayam_rdbms"

# (alias, lookup table, lookup key, readable column, requests column, output column)
# Identifiers are fixed here and never taken from the event.
REFERENCES = (
    ("creator", "users", "user_id", "full_name", "creator_id", "creator_name"),
    ("beneficiary", "users", "user_id", "full_name", "beneficiary_id", "beneficiary_name"),
    ("lead_vol", "users", "user_id", "full_name", "lead_volunteer_id", "lead_volunteer_name"),
    ("cat", "help_categories", "cat_id", "cat_name", "req_cat_id", "help_category"),
    ("rfor", "request_for", "req_for_id", "req_for", "req_for_id", "request_for"),
    ("islead", "request_isleadvol", "req_islead_id", "req_islead", "req_islead_id", "is_lead_volunteer"),
    ("rtype", "request_types", "req_type_id", "req_type", "req_type_id", "request_type"),
    ("prio", "request_priorities", "req_priority_id", "req_priority", "req_priority_id", "request_priority"),
    ("status", "request_statuses", "req_status_id", "req_status", "req_status_id", "request_status"),
)

PLAIN_COLUMNS = (
    "req_id", "req_subj", "req_desc", "req_doc_link", "audio_req_desc",
    "deletion_reason", "iscalamity", "to_public", "submission_date",
    "serviced_date", "last_updated_at",
)
GEOMETRY_COLUMNS = ("req_loc", "created_loc")


def output_columns():
    """Header of the exported CSV, in order."""
    return (
        ["req_id"]
        + [ref[5] for ref in REFERENCES]
        + [c for c in PLAIN_COLUMNS if c != "req_id"]
        + list(GEOMETRY_COLUMNS)
    )


def _parse_bound(value, name):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be an ISO-8601 timestamp, got {value!r}")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def build_where(event):
    """Return (WHERE fragment, params) for the optional last_updated_at window."""
    start = _parse_bound(event.get("last_updated_from"), "last_updated_from")
    end = _parse_bound(event.get("last_updated_to"), "last_updated_to")
    if start and end and start >= end:
        raise ValueError("last_updated_from must be earlier than last_updated_to")
    clauses, params = [], []
    if start:
        clauses.append(sql.SQL("r.last_updated_at >= %s"))
        params.append(start)
    if end:
        clauses.append(sql.SQL("r.last_updated_at < %s"))
        params.append(end)
    where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(clauses) if clauses else sql.SQL("")
    return where, params


def build_queries(schema, where):
    """Build the export query (nine LEFT JOINs) and the source count query."""
    select = [sql.SQL("r.req_id")]
    for alias, _t, _k, label, _c, out in REFERENCES:
        select.append(sql.SQL("{}.{} AS {}").format(
            sql.Identifier(alias), sql.Identifier(label), sql.Identifier(out)))
    select += [sql.SQL("r.{}").format(sql.Identifier(c)) for c in PLAIN_COLUMNS if c != "req_id"]
    # Geometry is exported as readable WKT, e.g. POINT(-122.4 37.8).
    select += [sql.SQL("public.ST_AsText(r.{}) AS {}").format(sql.Identifier(c), sql.Identifier(c))
               for c in GEOMETRY_COLUMNS]

    joins = [
        sql.SQL("LEFT JOIN {}.{} {} ON {}.{} = r.{}").format(
            sql.Identifier(schema), sql.Identifier(table), sql.Identifier(alias),
            sql.Identifier(alias), sql.Identifier(key), sql.Identifier(col))
        for alias, table, key, _l, col, _o in REFERENCES
    ]
    requests = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier("requests"))
    export = sql.SQL("SELECT {} FROM {} r {}{} ORDER BY r.req_id").format(
        sql.SQL(", ").join(select), requests, sql.SQL(" ").join(joins), where)
    count = sql.SQL("SELECT count(*) FROM {} r{}").format(requests, where)
    return export, count


def connect():
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def export_requests(conn, schema, event, path, batch_size=1000):
    """Write the enriched CSV to path; return the validation counts."""
    where, params = build_where(event)
    export_sql, count_sql = build_queries(schema, where)

    # Read-only snapshot, so the count and the export see the same rows.
    conn.set_session(isolation_level="REPEATABLE READ", readonly=True)
    try:
        with conn.cursor() as cur:
            cur.execute(count_sql, params)
            source_count = cur.fetchone()[0]

        exported = 0
        seen = set()
        with open(path, "w", newline="", encoding="utf-8") as fh, \
                conn.cursor(name="archive_requests") as cur:
            writer = csv.writer(fh)
            writer.writerow(output_columns())
            cur.itersize = batch_size
            cur.execute(export_sql, params)
            for row in cur:
                seen.add(row[0])
                writer.writerow(["" if v is None else v for v in row])
                exported += 1
    finally:
        conn.rollback()

    result = {
        "source_count": source_count,
        "exported_count": exported,
        "duplicate_requests": exported - len(seen),
    }
    if exported != source_count or result["duplicate_requests"]:
        raise RuntimeError(f"Export does not match source: {result}")
    return result


def lambda_handler(event, context):
    event = event or {}
    schema = os.environ.get("DB_SCHEMA", DEFAULT_SCHEMA)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"requests_enriched_{stamp}.csv"
    path = os.path.join(os.environ.get("LOCAL_OUTPUT_DIR", "/tmp"), filename)

    try:
        conn = connect()
        try:
            result = export_requests(conn, schema, event, path)
        finally:
            conn.close()

        bucket = os.environ.get("S3_BUCKET")
        if bucket:
            import boto3
            key = f"{os.environ.get('S3_PREFIX', 'requests').strip('/')}/{filename}"
            boto3.client("s3").upload_file(path, bucket, key)
            result["s3_uri"] = f"s3://{bucket}/{key}"
        result["local_path"] = path
        logger.info("Archived requests: %s", result)
        return {"statusCode": 200, "body": json.dumps(result)}
    except ValueError as exc:
        return {"statusCode": 400, "body": json.dumps({"error": str(exc)})}
    except Exception as exc:
        logger.exception("Request archive failed")
        return {"statusCode": 500, "body": json.dumps({"error": str(exc)})}
