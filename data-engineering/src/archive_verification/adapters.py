"""Seams for the archive verification harness (#586).

Three things vary between a local run and a run against the real pipeline, so
each is a seam rather than a hard-coded choice:

* **Source** - where request rows are read from. ``SqliteSource`` is the local
  copy of the schema that #586 asks for, because the real database is read only
  and a broken-reference row has to be created somewhere. ``PostgresSource``
  reads the real schema and is the only source that can answer check 7b.
* **Archive** - where exported files live. ``LocalDirectoryArchive`` needs no
  credentials; ``S3Archive`` is for whoever has S3 access. ``CONTRIBUTING.md``
  says contributors do not, hence the local one is the default.
* **Extract** - the query under test. Resolved from a ``module:callable``
  string so Task 2's Lambda can be dropped in without touching this harness.

``boto3`` is imported lazily and tolerated absent, so the default path adds no
dependency to ``requirements.txt``.
"""

from __future__ import annotations

import csv
import importlib
import io
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

try:  # pragma: no cover - exercised only where psycopg2 is installed
    import psycopg2
except ImportError:  # pragma: no cover
    psycopg2 = None  # type: ignore[assignment]

HERE = Path(__file__).resolve().parent
SCHEMA_SQL = HERE / "fixture_schema.sql"
EXTRACT_SQL = HERE / "fixture_extract.sql"

#: Canonical timestamp form. Lexical order equals chronological order, which is
#: what lets the half-open window predicate work identically against SQLite TEXT
#: and Postgres ``timestamp(6)``, microsecond ties included.
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


def format_timestamp(value: Optional[datetime]) -> str:
    """Render a datetime in the canonical form, or '' for None.

    Any tz-aware value is rejected rather than silently converted. Every column
    in this schema is ``timestamp without time zone`` holding UTC by
    convention, so an aware value reaching here means a caller has mixed the
    two representations - the bug check 7a exists to catch.
    """
    if value is None:
        return ""
    if value.tzinfo is not None:
        raise ValueError(
            f"expected a naive UTC datetime, got tz-aware {value!r}; "
            "see check 7a - this schema stores 'timestamp without time zone'"
        )
    return value.strftime(TIMESTAMP_FORMAT)


def parse_timestamp(value: str) -> datetime:
    """Parse the canonical form back into a naive datetime."""
    return datetime.strptime(value, TIMESTAMP_FORMAT)


# --------------------------------------------------------------------- sources


class Source:
    """A place request rows can be read from.

    Subclasses supply a parameter marker and a table-name prefix, which is all
    ``fixture_extract.sql`` needs to run unchanged on either dialect.
    """

    param_marker = "?"
    table_prefix = ""
    supports_session_time_zone = False

    def query(self, sql: str, params: Sequence[Any] = ()) -> tuple[list[str], list[tuple]]:
        """Run a read query, returning (column_names, rows)."""
        raise NotImplementedError

    def set_session_time_zone(self, time_zone: str) -> None:
        """Set the session time zone, for check 7b."""
        raise NotImplementedError

    def render(self, sql: str) -> str:
        """Substitute the dialect placeholders in a query template."""
        return sql.replace("{prefix}", self.table_prefix).replace("{p}", self.param_marker)

    def close(self) -> None:
        """Release the underlying connection."""


