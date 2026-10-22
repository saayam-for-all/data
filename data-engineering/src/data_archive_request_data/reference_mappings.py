"""Reference columns of the requests table and the tables they join to.

The mapping is the Task 1 (issue #573) output expressed as code: one entry per
column in ``requests`` that refers to another table, with the referenced table,
the column it matches on, and the readable column that replaces the id in the
archive export.

Every lookup is joined with a LEFT JOIN on the referenced table's primary key,
so a request whose reference is null or unmatched keeps its row in the export
and cannot be duplicated by the join.
"""

from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class ReferenceColumn:
    """One reference column of ``requests`` and the lookup that resolves it.

    Attributes:
        source_column: Column in ``requests`` holding the reference id.
        referenced_table: Table the column refers to.
        referenced_column: Primary key column the join matches on.
        readable_column: Column in the referenced table holding the readable value.
        output_column: Name the readable value gets in the export.
        alias: SQL alias used for the referenced table in the join.
    """

    source_column: str
    referenced_table: str
    referenced_column: str
    readable_column: str
    output_column: str
    alias: str


# The six lookup tables that used to be exported alongside requests. Their
# readable values are folded into the single enriched export instead.
REFERENCE_COLUMNS: Tuple[ReferenceColumn, ...] = (
    ReferenceColumn(
        source_column="req_for_id",
        referenced_table="request_for",
        referenced_column="req_for_id",
        readable_column="req_for",
        output_column="req_for",
        alias="rf",
    ),
    ReferenceColumn(
        source_column="req_islead_id",
        referenced_table="request_isleadvol",
        referenced_column="req_islead_id",
        readable_column="req_islead",
        output_column="req_islead",
        alias="rl",
    ),
    ReferenceColumn(
        source_column="req_cat_id",
        referenced_table="help_categories",
        referenced_column="cat_id",
        readable_column="cat_name",
        output_column="req_category",
        alias="hc",
    ),
    ReferenceColumn(
        source_column="req_type_id",
        referenced_table="request_type",
        referenced_column="req_type_id",
        readable_column="req_type",
        output_column="req_type",
        alias="rt",
    ),
    ReferenceColumn(
        source_column="req_priority_id",
        referenced_table="request_priority",
        referenced_column="req_priority_id",
        readable_column="req_priority",
        output_column="req_priority",
        alias="rp",
    ),
    ReferenceColumn(
        source_column="req_status_id",
        referenced_table="request_status",
        referenced_column="req_status_id",
        readable_column="req_status",
        output_column="req_status",
        alias="rs",
    ),
)

# Reference columns that point at ``users``. They are deliberately NOT enriched:
# the ids are already the readable identifiers used across Saayam, and copying
# names, emails or phone numbers into an S3 archive would move personal data
# out of the database. Enriching them is a product decision, not a technical
# one, so it is left out until the team asks for it.
USER_REFERENCE_COLUMNS: Tuple[ReferenceColumn, ...] = (
    ReferenceColumn(
        source_column="creator_id",
        referenced_table="users",
        referenced_column="user_id",
        readable_column="full_name",
        output_column="creator_name",
        alias="uc",
    ),
    ReferenceColumn(
        source_column="beneficiary_id",
        referenced_table="users",
        referenced_column="user_id",
        readable_column="full_name",
        output_column="beneficiary_name",
        alias="ub",
    ),
    ReferenceColumn(
        source_column="lead_volunteer_id",
        referenced_table="users",
        referenced_column="user_id",
        readable_column="full_name",
        output_column="lead_volunteer_name",
        alias="uv",
    ),
)

# Columns of ``requests``, in source order. The export keeps this order and
# replaces each reference id with its readable value in place.
REQUEST_COLUMNS: Tuple[str, ...] = (
    "req_id",
    "creator_id",
    "req_for_id",
    "req_islead_id",
    "req_cat_id",
    "req_type_id",
    "req_priority_id",
    "req_status_id",
    "req_loc",
    "iscalamity",
    "req_subj",
    "req_desc",
    "req_doc_link",
    "audio_req_desc",
    "submission_date",
    "serviced_date",
    "last_updated_at",
    "to_public",
    "beneficiary_id",
    "lead_volunteer_id",
    "deletion_reason",
)

REQUEST_PRIMARY_KEY = "req_id"
WATERMARK_COLUMN = "last_updated_at"


def reference_column_names() -> List[str]:
    """Return the names of the reference columns resolved by the export."""
    return [reference.source_column for reference in REFERENCE_COLUMNS]
