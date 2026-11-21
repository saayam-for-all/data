"""Build and validate one enriched CSV before permitting any upload."""

import csv
import hashlib
import io
import json
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import FUNCTION_NAME, REFERENCES
from .db_client import quote_identifier as qi


class ValidationError(RuntimeError):
    """The source cannot be archived without ambiguity or data loss."""


def build_export_query(db, columns, settings):
    """Preserve all source columns and place each label beside its source ID."""
    lookup_by_source = {ref.source: (index, ref) for index, ref in enumerate(REFERENCES)}
    projection, headers, joins = [], [], []
    for column in columns:
        projection.append(f"r.{qi(column)}")
        headers.append(column)
        if column in lookup_by_source:
            index, ref = lookup_by_source[column]
            projection.append(f"l{index}.{qi(ref.label)} AS {qi(ref.output)}")
            headers.append(ref.output)
    # Match markers distinguish a missing target from a target with a null label.
    for index, ref in enumerate(REFERENCES):
        joins.append(f"LEFT JOIN {db.table(ref.table)} l{index} "
                     f"ON r.{qi(ref.source)} = l{index}.{qi(ref.key)}")
        projection.append(f"l{index}.{qi(ref.key)} AS {qi('_match_' + ref.source)}")
    where, params = db.selection(settings)
    query = (f"SELECT {', '.join(projection)} FROM {db.table('requests')} r "
             f"{' '.join(joins)} {where} ORDER BY r.req_id")
    return query, params, headers


def inspect_source(db, settings):
    """Check schema, request identities and lookup uniqueness in this snapshot."""
    columns = db.columns("requests")
    required = {"req_id", "last_updated_at", "creator_id", "beneficiary_id", "lead_volunteer_id"}
    required.update(ref.source for ref in REFERENCES)
    missing = required - set(columns)
    collisions = set(columns) & {ref.output for ref in REFERENCES}
    if missing or collisions:
        raise ValidationError(f"Request schema mismatch; missing={sorted(missing)}, "
                              f"readable column collisions={sorted(collisions)}")
    with db.cursor() as cursor:
        for ref in REFERENCES:
            if not {ref.key, ref.label} <= set(db.columns(ref.table)):
                raise ValidationError(f"Required key/label absent from {ref.table}")
            cursor.execute(f"SELECT {qi(ref.key)} FROM {db.table(ref.table)} "
                           f"WHERE {qi(ref.key)} IS NOT NULL GROUP BY {qi(ref.key)} "
                           "HAVING COUNT(*) > 1 LIMIT 1")
            if cursor.fetchone() is not None:
                raise ValidationError(f"Duplicate lookup key in {ref.table}; refusing a multiplying join")
        where, params = db.selection(settings)
        cursor.execute(f"SELECT COUNT(*), COUNT(DISTINCT r.req_id) "
                       f"FROM {db.table('requests')} r {where}", params)
        source_count, distinct_count = cursor.fetchone()
        if source_count != distinct_count:
            raise ValidationError("Selected requests contain duplicate or null req_id values")
        if source_count > settings.max_rows:
            raise ValidationError("ARCHIVE_MAX_ROWS exceeded; use a smaller archival window")
        cursor.execute(f"SELECT COUNT(*) FROM {db.table('requests')} WHERE last_updated_at IS NULL")
        null_timestamps = cursor.fetchone()[0]
    return columns, source_count, null_timestamps


def csv_value(value):
    """Serialize DB values without masking, truncating or changing free text."""
    if isinstance(value, (bytes, memoryview)):
        return bytes(value).hex()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


@contextmanager
def create_archive(db, settings):
    """Yield a validated binary CSV and report; always dispose of the spool."""
    # The file spills to /tmp after 8 MiB; memory use is bounded by batch size.
    with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as binary:
        output = io.TextIOWrapper(binary, encoding="utf-8", newline="")
        try:
            with db.snapshot():
                columns, source_count, null_timestamps = inspect_source(db, settings)
                query, params, headers = build_export_query(db, columns, settings)
                writer = csv.writer(output, lineterminator="\n")
                writer.writerow(headers)
                indices = {name: index for index, name in enumerate(headers)}
                audit = {ref.source: {"table": ref.table, "key": ref.key,
                                     "readable_column": ref.output, "matched": 0,
                                     "null": 0, "unmatched": 0, "missing_label": 0}
                         for ref in REFERENCES}
                exported = 0
                previous_id = None
                with db.cursor(stream=True) as cursor:
                    cursor.execute(query, params)
                    while True:
                        batch = cursor.fetchmany(settings.batch_size)
                        if not batch:
                            break
                        for row in batch:
                            request_id = row[indices["req_id"]]
                            if request_id is None or request_id == previous_id:
                                raise ValidationError("Export contains a duplicate or null req_id")
                            previous_id = request_id
                            for index, ref in enumerate(REFERENCES):
                                values = audit[ref.source]
                                if row[indices[ref.source]] is None:
                                    values["null"] += 1
                                elif row[len(headers) + index] is None:
                                    values["unmatched"] += 1
                                else:
                                    values["matched"] += 1
                                    if row[indices[ref.output]] is None:
                                        values["missing_label"] += 1
                            writer.writerow(csv_value(value) for value in row[:len(headers)])
                            exported += 1
                            if exported > settings.max_rows:
                                raise ValidationError("Export row limit exceeded")
                        output.flush()
                        if binary.tell() > settings.max_bytes:
                            raise ValidationError("ARCHIVE_MAX_BYTES exceeded; narrow the window")
                if exported != source_count:
                    raise ValidationError(f"Source/export row mismatch: {source_count} != {exported}")
                if any(item["matched"] + item["null"] + item["unmatched"] != exported
                       for item in audit.values()):
                    raise ValidationError("Reference audit does not reconcile")
            output.flush()
            byte_count = binary.tell()
            if byte_count > settings.max_bytes:
                raise ValidationError("ARCHIVE_MAX_BYTES exceeded")
            output.detach()
            output = None
            binary.seek(0)
            digest = hashlib.file_digest(binary, "sha256").hexdigest()
            binary.seek(0)
            window = {"start_exclusive": settings.start.isoformat() + "Z",
                      "end_inclusive": settings.end.isoformat() + "Z"} if settings.start else None
            report = {
                "function": FUNCTION_NAME, "validation": "passed",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "mode": "incremental" if window else "snapshot", "window": window,
                "source_count": source_count, "exported_count": exported,
                "distinct_request_count": exported, "duplicate_request_count": 0,
                "source_null_timestamps": null_timestamps,
                "excluded_null_timestamps": null_timestamps if window else 0,
                "columns": headers, "references": audit, "sha256": digest,
                "bytes": byte_count, "source_read_only": True,
                "watermark_managed_by": "caller", "database_backend": db.dialect,
            }
            yield binary, report
        finally:
            # Keep ownership with the outer context even if serialization fails.
            if output is not None:
                output.detach()


def object_key(settings, report):
    """Use content-addressed names: identical retries reuse the same object."""
    if settings.start:
        stamp = lambda value: value.strftime("%Y%m%dT%H%M%S%fZ")
        partition = f"window={stamp(settings.start)}_{stamp(settings.end)}"
    else:
        partition = "snapshot"
    parts = [settings.prefix, "requests", partition, report["sha256"] + ".csv"]
    return "/".join(part for part in parts if part)
