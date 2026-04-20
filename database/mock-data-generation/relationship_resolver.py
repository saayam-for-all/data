"""
relationship_resolver.py
------------------------
Owns all FK knowledge that db_info.json does not declare.

Three responsibilities:
  1. EFFECTIVE_PKS  — authoritative PK column names for tables whose
                      db_info.json entry has primary_key: false on every col
                      (known schema gap).
  2. FK_MAP         — maps every FK column to the parent table and its PK,
                      plus the context key where the parent's generated ID
                      pool is stored at runtime.
  3. topological_order() — returns the generation sequence that respects
                            all FK dependencies.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import NamedTuple


# ---------------------------------------------------------------------------
# 1.  Effective PKs — overrides for tables missing primary_key: true
# ---------------------------------------------------------------------------

EFFECTIVE_PKS: dict[str, list[str]] = {
    # These tables have no primary_key flag set in db_info.json.
    "state":                            ["state_id"],
    "notification_channels":            ["channel_id"],
    "notification_types":               ["type_id"],
    "notifications":                    ["notification_id"],
    "user_notification_preferences":    ["user_notification_preferences_id"],
}


# ---------------------------------------------------------------------------
# 2.  FK map
#
# Each entry describes one FK column:
#   FKColumn(
#       child_table  – table that owns the FK column
#       child_col    – the FK column name
#       parent_table – table being referenced
#       parent_col   – referenced column (usually the PK)
#       context_key  – key in the runtime context dict that holds the pool
#                      of valid parent IDs;  e.g. "user_ids", "request_ids"
#   )
#
# FK relationships are inferred from naming conventions because db_info.json
# carries no FK declarations.
# ---------------------------------------------------------------------------


class FKColumn(NamedTuple):
    """Describes one FK relationship."""

    child_table: str
    child_col: str
    parent_table: str
    parent_col: str
    context_key: str   # key in runtime context that holds the parent ID pool


FK_MAP: list[FKColumn] = [
    # ── geography / location tables ──────────────────────────────────────────
    FKColumn("state",             "country_id",        "country",             "country_id",        "country_ids"),
    FKColumn("city",              "state_id",          "state",               "state_id",          "state_ids"),
    FKColumn("emergency_numbers", "country_id",        "country",             "country_id",        "country_ids"),
    FKColumn("emergency_numbers", "state_id",          "state",               "state_id",          "state_ids"),

    # ── help categories (self-referential map) ────────────────────────────────
    FKColumn("help_categories_map", "parent_id",       "help_categories",     "cat_id",            "cat_ids"),
    FKColumn("help_categories_map", "child_id",        "help_categories",     "cat_id",            "cat_ids"),

    # ── additional metadata tables ────────────────────────────────────────────
    FKColumn("req_add_info_metadata", "cat_id",        "help_categories",     "cat_id",            "cat_ids"),
    FKColumn("list_item_metadata",    "field_id",      "req_add_info_metadata", "field_id",        "field_ids"),

    # ── organizations ─────────────────────────────────────────────────────────
    FKColumn("organizations",     "cat_id",            "help_categories",     "cat_id",            "cat_ids"),

    # ── users ─────────────────────────────────────────────────────────────────
    FKColumn("users",             "country_id",        "country",             "country_id",        "country_ids"),
    FKColumn("users",             "state_id",          "state",               "state_id",          "state_ids"),
    FKColumn("users",             "user_status_id",    "user_status",         "user_status_id",    "user_status_ids"),
    FKColumn("users",             "user_category_id",  "user_category",       "user_category_id",  "user_category_ids"),

    # ── user child tables ─────────────────────────────────────────────────────
    FKColumn("user_additional_details",         "user_id",      "users", "user_id", "user_ids"),
    FKColumn("user_availability",               "user_id",      "users", "user_id", "user_ids"),
    FKColumn("user_locations",                  "user_id",      "users", "user_id", "user_ids"),
    FKColumn("user_notification_preferences",   "user_id",      "users", "user_id", "user_ids"),
    FKColumn("user_notification_preferences",   "channel_id",   "notification_channels", "channel_id", "channel_ids"),
    FKColumn("user_notification_status",        "user_id",      "users", "user_id", "user_ids"),
    FKColumn("user_skills",                     "user_id",      "users", "user_id", "user_ids"),
    FKColumn("user_skills",                     "cat_id",       "help_categories", "cat_id", "cat_ids"),
    FKColumn("user_org_map",                    "user_id",      "users", "user_id", "user_ids"),
    FKColumn("user_org_map",                    "org_id",       "organizations", "org_id", "org_ids"),

    # ── volunteer child tables ────────────────────────────────────────────────
    FKColumn("volunteer_applications", "user_id",  "users", "user_id", "user_ids"),
    FKColumn("volunteer_details",      "user_id",  "users", "user_id", "user_ids"),
    FKColumn("volunteer_locations",    "user_id",  "users", "user_id", "user_ids"),

    # ── fraud / meetings ──────────────────────────────────────────────────────
    FKColumn("fraud_requests",      "user_id",      "users",    "user_id",    "user_ids"),
    FKColumn("meetings",            "cohost_id",    "users",    "user_id",    "user_ids"),
    FKColumn("meeting_participants","meeting_id",   "meetings", "meeting_id", "meeting_ids"),
    FKColumn("meeting_participants","participant_id","users",   "user_id",    "user_ids"),

    # ── notifications ─────────────────────────────────────────────────────────
    FKColumn("notifications", "user_id",    "users",               "user_id",   "user_ids"),
    FKColumn("notifications", "type_id",    "notification_types",  "type_id",   "notification_type_ids"),
    FKColumn("notifications", "channel_id", "notification_channels","channel_id","channel_ids"),

    # ── request and its lookup FKs ────────────────────────────────────────────
    FKColumn("request", "req_user_id",    "users",             "user_id",       "user_ids"),
    FKColumn("request", "req_for_id",     "request_for",       "req_for_id",    "req_for_ids"),
    FKColumn("request", "req_islead_id",  "request_isleadvol", "req_islead_id", "req_islead_ids"),
    FKColumn("request", "req_cat_id",     "help_categories",   "cat_id",        "cat_ids"),
    FKColumn("request", "req_type_id",    "request_type",      "req_type_id",   "req_type_ids"),
    FKColumn("request", "req_priority_id","request_priority",  "req_priority_id","req_priority_ids"),
    FKColumn("request", "req_status_id",  "request_status",    "req_status_id", "req_status_ids"),

    # ── request child tables ──────────────────────────────────────────────────
    FKColumn("request_comments",    "req_id",       "request", "req_id", "request_ids"),
    FKColumn("request_comments",    "commenter_id", "users",   "user_id","user_ids"),
    FKColumn("request_guest_details","req_id",      "request", "req_id", "request_ids"),
    FKColumn("req_add_info",        "request_id",   "request", "req_id", "request_ids"),
    FKColumn("req_add_info",        "cat_id",       "help_categories", "cat_id", "cat_ids"),

    # ── volunteer_rating / volunteers_assigned ────────────────────────────────
    FKColumn("volunteer_rating",    "user_id",      "users",   "user_id",  "user_ids"),
    FKColumn("volunteer_rating",    "request_id",   "request", "req_id",   "request_ids"),
    FKColumn("volunteers_assigned", "request_id",   "request", "req_id",   "request_ids"),
    FKColumn("volunteers_assigned", "volunteer_id", "users",   "user_id",  "user_ids"),
]


# ---------------------------------------------------------------------------
# 3.  Topological sort — generation order
# ---------------------------------------------------------------------------

# Non-FK data dependencies: (source, dependent) means the dependent table's
# generator reads ctx data written by the source table's generator, so source
# must run first even though no database FK exists between them.
PIPELINE_DEPENDENCIES: list[tuple[str, str]] = [
    ("volunteer_applications", "user_skills"),  # user_skills reads ctx["vol_app_skills"]
]

# Tables that need NO generation (loaded verbatim from lookup_tables/).
# Declared here so topological_order() knows they are always "resolved".
LOOKUP_TABLES: frozenset[str] = frozenset([
    "country",
    "state",
    "help_categories",
    "help_categories_map",
    "req_add_info_metadata",
    "list_item_metadata",
    "notification_channels",
    "notification_types",
    "request_for",
    "request_isleadvol",
    "request_priority",
    "request_status",
    "request_type",
    "user_category",
    "user_status",
    "supporting_languages",
])


def _build_dependency_graph(
    all_tables: list[str],
) -> tuple[dict[str, set[str]], dict[str, int]]:
    """Build adjacency and in-degree structures for topological sort.

    Args:
        all_tables: Every table name known to the pipeline.

    Returns:
        A tuple of:
          - ``deps``: mapping table → set of tables it depends on.
          - ``in_degree``: mapping table → number of unresolved dependencies.
    """
    deps: dict[str, set[str]] = defaultdict(set)
    in_degree: dict[str, int] = {t: 0 for t in all_tables}

    for fk in FK_MAP:
        child = fk.child_table
        parent = fk.parent_table

        # Only count edges between tables in the pipeline.
        if child not in in_degree or parent not in in_degree:
            continue
        # Skip if already recorded (duplicate FKs on same parent table).
        if parent in deps[child]:
            continue

        deps[child].add(parent)
        in_degree[child] += 1

    # Non-FK pipeline dependencies: same edge semantics, different source list.
    for source, dependent in PIPELINE_DEPENDENCIES:
        if dependent not in in_degree or source not in in_degree:
            continue
        if source in deps[dependent]:
            continue
        deps[dependent].add(source)
        in_degree[dependent] += 1

    return deps, in_degree


def topological_order(all_tables: list[str]) -> list[str]:
    """Return tables in an order safe for generation (parents before children).

    Lookup-only tables always sort first regardless of position in the FK
    graph. Independent tables (no FKs in either direction) sort after
    lookup tables but before generated tables that depend on them.

    Uses Kahn's algorithm (BFS-based topological sort).

    Args:
        all_tables: Complete list of table names to order.

    Returns:
        Ordered list where every table appears after all its FK parents.

    Raises:
        ValueError: If a circular dependency is detected.
    """
    deps, in_degree = _build_dependency_graph(all_tables)

    # Seed the queue: lookup tables first, then zero-in-degree generated tables.
    queue: deque[str] = deque()

    # Lookup tables have no ordering requirements among themselves.
    for table in all_tables:
        if table in LOOKUP_TABLES:
            queue.appendleft(table)

    for table in all_tables:
        if table not in LOOKUP_TABLES and in_degree[table] == 0:
            queue.append(table)

    result: list[str] = []
    resolved: set[str] = set()

    # Build a reverse map: parent → children that depend on it.
    reverse: dict[str, list[str]] = defaultdict(list)
    for child, parents in deps.items():
        for parent in parents:
            reverse[parent].append(child)

    while queue:
        table = queue.popleft()
        # Guard: lookup tables with in_degree > 0 are seeded into the queue
        # unconditionally, but their parent may later decrement their in_degree
        # to 0 and append them a second time before they are popped.  Skip the
        # duplicate pop so each table appears in result exactly once.
        if table in resolved:
            continue
        result.append(table)
        resolved.add(table)

        for child in sorted(reverse[table]):  # sorted for determinism
            if child in resolved:
                continue
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    if len(result) != len(all_tables):
        unresolved = set(all_tables) - resolved
        raise ValueError(
            f"Circular dependency detected. Unresolved tables: {sorted(unresolved)}"
        )

    return result


# ---------------------------------------------------------------------------
# 4.  FK lookup helpers used by generators.py
# ---------------------------------------------------------------------------


def fk_columns_for_table(table_name: str) -> list[FKColumn]:
    """Return all FK entries where the given table is the child.

    Args:
        table_name: The child table name to look up.

    Returns:
        List of :class:`FKColumn` instances for that table.
    """
    return [fk for fk in FK_MAP if fk.child_table == table_name]


