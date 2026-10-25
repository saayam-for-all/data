"""Load the mock CSV fixtures into a throwaway database for local testing.

Issue #228 requires that ``organization_analytics`` be developed and tested
against the mock fixtures in ``data-analytics/sql`` -- never against the
shared Saayam database. This module builds a disposable database from
``organizations.csv`` and ``state.csv`` and hands back a connection that the
Lambda's own query code can use unmodified.

Two backends are supported:

``sqlite`` (default)
    An in-memory SQLite database wrapped in a thin PostgreSQL compatibility
    shim. Requires no server and no third-party packages, so the suite runs
    anywhere Python does. The shim covers exactly what the Lambda's SQL uses:

    * ``%s`` placeholders are rewritten to ``?``
    * ``CURRENT_DATE - INTERVAL 'N unit'`` is rewritten to ``date('now', ...)``
    * ``::numeric`` casts are dropped (SQLite ``ROUND`` already takes a scale)
    * ``DATE_TRUNC`` and ``TO_CHAR`` are registered as Python functions
    * rows are returned as dicts, mimicking ``psycopg2``'s ``RealDictCursor``
    * ``is_collaborator``/``is_contributor`` are returned as real booleans
      rather than SQLite's 0/1, so payloads match PostgreSQL

    ``COUNT(*) FILTER (WHERE ...)``, ``IS TRUE``/``IS FALSE``, ``NULLS LAST``
    and schema-qualified names (via ``ATTACH``) are supported by SQLite
    directly and are passed through untouched.

``postgres``
    A real local PostgreSQL database, matching the "test locally using a local
    PostgreSQL connection" note on the issue. Selected by setting
    ``MOCK_DB_BACKEND=postgres``; the connection comes from the ``DB_*``
    environment variables and the same CSVs are loaded into a real
    ``virginia_dev_saayam_rdbms`` schema. As a safety measure this backend
    refuses to run against any host that is not loopback, so the fixtures can
    never be written into a shared database.

Both backends load identical data, and the test suite asserts the same
expectations against whichever one is active.
"""

from __future__ import annotations

import csv
import os
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional


SCHEMA_NAME = "virginia_dev_saayam_rdbms"

# data-analytics/tests/mock_db.py -> data-analytics/sql
MOCK_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"
ORGANIZATIONS_CSV = MOCK_SQL_DIR / "organizations.csv"
STATE_CSV = MOCK_SQL_DIR / "state.csv"

# Column-name driven typing. The fixtures are small and their column names are
# stable, so this is simpler and more predictable than inferring from values.
BOOLEAN_COLUMNS = frozenset({"is_collaborator", "is_contributor"})
INTEGER_COLUMNS = frozenset({"org_rating", "country_id"})
TIMESTAMP_COLUMNS = frozenset({"created_at", "last_updated_at", "last_update_date"})

TABLES: dict[str, Path] = {
    "organizations": ORGANIZATIONS_CSV,
    "state": STATE_CSV,
}

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


# --------------------------------------------------------------------------- #
# CSV reading
# --------------------------------------------------------------------------- #
def _coerce_csv_value(column: str, raw: Optional[str]) -> Any:
    """Convert one raw CSV cell into a typed Python value.

    Args:
        column: Column name, used to pick the target type.
        raw: The raw cell text (``None`` or ``""`` mean SQL ``NULL``).

    Returns:
        ``None``, ``bool``, ``int`` or ``str`` depending on the column.
    """
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        return None
    if column in BOOLEAN_COLUMNS:
        return text.upper() == "TRUE"
    if column in INTEGER_COLUMNS:
        return int(text)
    return text


def read_fixture(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Read a mock CSV into typed row dicts.

    Args:
        path: Path to the CSV fixture.

    Returns:
        A ``(columns, rows)`` tuple.

    Raises:
        FileNotFoundError: If the fixture is missing.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Mock fixture not found: {path}. Expected the CSVs committed under "
            f"{MOCK_SQL_DIR}."
        )
    # utf-8-sig transparently strips a BOM if the CSV was saved from Excel.
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = [
            {col: _coerce_csv_value(col, row.get(col)) for col in columns}
            for row in reader
        ]
    return columns, rows


def load_organizations() -> list[dict[str, Any]]:
    """Return the typed rows of ``organizations.csv`` (the test oracle)."""
    return read_fixture(ORGANIZATIONS_CSV)[1]


def load_states() -> list[dict[str, Any]]:
    """Return the typed rows of ``state.csv`` (the test oracle)."""
    return read_fixture(STATE_CSV)[1]


