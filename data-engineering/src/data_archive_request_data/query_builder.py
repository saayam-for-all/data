"""SQL builders for the single enriched requests export.

The same builders drive the Lambda (PostgreSQL, ``%s`` placeholders) and the
local SQLite run used for development and tests (``?`` placeholders), so the
join structure that is tested locally is the join structure that runs against
RDS.
"""

from typing import List, Optional, Sequence, Tuple

try:
    from .reference_mappings import (
        REFERENCE_COLUMNS,
        REQUEST_COLUMNS,
        REQUEST_PRIMARY_KEY,
        WATERMARK_COLUMN,
        ReferenceColumn,
    )
except ImportError:  # The deploy workflow copies these modules to the zip root.
    from reference_mappings import (
        REFERENCE_COLUMNS,
        REQUEST_COLUMNS,
        REQUEST_PRIMARY_KEY,
        WATERMARK_COLUMN,
        ReferenceColumn,
    )

REQUESTS_TABLE = "requests"
REQUESTS_ALIAS = "r"
REFERENCE_ALIAS = "ref"

_PLACEHOLDERS = {"pyformat": "%s", "qmark": "?"}


def placeholder(paramstyle: str = "pyformat") -> str:
    """Return the parameter placeholder for a DB-API paramstyle.

    Args:
        paramstyle: ``pyformat`` for psycopg2 or ``qmark`` for sqlite3.

    Returns:
        The placeholder string to interpolate into the SQL.

    Raises:
        ValueError: If the paramstyle is not supported.
    """
    try:
        return _PLACEHOLDERS[paramstyle]
    except KeyError:
        raise ValueError(f"Unsupported paramstyle: {paramstyle}") from None


def qualified_table(table: str, schema: Optional[str] = None) -> str:
    """Return the table name prefixed with the schema when one is configured."""
    if schema:
        return f"{schema}.{table}"
    return table


def export_columns() -> List[Tuple[str, str]]:
    """Return the export projection as ``(sql_expression, output_column)`` pairs.

    Request columns keep their source order and their ids. The readable value
    from the referenced table is added immediately after each id, so
    ``req_status`` sits next to ``req_status_id``: the team's decision on #574
    is to keep both, because the id is the join key for reconciling the archive
    against the source, and keeping it leaves an unmatched reference auditable
    in the archived file itself.

    Returns:
        The projection in export order.
    """
    by_source = {reference.source_column: reference for reference in REFERENCE_COLUMNS}
    projection: List[Tuple[str, str]] = []

    for column in REQUEST_COLUMNS:
        projection.append((f"{REQUESTS_ALIAS}.{column}", column))

        reference = by_source.get(column)
        if reference is not None:
            projection.append(
                (
                    f"{reference.alias}.{reference.readable_column}",
                    reference.output_column,
                )
            )

    return projection


def export_column_names() -> List[str]:
    """Return the export column names in order."""
    return [name for _, name in export_columns()]


def _left_join(reference: ReferenceColumn, schema: Optional[str] = None) -> str:
    """Return the LEFT JOIN clause resolving one reference column."""
    return (
        f"LEFT JOIN {qualified_table(reference.referenced_table, schema)} "
        f"{reference.alias} "
        f"ON {reference.alias}.{reference.referenced_column} "
        f"= {REQUESTS_ALIAS}.{reference.source_column}"
    )


def _watermark_clause(paramstyle: str) -> str:
    """Return the incremental window predicate on the watermark column."""
    mark = placeholder(paramstyle)
    return (
        f"WHERE {REQUESTS_ALIAS}.{WATERMARK_COLUMN} > {mark}\n"
        f"  AND {REQUESTS_ALIAS}.{WATERMARK_COLUMN} <= {mark}"
    )


def build_export_query(
    schema: Optional[str] = None,
    paramstyle: str = "pyformat",
    references: Sequence[ReferenceColumn] = REFERENCE_COLUMNS,
) -> str:
    """Build the single enriched requests export query.

    Every referenced table is joined with a LEFT JOIN on its primary key, so
    requests with null or unmatched references stay in the result and no join
    can multiply a request row.

    Args:
        schema: Schema qualifying the tables, or ``None`` for the search path.
        paramstyle: ``pyformat`` for psycopg2 or ``qmark`` for sqlite3.
        references: Reference columns to resolve; defaults to all six lookups.

    Returns:
        The SELECT statement, taking the watermark window as two parameters
        (exclusive start, inclusive end).
    """
    projection = ",\n".join(
        f"       {expression} AS {name}"
        for expression, name in export_columns()
    )
    joins = "\n".join(_left_join(reference, schema) for reference in references)

    return (
        "SELECT\n"
        f"{projection}\n"
        f"FROM {qualified_table(REQUESTS_TABLE, schema)} {REQUESTS_ALIAS}\n"
        f"{joins}\n"
        f"{_watermark_clause(paramstyle)}\n"
        f"ORDER BY {REQUESTS_ALIAS}.{WATERMARK_COLUMN},"
        f" {REQUESTS_ALIAS}.{REQUEST_PRIMARY_KEY}"
    )


def build_source_count_query(
    schema: Optional[str] = None,
    paramstyle: str = "pyformat",
) -> str:
    """Build the count of source requests selected for archival in the window."""
    return (
        f"SELECT count(*) AS source_row_count,\n"
        f"       count(DISTINCT {REQUESTS_ALIAS}.{REQUEST_PRIMARY_KEY})"
        f" AS source_request_count\n"
        f"FROM {qualified_table(REQUESTS_TABLE, schema)} {REQUESTS_ALIAS}\n"
        f"{_watermark_clause(paramstyle)}"
    )


def build_table_probe_query(schema: Optional[str] = None) -> str:
    """Build a zero-row SELECT used to read the live columns of requests."""
    return f"SELECT * FROM {qualified_table(REQUESTS_TABLE, schema)} WHERE 1 = 0"


def build_reference_audit_query(
    reference: ReferenceColumn,
    schema: Optional[str] = None,
    paramstyle: str = "pyformat",
) -> str:
    """Build the null and unmatched counts for one reference column.

    A row counts as unmatched when the request carries a non-null reference id
    that no row in the referenced table matches.
    """
    return (
        "SELECT\n"
        f"       COALESCE(SUM(CASE WHEN {REQUESTS_ALIAS}.{reference.source_column}"
        " IS NULL THEN 1 ELSE 0 END), 0) AS null_count,\n"
        f"       COALESCE(SUM(CASE WHEN {REQUESTS_ALIAS}.{reference.source_column}"
        f" IS NOT NULL AND {REFERENCE_ALIAS}.{reference.referenced_column}"
        " IS NULL THEN 1 ELSE 0 END), 0) AS unmatched_count\n"
        f"FROM {qualified_table(REQUESTS_TABLE, schema)} {REQUESTS_ALIAS}\n"
        f"LEFT JOIN {qualified_table(reference.referenced_table, schema)}"
        f" {REFERENCE_ALIAS}\n"
        f"  ON {REFERENCE_ALIAS}.{reference.referenced_column}"
        f" = {REQUESTS_ALIAS}.{reference.source_column}\n"
        f"{_watermark_clause(paramstyle)}"
    )
