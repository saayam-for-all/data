"""Database access for Data Engineering code.

Per CONTRIBUTING.md, database connections and queries live here rather than
being scattered across files, so the backend can later be swapped (e.g. for a
vector store) by changing only this module.
"""
import os
import re
from typing import Any, Callable, Optional

DB_SCHEMA_ENV = "SCREENING_DB_SCHEMA"
DEFAULT_SCHEMA = "virginia_dev_saayam_rdbms"
FLAGGED_HELP_REQUESTS_TABLE = "flagged_help_requests"

# Schema names can't be bound as query parameters, so they are validated.
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def get_postgres_connection() -> Any:
    """Open a PostgreSQL connection from the DB_* environment variables."""
    # Imported here so code using a mocked connection doesn't need the driver.
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode=os.getenv("DB_SSLMODE", "prefer"),
    )


class DatabaseClient:
    """Abstraction layer for database operations.

    `connection_factory` returns a DB-API connection; tests pass a fake one.
    """

    def __init__(
            self,
            connection_factory: Callable[[], Any] = get_postgres_connection,
            schema: Optional[str] = None) -> None:
        """Create a client for `schema` (default: SCREENING_DB_SCHEMA)."""
        schema = schema or os.getenv(DB_SCHEMA_ENV, DEFAULT_SCHEMA)
        if not _IDENTIFIER_PATTERN.match(schema):
            raise ValueError(f"Invalid database schema name: {schema!r}")
        self.schema = schema
        self._connection_factory = connection_factory

    def record_flagged_request(self, req_id: str,
                               severity_score: Optional[int],
                               severity_label: str, route: str) -> None:
        """Save a help request held back from active matching.

        Re-screening the same request updates its row, so retries are safe.
        `severity_score` is None when the Profanity API was unavailable.
        """
        query = f"""
            INSERT INTO {self.schema}.{FLAGGED_HELP_REQUESTS_TABLE}
                (req_id, severity_score, severity_label, route)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (req_id) DO UPDATE SET
                severity_score = EXCLUDED.severity_score,
                severity_label = EXCLUDED.severity_label,
                route = EXCLUDED.route,
                flagged_at = now()
        """
        conn = self._connection_factory()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    query, (req_id, severity_score, severity_label, route))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