# --------------------------------------------------------------------------- #
# PostgreSQL -> SQLite translation
# --------------------------------------------------------------------------- #
_INTERVAL_RE = re.compile(
    r"CURRENT_DATE\s*-\s*INTERVAL\s*'(\d+)\s+([a-z]+)'",
    re.IGNORECASE,
)

_TO_CHAR_FORMATS = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "YYYY-MM": "%Y-%m",
    "YYYY": "%Y",
}


def translate_sql(sql: str) -> str:
    """Rewrite the Lambda's PostgreSQL text into equivalent SQLite text.

    Args:
        sql: The original PostgreSQL statement.

    Returns:
        A statement SQLite can execute with identical semantics for the
        constructs this codebase uses.
    """
    # CURRENT_DATE - INTERVAL '7 days'  ->  date('now','-7 days')
    sql = _INTERVAL_RE.sub(
        lambda m: f"date('now','-{m.group(1)} {m.group(2)}')",
        sql,
    )
    # ROUND(AVG(x)::numeric, 2) -> ROUND(AVG(x), 2); SQLite ROUND takes a scale.
    sql = sql.replace("::numeric", "")
    # psycopg2 placeholders -> SQLite placeholders.
    sql = sql.replace("%s", "?")
    return sql


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse a fixture timestamp string, tolerating a missing time part."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _sql_date_trunc(unit: Any, value: Any) -> Optional[str]:
    """SQLite implementation of PostgreSQL ``DATE_TRUNC(unit, timestamp)``.

    Args:
        unit: ``day``, ``week``, ``month`` or ``year``.
        value: Timestamp text from the database.

    Returns:
        The truncated timestamp as ``YYYY-MM-DD HH:MM:SS``, or ``None``.

    Raises:
        ValueError: If ``unit`` is not one of the supported values.
    """
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    key = str(unit).strip().lower()
    if key == "day":
        parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
    elif key == "week":
        # PostgreSQL truncates weeks to Monday; weekday() is 0 on Monday.
        parsed = (parsed - timedelta(days=parsed.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif key == "month":
        parsed = parsed.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif key == "year":
        parsed = parsed.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    else:
        raise ValueError(f"unsupported DATE_TRUNC unit: {unit!r}")
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _sql_to_char(value: Any, fmt: Any) -> Optional[str]:
    """SQLite implementation of PostgreSQL ``TO_CHAR(timestamp, format)``.

    Only the formats whitelisted in ``organization_analytics.GROUP_BY_MAP`` are
    supported; anything else is a programming error and raises.

    Raises:
        ValueError: If ``fmt`` is not a whitelisted format string.
    """
    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    key = str(fmt).strip()
    if key not in _TO_CHAR_FORMATS:
        raise ValueError(f"unsupported TO_CHAR format: {fmt!r}")
    return parsed.strftime(_TO_CHAR_FORMATS[key])


# --------------------------------------------------------------------------- #
# psycopg2-shaped wrappers around sqlite3
# --------------------------------------------------------------------------- #
class MockCursor:
    """A cursor that accepts the Lambda's PostgreSQL SQL and returns dicts.

    Mirrors the slice of ``psycopg2.extras.RealDictCursor`` the Lambda uses:
    ``execute``, ``fetchone``, ``fetchall`` and ``close``. Executed statements
    are recorded on the owning connection so tests can assert which columns
    were referenced (used to prove the contributor guard never touches
    ``is_contributor``).
    """

    def __init__(self, connection: "MockConnection") -> None:
        self._connection = connection
        self._cursor = connection.raw.cursor()

    def execute(self, sql: str, params: Optional[Iterable[Any]] = None) -> None:
        """Translate and run a statement, recording the original SQL."""
        self._connection.executed_sql.append(sql)
        self._cursor.execute(translate_sql(sql), list(params or []))

    def _to_dict(self, row: Optional[tuple]) -> Optional[dict[str, Any]]:
        """Convert a positional row into a dict with PostgreSQL-like types."""
        if row is None:
            return None
        columns = [desc[0] for desc in self._cursor.description]
        result: dict[str, Any] = {}
        for column, value in zip(columns, row):
            # SQLite has no boolean type; restore it so the JSON payload
            # matches what psycopg2 would produce (true/false, not 1/0).
            if column in BOOLEAN_COLUMNS and isinstance(value, int):
                value = bool(value)
            result[column] = value
        return result

    def fetchone(self) -> Optional[dict[str, Any]]:
        return self._to_dict(self._cursor.fetchone())

    def fetchall(self) -> list[dict[str, Any]]:
        return [
            row for row in (self._to_dict(r) for r in self._cursor.fetchall())
            if row is not None
        ]

    def close(self) -> None:
        self._cursor.close()


class MockConnection:
    """A minimal stand-in for a ``psycopg2`` connection backed by SQLite."""

    def __init__(self, raw: sqlite3.Connection) -> None:
        self.raw = raw
        self.executed_sql: list[str] = []

    def cursor(self, cursor_factory: Any = None) -> MockCursor:
        """Return a dict cursor. ``cursor_factory`` is accepted and ignored."""
        return MockCursor(self)

    def close(self) -> None:
        self.raw.close()


# --------------------------------------------------------------------------- #
# Backend construction
# --------------------------------------------------------------------------- #
def _sqlite_column_type(column: str) -> str:
    """Map a fixture column name to a SQLite column type."""
    if column in INTEGER_COLUMNS:
        return "INTEGER"
    if column in BOOLEAN_COLUMNS:
        return "INTEGER"
    return "TEXT"


def _build_sqlite() -> MockConnection:
    """Create an in-memory SQLite database seeded from the mock CSVs."""
    raw = sqlite3.connect(":memory:")
    # A schema-qualified name resolves against an attached database, which
    # lets ``virginia_dev_saayam_rdbms.organizations`` work verbatim.
    raw.execute(f"ATTACH ':memory:' AS {SCHEMA_NAME}")
    raw.create_function("date_trunc", 2, _sql_date_trunc)
    raw.create_function("to_char", 2, _sql_to_char)

    for table, path in TABLES.items():
        columns, rows = read_fixture(path)
        column_ddl = ", ".join(
            f'"{col}" {_sqlite_column_type(col)}' for col in columns
        )
        raw.execute(f"CREATE TABLE {SCHEMA_NAME}.{table} ({column_ddl})")
        placeholders = ", ".join("?" for _ in columns)
        raw.executemany(
            f"INSERT INTO {SCHEMA_NAME}.{table} VALUES ({placeholders})",
            [[row[col] for col in columns] for row in rows],
        )
    raw.commit()
    return MockConnection(raw)


def _postgres_column_type(column: str) -> str:
    """Map a fixture column name to a PostgreSQL column type."""
    if column in INTEGER_COLUMNS:
        return "INTEGER"
    if column in BOOLEAN_COLUMNS:
        return "BOOLEAN"
    if column in TIMESTAMP_COLUMNS:
        return "TIMESTAMP"
    return "TEXT"


def _build_postgres() -> Any:
    """Create the schema in a local PostgreSQL and seed it from the CSVs.

    Returns:
        An open ``psycopg2`` connection.

    Raises:
        RuntimeError: If ``DB_HOST`` is unset or is not a loopback address.
    """
    import psycopg2  # imported lazily so the SQLite backend needs no driver

    host = os.environ.get("DB_HOST", "").strip()
    if not host:
        raise RuntimeError(
            "MOCK_DB_BACKEND=postgres requires DB_HOST (plus DB_NAME/DB_USER/"
            "DB_PASSWORD/DB_PORT) to point at a local database."
        )
    if host.lower() not in LOOPBACK_HOSTS:
        raise RuntimeError(
            f"Refusing to load mock fixtures into non-local host {host!r}. "
            "The mock data must only ever be written to a local database."
        )

    connection = psycopg2.connect(
        host=host,
        database=os.environ.get("DB_NAME", "saayam_local"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
        port=os.environ.get("DB_PORT", "5432"),
    )
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}")
        for table, path in TABLES.items():
            columns, rows = read_fixture(path)
            column_ddl = ", ".join(
                f'"{col}" {_postgres_column_type(col)}' for col in columns
            )
            cursor.execute(f"DROP TABLE IF EXISTS {SCHEMA_NAME}.{table}")
            cursor.execute(f"CREATE TABLE {SCHEMA_NAME}.{table} ({column_ddl})")
            placeholders = ", ".join("%s" for _ in columns)
            cursor.executemany(
                f"INSERT INTO {SCHEMA_NAME}.{table} VALUES ({placeholders})",
                [[row[col] for col in columns] for row in rows],
            )
    connection.commit()
    return connection


def active_backend() -> str:
    """Return the configured backend name (``sqlite`` or ``postgres``)."""
    return os.environ.get("MOCK_DB_BACKEND", "sqlite").strip().lower()


def load_mock_database() -> Any:
    """Build a fresh database seeded from the mock CSVs.

    Returns:
        A connection exposing ``cursor(cursor_factory=...)`` and ``close()``.

    Raises:
        ValueError: If ``MOCK_DB_BACKEND`` is not a recognized backend.
    """
    backend = active_backend()
    if backend == "sqlite":
        return _build_sqlite()
    if backend == "postgres":
        return _build_postgres()
    raise ValueError(
        f"Unknown MOCK_DB_BACKEND {backend!r}; expected 'sqlite' or 'postgres'."
    )
