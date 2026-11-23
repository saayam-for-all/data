"""Builds the local copy of the schema that #586 asks for.

    "Check 5 needs a row with a broken reference, and the dev data may not have
     one. You cannot insert into the source database, it is read only. So build
     a local copy of the schema, put a request in it whose category points at
     nothing, and run the extract against that."

Lookup values are loaded from ``database/lookup_tables/*.csv``, which are
already committed and whose values match the DDL comments in #573's
``saayam_schema.sql`` exactly. Nothing here invents lookup data - generating
mock data for this pipeline is Task 7 (#587), a separate open issue, and this
fixture is deliberately the ~25 rows the seven checks need rather than a
dataset.

Every check builds its own fresh fixture. Two of them need different histories
of the same rows - check 3 needs a window pair with nothing changing in
between, check 2 needs a row updated between the two runs - so sharing one
fixture would make the checks order-dependent. In-memory SQLite makes a rebuild
cost roughly nothing.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .adapters import SCHEMA_SQL, SqliteSource, format_timestamp

#: ``<repo>/database/lookup_tables`` - real, committed lookup values.
LOOKUP_DIR = Path(__file__).resolve().parents[2].parent / "database" / "lookup_tables"

#: CSV file -> (table, column renames). Two drifts are handled here rather than
#: papered over: the files are singular where the schema is plural
#: (``request_type.csv`` -> ``request_types``), and they spell the timestamp
#: ``last_updated_date`` where the schema says ``last_updated_at``.
LOOKUP_FILES: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("help_categories.csv", "help_categories", {}),
    ("help_categories_map.csv", "help_categories_map", {}),
    ("request_for.csv", "request_for", {"last_updated_date": "last_updated_at"}),
    ("request_isleadvol.csv", "request_isleadvol", {"last_updated_date": "last_updated_at"}),
    ("request_type.csv", "request_types", {"last_updated_date": "last_updated_at"}),
    ("request_priority.csv", "request_priorities", {"last_updated_date": "last_updated_at"}),
    ("request_status.csv", "request_statuses", {"last_updated_date": "last_updated_at"}),
)

#: #573's DDL comment lists nine statuses, 0 through 8, but
#: ``request_status.csv`` stops at 7. Added so the lookup set check 4 validates
#: against is the complete one.
MISSING_STATUS = (8, "VOLUNTEER_NOT_FOUND", "No volunteer could be found for the request")

#: The window boundaries every check shares. Fixed rather than relative to
#: today, so a report records the same numbers whenever it is re-run.
T0 = datetime(2026, 10, 1, 0, 0, 0, 0)
T1 = datetime(2026, 10, 8, 0, 0, 0, 0)
T2 = datetime(2026, 10, 15, 0, 0, 0, 0)

#: A category id that is absent from all 80 rows of ``help_categories.csv``.
DANGLING_CATEGORY = "CAT-DOES-NOT-EXIST"

USERS = tuple(f"SID-00-000-000-000-000-{index:03d}" for index in range(1, 9))


@dataclass
class FixtureFacts:
    """What the fixture deliberately contains, for expected-versus-actual.

    Checks still count rows by querying the source - #586 requires counts to be
    "compared against the source for the same window, not just reported from
    the file". These are the fixture's declared intent, used to assert that the
    rows a check depends on are the rows it thinks they are.
    """

    low: datetime = T0
    middle: datetime = T1
    high: datetime = T2
    null_lead_volunteer: list[str] = field(default_factory=list)
    null_beneficiary: list[str] = field(default_factory=list)
    dangling_category: list[str] = field(default_factory=list)
    boundary_tie: list[str] = field(default_factory=list)
    awkward_text: list[str] = field(default_factory=list)
    updated_after_submission: list[str] = field(default_factory=list)


def _clean(value: Optional[str]) -> Optional[str]:
    """Turn the CSVs' literal 'NULL' text and empty strings into None."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped == "" or stripped.upper() == "NULL":
        return None
    return stripped


