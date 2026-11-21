"""Validated invocation settings and the schema-backed reference mapping."""

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping


FUNCTION_NAME = "Data_ArchiveRequestData"


@dataclass(frozen=True)
class Reference:
    """A many-to-one lookup declared in the Task 573 schema."""

    source: str
    table: str
    key: str
    label: str
    output: str


REFERENCES = (
    Reference("req_cat_id", "help_categories", "cat_id", "cat_name", "req_category"),
    Reference("req_for_id", "request_for", "req_for_id", "req_for", "req_for"),
    Reference("req_islead_id", "request_isleadvol", "req_islead_id", "req_islead", "req_islead"),
    Reference("req_type_id", "request_types", "req_type_id", "req_type", "req_type"),
    Reference("req_priority_id", "request_priorities", "req_priority_id", "req_priority", "req_priority"),
    Reference("req_status_id", "request_statuses", "req_status_id", "req_status", "req_status"),
)


def utc_timestamp(value: str) -> datetime:
    """Require an explicit timezone, then normalize to naive UTC for the DB."""
    if not isinstance(value, str):
        raise ValueError("Window bounds must be ISO 8601 strings with a timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Window bounds must be ISO 8601 timestamps") from exc
    if parsed.tzinfo is None:
        raise ValueError("Window bounds must include a timezone, for example Z")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class Settings:
    """One snapshot or an explicitly bounded incremental export."""

    bucket: str
    prefix: str
    schema: str
    start: datetime | None
    end: datetime | None
    dry_run: bool
    batch_size: int
    max_rows: int
    max_bytes: int
    kms_key_id: str | None

    @classmethod
    def from_event(cls, event: dict, environ: Mapping[str, str] | None = None):
        """Reject ambiguous input before opening database or AWS connections."""
        env = os.environ if environ is None else environ
        if not isinstance(event, dict):
            raise ValueError("event must be a JSON object")
        allowed = {"watermark_start", "watermark_end", "dry_run"}
        if set(event) - allowed:
            raise ValueError("Unknown event keys: " + ", ".join(sorted(set(event) - allowed)))
        dry_run = event.get("dry_run", False)
        if not isinstance(dry_run, bool):
            raise ValueError("dry_run must be a JSON boolean")
        bucket = env.get("ARCHIVE_S3_BUCKET", "")
        if not dry_run and not bucket:
            raise ValueError("ARCHIVE_S3_BUCKET is required for an upload")
        prefix = env.get("ARCHIVE_S3_PREFIX", "request_archive").strip("/")
        if any(part in {".", ".."} for part in prefix.split("/")) or "\\" in prefix:
            raise ValueError("ARCHIVE_S3_PREFIX must be an S3 prefix without traversal")
        schema = env.get("ARCHIVE_DB_SCHEMA", "virginia_dev_saayam_rdbms")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError("ARCHIVE_DB_SCHEMA must be a simple SQL identifier")
        has_start, has_end = "watermark_start" in event, "watermark_end" in event
        if has_start != has_end:
            raise ValueError("watermark_start and watermark_end must be supplied together")
        start = utc_timestamp(event["watermark_start"]) if has_start else None
        end = utc_timestamp(event["watermark_end"]) if has_end else None
        if start is not None and start >= end:
            raise ValueError("watermark_start must precede watermark_end")
        limits = []
        for key, default, ceiling in (
            ("ARCHIVE_BATCH_SIZE", 1000, 10000),
            ("ARCHIVE_MAX_ROWS", 250000, 10000000),
            ("ARCHIVE_MAX_BYTES", 268435456, 1073741824),
        ):
            try:
                number = int(env.get(key, str(default)))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{key} must be an integer") from exc
            if not 1 <= number <= ceiling:
                raise ValueError(f"{key} must be between 1 and {ceiling}")
            limits.append(number)
        return cls(bucket, prefix, schema, start, end, dry_run, *limits,
                   env.get("ARCHIVE_KMS_KEY_ID") or None)
