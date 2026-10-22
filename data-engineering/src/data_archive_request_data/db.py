"""Database access for the enriched requests archive.

psycopg2 is imported lazily so the module can be imported, and the SQL builders
tested, on a machine with no database driver and no RDS access.
"""

import os
from typing import Any, List, Optional, Sequence, Tuple


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


def fetch_all(
    connection: Any,
    query: str,
    params: Sequence[Any],
) -> Tuple[List[str], List[Sequence[Any]]]:
    """Run a query and return its column names and all rows.

    Args:
        connection: DB-API connection.
        query: SELECT statement.
        params: Query parameters.

    Returns:
        A tuple of the column names and the rows.
    """
    cursor = connection.cursor()
    try:
        cursor.execute(query, params)
        columns = [description[0] for description in cursor.description]
        rows = list(cursor.fetchall())
    finally:
        cursor.close()

    return columns, rows


def fetch_one(connection: Any, query: str, params: Sequence[Any]) -> Sequence[Any]:
    """Run a query expected to return a single row and return that row."""
    cursor = connection.cursor()
    try:
        cursor.execute(query, params)
        row = cursor.fetchone()
    finally:
        cursor.close()

    return row