def _load_lookup_tables(source: SqliteSource) -> None:
    """Insert every committed lookup value into the local copy."""
    for filename, table, renames in LOOKUP_FILES:
        path = LOOKUP_DIR / filename
        # utf-8-sig: these files are exported with a BOM, which would otherwise
        # end up inside the first column's name and break the INSERT.
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            continue
        columns = [renames.get(name, name) for name in rows[0]]
        placeholders = ", ".join("?" for _ in columns)
        statement = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
        )
        source.connection.executemany(
            statement, [tuple(_clean(value) for value in row.values()) for row in rows]
        )

    source.connection.execute(
        "INSERT INTO request_statuses (req_status_id, req_status, req_status_desc) "
        "VALUES (?, ?, ?)",
        MISSING_STATUS,
    )
    source.connection.executemany(
        "INSERT INTO users (user_id) VALUES (?)", [(user,) for user in USERS]
    )
    source.connection.commit()


def _insert_request(
    source: SqliteSource,
    req_id: str,
    last_updated_at: datetime,
    *,
    creator_id: str = USERS[0],
    beneficiary_id: Optional[str] = USERS[1],
    lead_volunteer_id: Optional[str] = USERS[2],
    req_cat_id: str = "1.1",
    req_for_id: int = 0,
    req_islead_id: int = 0,
    req_type_id: int = 1,
    req_priority_id: int = 2,
    req_status_id: int = 3,
    req_subj: str = "Help with groceries",
    req_desc: str = "Needs a weekly grocery run.",
    submission_date: Optional[datetime] = None,
) -> None:
    """Insert one request row into the local copy."""
    values: tuple[Any, ...] = (
        req_id,
        creator_id,
        beneficiary_id,
        lead_volunteer_id,
        req_cat_id,
        req_for_id,
        req_islead_id,
        req_type_id,
        req_priority_id,
        req_status_id,
        req_subj,
        req_desc,
        None,
        None,
        None,
        "Suffolk, VA",
        None,
        0,
        1,
        format_timestamp(submission_date or (last_updated_at - timedelta(days=2))),
        None,
        format_timestamp(last_updated_at),
    )
    source.connection.execute(
        """
        INSERT INTO requests (
            req_id, creator_id, beneficiary_id, lead_volunteer_id,
            req_cat_id, req_for_id, req_islead_id, req_type_id,
            req_priority_id, req_status_id,
            req_subj, req_desc, req_doc_link, audio_req_desc, deletion_reason,
            req_loc, created_loc, iscalamity, to_public,
            submission_date, serviced_date, last_updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )


def build() -> tuple[SqliteSource, FixtureFacts]:
    """Create a freshly seeded local copy of the schema.

    Returns the source and a description of what was deliberately put in it.
    """
    source = SqliteSource(":memory:")
    source.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    _load_lookup_tables(source)
    facts = FixtureFacts()

    # ---------------------------------------------------------- window A rows
    _insert_request(source, "REQ-A-001", T0 + timedelta(hours=1))

    # The real shape of a broken reference. In dev, lead_volunteer_id is null in
    # 218 of 221 requests and beneficiary_id in 8 - an inner join on the former
    # returns 3 rows and the count looks small rather than wrong.
    _insert_request(source, "REQ-A-002", T0 + timedelta(hours=2), lead_volunteer_id=None)
    facts.null_lead_volunteer.append("REQ-A-002")
    _insert_request(source, "REQ-A-003", T0 + timedelta(hours=3), beneficiary_id=None)
    facts.null_beneficiary.append("REQ-A-003")
    _insert_request(
        source,
        "REQ-A-004",
        T0 + timedelta(hours=4),
        beneficiary_id=None,
        lead_volunteer_id=None,
    )
    facts.null_lead_volunteer.append("REQ-A-004")
    facts.null_beneficiary.append("REQ-A-004")

    # Free text that breaks a line-counting row count: an embedded newline, a
    # comma and a double quote. requesters "can type anything into these".
    _insert_request(
        source,
        "REQ-A-006",
        T0 + timedelta(hours=6),
        req_subj='Rent help, urgent',
        req_desc='Line one\nline two, with a comma and a "quoted" word.\nLine three',
    )
    facts.awkward_text.append("REQ-A-006")

    # last_updated_at earlier than submission_date. This occurs in the real data
    # and nothing prevents it, so the extract must not assume an ordering.
    _insert_request(
        source,
        "REQ-A-007",
        T0 + timedelta(hours=7),
        submission_date=T0 + timedelta(days=3),
    )
    facts.updated_after_submission.append("REQ-A-007")

    for index in range(8, 13):
        _insert_request(
            source,
            f"REQ-A-{index:03d}",
            T0 + timedelta(hours=index),
            req_cat_id="1.2",
            req_status_id=index % 9,
            req_priority_id=index % 4,
            req_type_id=index % 2,
            req_for_id=index % 2,
            req_islead_id=index % 2,
        )

    # ---------------------------------------------------------- window B rows
    # Three rows sharing one last_updated_at to the microsecond, sitting exactly
    # on the boundary. With a half-open window they belong to B and only B; a
    # closed window puts them in both, an exclusive low bound in neither.
    for index in (1, 2, 3):
        _insert_request(source, f"REQ-B-{index:03d}", T1)
        facts.boundary_tie.append(f"REQ-B-{index:03d}")

    for index in range(4, 9):
        _insert_request(
            source,
            f"REQ-B-{index:03d}",
            T1 + timedelta(hours=index),
            req_cat_id="2.1",
            req_status_id=index % 9,
        )

    # ------------------------------------------------- the dangling reference
    # req_cat_id is NOT NULL and foreign-key constrained, so a faithful copy of
    # the schema rejects the row #586 asks for. Enforcement is disabled for this
    # one insert, which is the local equivalent of dropping the constraint in
    # Postgres and represents the same real risk: a load that runs with
    # constraints off. It is re-enabled immediately.
    source.set_foreign_keys(False)
    _insert_request(
        source,
        "REQ-A-005",
        T0 + timedelta(hours=5),
        req_cat_id=DANGLING_CATEGORY,
    )
    source.set_foreign_keys(True)
    facts.dangling_category.append("REQ-A-005")

    source.connection.commit()
    return source, facts


def move_into_later_window(
    source: SqliteSource, req_id: str, last_updated_at: datetime
) -> None:
    """Move a request's ``last_updated_at``, as an update to it would.

    Epic #416: "last_updated_at moves on update as well as insert, so a status
    change on an already-archived request gets re-archived with its new value."
    Check 2 uses this to confirm a legitimate re-archive is not mistaken for a
    duplicate.
    """
    source.connection.execute(
        "UPDATE requests SET last_updated_at = ?, req_status_id = ? WHERE req_id = ?",
        (format_timestamp(last_updated_at), 4, req_id),
    )
    source.connection.commit()


def count_in_window(source: SqliteSource, low: datetime, high: datetime) -> int:
    """Count source rows in the half-open window ``[low, high)``.

    This is the source-side number check 1 compares the file against, rather
    than trusting a count the file reports about itself.
    """
    _, rows = source.query(
        "SELECT count(*) FROM requests "
        "WHERE last_updated_at >= ? AND last_updated_at < ?",
        [format_timestamp(low), format_timestamp(high)],
    )
    return int(rows[0][0])


def lookup_values(source: SqliteSource, table: str, column: str) -> set[str]:
    """Read the permitted readable values for one lookup, for check 4."""
    _, rows = source.query(f"SELECT {column} FROM {table}")
    return {str(row[0]) for row in rows if row[0] is not None}
