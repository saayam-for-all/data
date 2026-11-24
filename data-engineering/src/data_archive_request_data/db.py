"""Database access for the enriched requests archive.

psycopg2 is imported lazily so the module can be imported, and the SQL builders
tested, on a machine with no database driver and no RDS access. Cursors are used
without a context manager because sqlite3 cursors are not context managers, and
the local development run drives the same code against SQLite.
"""

import os
import uuid
from typing import Any, Iterator, List, Optional, Sequence, Tuple

DEFAULT_ITERSIZE = 2000


def connect(database_url: Optional[str] = None) -> Any:
    """Open a read-only-by-use connection to the Saayam database.

    Args:
        database_url: libpq connection string; falls back to the DATABASE_URL
            environment variable set from .env.

    Returns:
        A DB-API connection.

    Raises:
        ValueError: If no connection string is configured.
    """
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL is not set")

    import psycopg2  # Imported lazily: not needed to build or test the SQL.

    return psycopg2.connect(url)


def fetch_one(connection: Any, query: str, params: Sequence[Any]) -> Sequence[Any]:
    """Run a query expected to return a single row and return that row."""
    cursor = connection.cursor()
    try:
        cursor.execute(query, params)
        row = cursor.fetchone()
    finally:
        cursor.close()

    return row


def _streaming_cursor(connection: Any, itersize: int) -> Any:
    """Return a cursor that fetches in batches rather than all at once.

    psycopg2 streams only through a named (server-side) cursor, which keeps the
    rows on the server instead of materialising the whole result in the
    Lambda. Drivers without named cursors, sqlite3 among them, fall back to a
    plain cursor driven by fetchmany.
    """
    try:
        cursor = connection.cursor(name=f"data_archive_{uuid.uuid4().hex}")
    except TypeError:
        return connection.cursor()

    cursor.itersize = itersize
    return cursor


def stream_rows(
    connection: Any,
    query: str,
    params: Sequence[Any],
    itersize: int = DEFAULT_ITERSIZE,
) -> Iterator[Sequence[Any]]:
    """Yield query rows in batches, holding at most one batch in memory.

    Args:
        connection: DB-API connection.
        query: SELECT statement.
        params: Query parameters.
        itersize: Rows fetched per round trip.

    Yields:
        One row at a time.
    """
    cursor = _streaming_cursor(connection, itersize)
    try:
        cursor.execute(query, params)
        while True:
            batch = cursor.fetchmany(itersize)
            if not batch:
                break
            for row in batch:
                yield row
    finally:
        cursor.close()


def table_columns(connection: Any, probe_query: str) -> List[str]:
    """Return the live column names of a table.

    Uses a zero-row SELECT rather than information_schema so the same call
    works against PostgreSQL and the SQLite database used locally.

    Args:
        connection: DB-API connection.
        probe_query: A SELECT that returns no rows, from
            query_builder.build_table_probe_query.

    Returns:
        The column names the database reports, in table order.
    """
    cursor = connection.cursor()
    try:
        cursor.execute(probe_query)
        columns = [description[0] for description in cursor.description]
        cursor.fetchall()
    finally:
        cursor.close()

    return columns


def check_column_coverage(
    live_columns: Sequence[str],
    exported_columns: Sequence[str],
) -> Tuple[List[str], List[str]]:
    """Compare the live table against the columns the export knows about.

    Args:
        live_columns: Column names reported by the database.
        exported_columns: Column names the export selects.

    Returns:
        A tuple of (columns missing from the database, columns the database has
        that the export would drop). Both empty means the export covers the
        table exactly.
    """
    live = list(live_columns)
    expected = list(exported_columns)

    missing = [column for column in expected if column not in live]
    unexported = [column for column in live if column not in expected]

    return missing, unexported