class SqliteSource(Source):
    """The local copy of the schema, held in SQLite.

    This is the "build a local copy of the schema" half of #586. It is the
    default because it needs no container, no credentials and no network, and
    because it is writable - the real source is read only, so the
    broken-reference row of check 5 cannot be created there.

    Foreign keys are enforced by default, which is the point: it means the
    dangling row in check 5b has to be inserted with enforcement explicitly
    disabled, mirroring the fact that production's constraints make that state
    unreachable by any ordinary write.
    """

    param_marker = "?"
    table_prefix = ""
    supports_session_time_zone = False

    def __init__(self, path: str = ":memory:") -> None:
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA foreign_keys = ON")

    def query(self, sql: str, params: Sequence[Any] = ()) -> tuple[list[str], list[tuple]]:
        """Run a read query, returning (column_names, rows)."""
        cursor = self.connection.execute(sql, tuple(params))
        columns = [description[0] for description in cursor.description or []]
        rows = [tuple(row) for row in cursor.fetchall()]
        cursor.close()
        return columns, rows

    def executescript(self, script: str) -> None:
        """Apply a multi-statement DDL script."""
        self.connection.executescript(script)

    def set_foreign_keys(self, enabled: bool) -> None:
        """Turn foreign key enforcement on or off.

        Disabling it is how check 5b creates a dangling reference. SQLite has no
        ``ALTER TABLE ... DROP CONSTRAINT``; this pragma is the local equivalent
        of dropping the constraint in Postgres, and it represents the same
        real-world risk - a bulk load that runs with constraints disabled.

        The commit is required, not tidiness: ``PRAGMA foreign_keys`` is a
        **silent no-op inside an open transaction**. Without committing first,
        enforcement stays on, the dangling insert fails, and the error points at
        the insert rather than at the pragma that never applied. The read-back
        turns that silence into an exception.
        """
        self.connection.commit()
        self.connection.execute(f"PRAGMA foreign_keys = {'ON' if enabled else 'OFF'}")
        actual = bool(self.connection.execute("PRAGMA foreign_keys").fetchone()[0])
        if actual is not enabled:
            raise RuntimeError(
                "PRAGMA foreign_keys did not take effect - it is ignored inside "
                "an open transaction; commit before calling this"
            )

    def close(self) -> None:
        """Release the underlying connection."""
        self.connection.close()


class PostgresSource(Source):
    """The real source database, read only.

    Reads connection details from the environment names already used by
    ``.env.example``. This is the only source that can answer check 7b, because
    a session time zone is a Postgres concept and #586's concern - "a wrong
    session time zone shifts the extraction window silently" - cannot be
    reproduced anywhere else.
    """

    param_marker = "%s"
    supports_session_time_zone = True

    def __init__(self, schema: str = "virginia_dev_saayam_rdbms") -> None:
        if psycopg2 is None:  # pragma: no cover
            raise RuntimeError("psycopg2 is required for --source postgres")
        self.table_prefix = f"{schema}." if schema else ""
        self.connection = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "saayam"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        # Nothing here may write. #586: "You cannot insert into the source
        # database, it is read only."
        self.connection.set_session(readonly=True, autocommit=True)

    def query(self, sql: str, params: Sequence[Any] = ()) -> tuple[list[str], list[tuple]]:
        """Run a read query, returning (column_names, rows)."""
        with self.connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            columns = [description[0] for description in cursor.description or []]
            rows = [tuple(row) for row in cursor.fetchall()]
        return columns, rows

    def set_session_time_zone(self, time_zone: str) -> None:
        """Set the session time zone, for check 7b."""
        with self.connection.cursor() as cursor:
            cursor.execute(f"SET TIME ZONE '{time_zone}'")

    def close(self) -> None:
        """Release the underlying connection."""
        self.connection.close()


# -------------------------------------------------------------------- archives


class Archive:
    """Somewhere exported files are written to and read back from."""

    def write(self, key: str, payload: str) -> None:
        """Store a file, replacing any file already at that key."""
        raise NotImplementedError

    def read(self, key: str) -> str:
        """Read a file back as text."""
        raise NotImplementedError

    def keys(self) -> list[str]:
        """List every file currently stored, sorted."""
        raise NotImplementedError


