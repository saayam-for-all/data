"""Database access kept separate from export logic and AWS dependencies."""

import os
import sqlite3
from contextlib import contextmanager


def quote_identifier(value: str) -> str:
    """Quote a known table/column name, including names discovered in the DB."""
    return '"' + value.replace('"', '""') + '"'


class DatabaseClient:
    """Own a read-only snapshot for production PostgreSQL or local SQLite."""

    def __init__(self, connection, schema: str, dialect: str = "postgres"):
        """Wrap a connection; local test code must explicitly select SQLite."""
        if dialect not in {"postgres", "sqlite"}:
            raise ValueError("Unsupported database dialect")
        self.connection = connection
        self.schema = schema
        self.dialect = dialect

    @classmethod
    def production(cls, schema: str):
        """Open PostgreSQL only when invoked outside the local demo."""
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise ValueError("DATABASE_URL is required")
        import psycopg2

        connection = psycopg2.connect(dsn, connect_timeout=10,
                                      options="-c statement_timeout=120000")
        return cls(connection, schema)

    @classmethod
    def local(cls, path):
        """Open an existing local fixture; creating data belongs to the demo."""
        connection = sqlite3.connect(path)
        return cls(connection, "main", "sqlite")

    def table(self, name: str) -> str:
        """Return a schema-qualified identifier, never an event-supplied table."""
        return f"{quote_identifier(self.schema)}.{quote_identifier(name)}"

    @contextmanager
    def snapshot(self):
        """Keep counts, reference audits and streamed rows in one snapshot."""
        if self.dialect == "sqlite":
            self.connection.execute("PRAGMA query_only = ON")
            self.connection.execute("BEGIN")
        else:
            self.connection.set_session(isolation_level="REPEATABLE READ", readonly=True,
                                        autocommit=False)
        try:
            yield self
        finally:
            self.connection.rollback()

    @contextmanager
    def cursor(self, stream: bool = False):
        """Use a server-side cursor for the potentially large PostgreSQL export."""
        cursor = (self.connection.cursor(name="task574_requests")
                  if stream and self.dialect == "postgres" else self.connection.cursor())
        try:
            yield cursor
        finally:
            cursor.close()

    def columns(self, table: str) -> list[str]:
        """Discover column order without reading any data rows."""
        with self.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {self.table(table)} WHERE 1 = 0")
            return [column[0] for column in cursor.description]

    def selection(self, settings) -> tuple[str, tuple]:
        """Build a parameterized (start, end] predicate on UTC timestamps."""
        if settings.start is None:
            return "", ()
        marker = "?" if self.dialect == "sqlite" else "%s"
        bounds = (settings.start, settings.end)
        if self.dialect == "sqlite":
            bounds = tuple(bound.isoformat(sep=" ", timespec="microseconds") for bound in bounds)
        return (f"WHERE r.last_updated_at > {marker} AND r.last_updated_at <= {marker}", bounds)

    def close(self):
        """Release the connection even if validation or upload fails."""
        self.connection.close()
