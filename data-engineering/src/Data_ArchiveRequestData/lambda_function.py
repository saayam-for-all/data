"""Read-only, snapshot-consistent PostgreSQL requests export for issue #574."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg import sql

LOG = logging.getLogger(__name__)
LOG.setLevel(logging.INFO)
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Reference:
    """One direct requests reference, as documented by Task 1."""

    column: str
    table: str
    key: str
    label: str
    output: str


@dataclass(frozen=True)
class Config:
    """Explicit schema and mapping; identifiers are never supplied by events."""

    schema: str
    table: str
    key: str
    archive_date: str
    references: tuple[Reference, ...]
    batch_size: int = 1000
    max_bytes: int = 400_000_000

    def __post_init__(self):
        """Reject ambiguous mappings before reading any records."""
        names = [self.schema, self.table, self.key, self.archive_date]
        for ref in self.references:
            names.extend((ref.column, ref.table, ref.key, ref.label, ref.output))
        if not self.references or any(not IDENTIFIER.fullmatch(n) for n in names):
            raise ValueError("Mapping contains missing or invalid identifiers")
        for field in ("column", "output"):
            values = [getattr(ref, field) for ref in self.references]
            if len(set(values)) != len(values):
                raise ValueError(f"Duplicate mapping {field}")
        if self.key in {r.column for r in self.references}:
            raise ValueError("The request primary key must remain in the export")
        if self.batch_size < 1 or self.max_bytes < 1:
            raise ValueError("batch_size and max_bytes must be positive")


def load_config(path: str | Path | None = None) -> Config:
    """Load the reviewed mapping; ship the JSON beside the Lambda handler."""
    path = path or Path(__file__).with_name("reference_mapping.json")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Config(
        schema=os.environ.get("DB_SCHEMA", data["schema"]),
        table=data["table"],
        key=data["key"],
        archive_date=data["archive_date"],
        references=tuple(Reference(**r) for r in data["references"]),
    )


def archive_selection(event: dict, config: Config):
    """Require an explicit UTC cutoff and status policy, with bound SQL values.

    status_ids=null explicitly selects every status (including NULL); a nonempty
    integer array restricts archival to those statuses. The cutoff is exclusive.
    serviced_date is a timestamp without time zone interpreted as UTC.
    """
    if not isinstance(event, dict) or "status_ids" not in event:
        raise ValueError("Supply archive_before and status_ids (array or null)")
    cutoff = datetime.fromisoformat(
        str(event.get("archive_before", "")).replace("Z", "+00:00")
    )
    if cutoff.tzinfo is None:
        raise ValueError("archive_before must include a timezone")
    cutoff = cutoff.astimezone(UTC).replace(tzinfo=None)
    statuses = event["status_ids"]
    condition = sql.SQL("r.{} < %s").format(sql.Identifier(config.archive_date))
    params = [cutoff]
    if statuses is not None:
        if (
            not isinstance(statuses, list)
            or not statuses
            or any(type(s) is not int for s in statuses)
        ):
            raise ValueError("status_ids must be null or a nonempty integer array")
        condition += sql.SQL(" AND r.req_status_id = ANY(%s)")
        params.append(statuses)
    return condition, params


def qualified(config: Config, table: str):
    """Quote a schema-qualified table name."""
    return sql.Identifier(config.schema, table)


def inspect_source(conn, config: Config) -> list[str]:
    """Validate source columns, declared foreign keys, and mapping coverage."""
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT * FROM {} LIMIT 0").format(qualified(config, config.table))
        )
        columns = [c.name for c in cur.description]
        required = {config.key, config.archive_date} | {
            r.column for r in config.references
        }
        if not required.issubset(columns):
            raise ValueError(
                f"Mapping columns missing from source: {sorted(required - set(columns))}"
            )
        # Detect schema drift instead of silently exporting new opaque references.
        candidates = {c for c in columns if c.endswith("_id")} - {config.key}
        mapped = {r.column for r in config.references}
        if candidates - mapped:
            raise ValueError(
                f"Unmapped reference columns: {sorted(candidates - mapped)}"
            )
        outputs = [
            next((r.output for r in config.references if r.column == c), c)
            for c in columns
        ]
        if len(set(outputs)) != len(outputs):
            raise ValueError("Output names collide with source columns")
        cur.execute(
            """
            SELECT a.attname, nt.nspname, t.relname, b.attname,
                   cardinality(f.conkey)
            FROM pg_constraint f
            JOIN pg_class s ON s.oid = f.conrelid
            JOIN pg_namespace ns ON ns.oid = s.relnamespace
            JOIN pg_class t ON t.oid = f.confrelid
            JOIN pg_namespace nt ON nt.oid = t.relnamespace
            JOIN pg_attribute a ON a.attrelid=s.oid AND a.attnum=f.conkey[1]
            JOIN pg_attribute b ON b.attrelid=t.oid AND b.attnum=f.confkey[1]
            WHERE f.contype='f' AND ns.nspname=%s AND s.relname=%s
        """,
            (config.schema, config.table),
        )
        for column, schema, table, key, arity in cur.fetchall():
            ref = next((r for r in config.references if r.column == column), None)
            if (
                arity != 1
                or ref is None
                or (schema, table, key) != (config.schema, ref.table, ref.key)
            ):
                raise ValueError(f"Declared foreign key differs from mapping: {column}")
        # Refuse fan-out rather than arbitrarily choosing a lookup row.
        for table, key in sorted({(r.table, r.key) for r in config.references}):
            cur.execute(
                sql.SQL(
                    "SELECT 1 FROM {} WHERE {} IS NOT NULL GROUP BY {} HAVING COUNT(*) > 1 LIMIT 1"
                ).format(
                    qualified(config, table), sql.Identifier(key), sql.Identifier(key)
                )
            )
            if cur.fetchone():
                raise ValueError(f"Nonunique lookup key: {table}.{key}")
    return columns


def build_export_query(config: Config, columns: list[str], selection):
    """Every reference uses LEFT JOIN; readable columns replace identifier columns."""
    expressions, joins, diagnostics = [], [], []
    by_column = {r.column: (i, r) for i, r in enumerate(config.references)}
    for column in columns:
        if column not in by_column:
            expressions.append(sql.SQL("r.{}").format(sql.Identifier(column)))
            continue
        index, ref = by_column[column]
        alias = sql.Identifier(f"l{index}")
        source = sql.SQL("r.{}").format(sql.Identifier(column))
        label = sql.SQL("{}.{}").format(alias, sql.Identifier(ref.label))
        key = sql.SQL("{}.{}").format(alias, sql.Identifier(ref.key))
        expressions.append(
            sql.SQL("""CASE WHEN {source} IS NULL THEN NULL
            WHEN {key} IS NULL THEN '[UNMATCHED: ' || CAST({source} AS text) || ']'
            WHEN {label} IS NULL OR trim(CAST({label} AS text)) = ''
                THEN '[MISSING LABEL: ' || CAST({source} AS text) || ']'
            ELSE CAST({label} AS text) END AS {output}""").format(
                source=source, key=key, label=label, output=sql.Identifier(ref.output)
            )
        )
    for i, ref in enumerate(config.references):
        alias = sql.Identifier(f"l{i}")
        source = sql.SQL("r.{}").format(sql.Identifier(ref.column))
        key = sql.SQL("{}.{}").format(alias, sql.Identifier(ref.key))
        label = sql.SQL("{}.{}").format(alias, sql.Identifier(ref.label))
        joins.append(
            sql.SQL("LEFT JOIN {} AS {} ON {} = {}").format(
                qualified(config, ref.table), alias, source, key
            )
        )
        diagnostics.extend(
            [
                sql.SQL("{} IS NULL").format(source),
                sql.SQL("{} IS NOT NULL AND {} IS NULL").format(source, key),
                sql.SQL(
                    "{} IS NOT NULL AND ({} IS NULL OR trim(CAST({} AS text)) = '')"
                ).format(key, label, label),
            ]
        )
    # Diagnostic booleans are used for validation only, never written to CSV.
    query = sql.SQL("SELECT {} FROM {} AS r {} WHERE {} ORDER BY r.{}").format(
        sql.SQL(", ").join(expressions + diagnostics),
        qualified(config, config.table),
        sql.SQL(" ").join(joins),
        selection,
        sql.Identifier(config.key),
    )
    return query


def csv_value(value):
    """Encode SQL NULL distinctly from empty strings; escape literal backslashes."""
    if value is None:
        return r"\N"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    elif isinstance(value, datetime):
        value = value.isoformat(sep=" ")
    return str(value).replace("\\", "\\\\")


def export_requests(conn, event: dict, config: Config, output) -> dict:
    """Stream one validated CSV from a caller-owned, idle PostgreSQL connection.

    No source records or existing Lambda functions are modified. Failure leaves
    a partial *local* stream; callers must only publish after this returns.
    """
    selection, params = archive_selection(event, config)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SELECT set_config('statement_timeout', '600000', true)")
        columns = inspect_source(conn, config)
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT count(*), count(DISTINCT r.{}) FROM {} AS r WHERE {}"
                ).format(
                    sql.Identifier(config.key),
                    qualified(config, config.table),
                    selection,
                ),
                params,
            )
            source_count, unique_count = cur.fetchone()
        if source_count != unique_count:
            raise ValueError("Selected requests have duplicate or null request IDs")
        summary = {
            "source_count": source_count,
            "exported_count": 0,
            "duplicate_request_count": 0,
            "references": {
                r.column: {"null": 0, "unmatched": 0, "missing_label": 0}
                for r in config.references
            },
        }
        headers = [
            next((r.output for r in config.references if r.column == c), c)
            for c in columns
        ]
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(headers)
        key_index, previous_id = columns.index(config.key), None
        with conn.cursor(name="archive_" + uuid.uuid4().hex) as cur:
            cur.itersize = config.batch_size
            cur.execute(build_export_query(config, columns, selection), params)
            for row in cur:
                request_id = row[key_index]
                if request_id is None or request_id == previous_id:
                    raise ValueError("Join duplicated or lost a request identity")
                previous_id = request_id
                writer.writerow(csv_value(v) for v in row[: len(columns)])
                summary["exported_count"] += 1
                for i, ref in enumerate(config.references):
                    for j, metric in enumerate(("null", "unmatched", "missing_label")):
                        summary["references"][ref.column][metric] += int(
                            row[len(columns) + 3 * i + j]
                        )
                if output.tell() > config.max_bytes:
                    raise ValueError(
                        "Export exceeds configured local storage limit; use a smaller archival window"
                    )
        if summary["exported_count"] != source_count:
            raise ValueError("Source and exported request counts differ")
        for metrics in summary["references"].values():
            metrics["matched"] = source_count - metrics["null"] - metrics["unmatched"]
        summary["validated"] = True
        return summary


def connect_database():
    """Use an injected connection URL or AWS Secrets Manager, with TLS in AWS."""
    import boto3

    secret_id = os.environ.get("DB_SECRET_ID")
    if secret_id:
        secret = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)
        data = json.loads(secret["SecretString"])
        return psycopg.connect(
            host=data["host"],
            port=data.get("port", 5432),
            dbname=data["dbname"],
            user=data["username"],
            password=data["password"],
            sslmode="verify-full",
            connect_timeout=10,
            **(
                {"sslrootcert": os.environ["DB_SSLROOTCERT"]}
                if os.environ.get("DB_SSLROOTCERT")
                else {}
            ),
        )
    url = os.environ["DATABASE_URL"]
    options = (
        {"sslmode": "verify-full"} if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else {}
    )
    return psycopg.connect(url, connect_timeout=10, **options)


def lambda_handler(event, context):
    """Publish exactly one CSV only after count and identity validation succeeds."""
    import boto3

    bucket = os.environ["ARCHIVE_BUCKET"]
    config = load_config(os.environ.get("REFERENCE_MAPPING_PATH"))
    prefix = os.environ.get("ARCHIVE_PREFIX", "requests").strip("/")
    run_id = uuid.uuid4().hex
    key = "/".join(p for p in (prefix, f"requests_{run_id}.csv") if p)
    # TemporaryFile is deleted on success and failure. No data upload precedes validation.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="") as output:
        with connect_database() as conn:
            summary = export_requests(conn, event, config, output)
        output.flush()
        output.seek(0)
        digest = hashlib.sha256()
        while chunk := output.buffer.read(1024 * 1024):
            digest.update(chunk)
        output.buffer.seek(0)
        extra = {"ServerSideEncryption": "AES256"}
        if os.environ.get("ARCHIVE_KMS_KEY_ID"):
            extra = {
                "ServerSideEncryption": "aws:kms",
                "SSEKMSKeyId": os.environ["ARCHIVE_KMS_KEY_ID"],
            }
        boto3.client("s3").upload_fileobj(
            output.buffer,
            bucket,
            key,
            ExtraArgs={
                "ContentType": "text/csv; charset=utf-8",
                **extra,
                "Metadata": {
                    "source-count": str(summary["source_count"]),
                    "exported-count": str(summary["exported_count"]),
                    "sha256": digest.hexdigest(),
                    "validated": "true",
                },
            },
        )
    result = {
        "function": "Data_ArchiveRequestData",
        "bucket": bucket,
        "key": key,
        "sha256": digest.hexdigest(),
        **summary,
    }
    LOG.info("Archive validation: %s", json.dumps(result, sort_keys=True))
    return result