class LocalDirectoryArchive(Archive):
    """Files on local disk. The default, because it needs no credentials.

    Writes are newline-exact: ``newline=""`` keeps the ``\\n`` line terminator
    the extract chose, instead of letting Windows rewrite it to ``\\r\\n`` and
    make a byte comparison depend on the platform.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def write(self, key: str, payload: str) -> None:
        """Store a file, replacing any file already at that key."""
        path = self.directory / key
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(payload)

    def read(self, key: str) -> str:
        """Read a file back as text."""
        with open(self.directory / key, "r", encoding="utf-8", newline="") as handle:
            return handle.read()

    def keys(self) -> list[str]:
        """List every file currently stored, sorted."""
        return sorted(
            str(path.relative_to(self.directory)).replace(os.sep, "/")
            for path in self.directory.rglob("*")
            if path.is_file()
        )


class S3Archive(Archive):  # pragma: no cover - needs credentials nobody here has
    """Files in S3, for whoever has access.

    ``boto3`` is imported at construction rather than at module import, so this
    module stays importable - and the whole local path stays runnable - on a
    machine without it. ``CONTRIBUTING.md``: "You will not get AWS Lambda/S3
    access... Structure your code so AWS calls can be easily mocked."
    """

    def __init__(self, bucket: str, prefix: str = "") -> None:
        try:
            import boto3
        except ImportError as error:
            raise RuntimeError(
                "boto3 is needed for an S3 archive; it is intentionally not in "
                "requirements.txt because the default local archive does not "
                "use it. Install it in your own environment."
            ) from error
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.client = boto3.client("s3")

    def _full_key(self, key: str) -> str:
        """Join the configured prefix onto a key."""
        return f"{self.prefix}/{key}" if self.prefix else key

    def write(self, key: str, payload: str) -> None:
        """Store a file, replacing any file already at that key."""
        self.client.put_object(
            Bucket=self.bucket, Key=self._full_key(key), Body=payload.encode("utf-8")
        )

    def read(self, key: str) -> str:
        """Read a file back as text."""
        response = self.client.get_object(Bucket=self.bucket, Key=self._full_key(key))
        return response["Body"].read().decode("utf-8")

    def keys(self) -> list[str]:
        """List every file currently stored, sorted."""
        paginator = self.client.get_paginator("list_objects_v2")
        found: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                if self.prefix:
                    key = key[len(self.prefix) + 1 :]
                found.append(key)
        return sorted(found)


# --------------------------------------------------------------------- extract


@dataclass
class ExtractResult:
    """One run of the extract over one window."""

    columns: list[str]
    rows: list[tuple]
    #: The upper bound of the window, which is what the watermark advances to -
    #: deliberately not ``max(last_updated_at)`` of the rows returned. Taking
    #: the max loses every row that shares the boundary microsecond, or
    #: re-reads it, depending on which comparison the next run uses.
    watermark: datetime
    csv_text: str = ""
    key: str = ""
    notes: list[str] = field(default_factory=list)


def rows_to_csv(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    """Serialise rows to CSV deterministically.

    ``lineterminator="\\n"`` is explicit because ``csv.writer`` defaults to
    ``\\r\\n``; pinning it keeps a re-run byte-identical across platforms, which
    check 6 compares. Timestamps go through ``format_timestamp`` so a datetime
    and its string form cannot produce two different files.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(columns))
    for row in rows:
        writer.writerow(
            [
                format_timestamp(value)
                if isinstance(value, datetime)
                else ("" if value is None else value)
                for value in row
            ]
        )
    return buffer.getvalue()


def window_key(low: datetime, high: datetime) -> str:
    """Build the archive file name for a window.

    Derived only from the window bounds, never from the wall clock. A key
    containing the run time would make a re-run of the same window write a
    second file instead of replacing the first - which check 6 rejects, and
    which check 2 would then report as a duplicated request.
    """
    return f"requests/{low.strftime('%Y%m%dT%H%M%S%f')}-{high.strftime('%Y%m%dT%H%M%S%f')}.csv"


def reference_extract(source: Source, low: datetime, high: datetime) -> ExtractResult:
    """Run the reference extract over the half-open window ``[low, high)``.

    TEST FIXTURE, not the production extract - see the header of
    ``fixture_extract.sql``. Task 2 (#574) owns the real one; it is not merged
    to any mainline branch, so this exists to give the checks something real to
    run against today.
    """
    sql = source.render(EXTRACT_SQL.read_text(encoding="utf-8"))
    columns, rows = source.query(sql, [format_timestamp(low), format_timestamp(high)])
    return ExtractResult(
        columns=columns,
        rows=rows,
        watermark=high,
        csv_text=rows_to_csv(columns, rows),
        key=window_key(low, high),
        notes=["reference extract (fixture) - Task 2's extract is not merged"],
    )


Extractor = Callable[[Source, datetime, datetime], ExtractResult]


def resolve_extractor(spec: Optional[str]) -> tuple[Extractor, str]:
    """Load the extract under test from a ``module:callable`` string.

    Returns the callable and a label for the report, so a reader can always tell
    which extract produced a result. With no spec the reference fixture is used
    and the label says so - a passing report must never be mistaken for a
    verified production pipeline.
    """
    if not spec:
        return reference_extract, "reference extract (FIXTURE, not production)"
    module_name, _, attribute = spec.partition(":")
    if not module_name or not attribute:
        raise ValueError(f"--extractor must look like 'module:callable', got {spec!r}")
    module = importlib.import_module(module_name)
    try:
        extractor = getattr(module, attribute)
    except AttributeError as error:
        raise ValueError(f"{module_name} has no attribute {attribute!r}") from error
    return extractor, spec
