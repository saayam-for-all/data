#!/usr/bin/env python3
"""Generate deterministic synthetic fixtures for the request archive pipeline.

The column names and constraints in this module mirror the schema-only
``saayam_schema.sql`` bundled with the generated fixtures. No database access
or production/dev exports are used.
"""

from __future__ import annotations

import argparse
import random
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Sequence


HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE / "request_archive_mock"
DEFAULT_SCHEMA = HERE / "saayam_schema.sql"
SEED_DEFAULT = 587
REQUEST_COLUMNS = [
    "req_id", "creator_id", "beneficiary_id", "lead_volunteer_id",
    "req_cat_id", "req_for_id", "req_islead_id", "req_type_id",
    "req_priority_id", "req_status_id", "req_subj", "req_desc",
    "req_doc_link", "audio_req_desc", "deletion_reason", "req_loc",
    "created_loc", "iscalamity", "to_public", "submission_date",
    "serviced_date", "last_updated_at",
]
NULL_TOKEN = r"\N"

TABLE_COLUMNS: dict[str, list[str]] = {
    "requests": REQUEST_COLUMNS,
    "help_categories": ["cat_id", "cat_name", "cat_desc", "last_updated_at"],
    "help_categories_map": ["parent_id", "child_id", "last_updated_at"],
    "request_for": ["req_for_id", "req_for", "req_for_desc", "last_updated_at"],
    "request_isleadvol": ["req_islead_id", "req_islead", "req_islead_desc", "last_updated_at"],
    "request_types": ["req_type_id", "req_type", "req_type_desc", "last_updated_at"],
    "request_priorities": ["req_priority_id", "req_priority", "req_priority_desc", "last_updated_at"],
    "request_statuses": ["req_status_id", "req_status", "req_status_desc", "last_updated_at"],
    # Intentionally only the key column: the real users table contains PII.
    "users": ["user_id"],
}

LOOKUP_TIMESTAMP = "2026-01-01 00:00:00.000000"


def quote_cell(value: object) -> str:
    """Serialize a cell as PostgreSQL-compatible CSV, preserving empty text."""
    if value is None:
        return NULL_TOKEN
    text = str(value)
    return '"' + text.replace('"', '""') + '"'


def write_csv(path: Path, columns: Sequence[str], rows: Iterable[dict[str, object]]) -> None:
    """Write UTF-8 CSV with explicit NULL and empty-string representations."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(",".join(quote_cell(column) for column in columns) + "\n")
        for row in rows:
            stream.write(",".join(quote_cell(row.get(column)) for column in columns) + "\n")


def ts(value: datetime) -> str:
    """Format a timestamp with exactly six fractional digits."""
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def lookup_rows() -> dict[str, list[dict[str, object]]]:
    """Return the fixed lookup values documented in issue #573."""
    return {
        "request_for": [
            {"req_for_id": 0, "req_for": "SELF", "req_for_desc": "Request is for the person creating it.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_for_id": 1, "req_for": "OTHER", "req_for_desc": "Request is for another person.", "last_updated_at": LOOKUP_TIMESTAMP},
        ],
        "request_isleadvol": [
            {"req_islead_id": 0, "req_islead": "NO", "req_islead_desc": "No lead volunteer is indicated.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_islead_id": 1, "req_islead": "YES", "req_islead_desc": "A lead volunteer is indicated.", "last_updated_at": LOOKUP_TIMESTAMP},
        ],
        "request_types": [
            {"req_type_id": 0, "req_type": "IN_PERSON", "req_type_desc": "Help is provided in person.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_type_id": 1, "req_type": "REMOTE", "req_type_desc": "Help is provided remotely.", "last_updated_at": LOOKUP_TIMESTAMP},
        ],
        "request_priorities": [
            {"req_priority_id": 0, "req_priority": "LOW", "req_priority_desc": "Low urgency.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_priority_id": 1, "req_priority": "MEDIUM", "req_priority_desc": "Moderate urgency.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_priority_id": 2, "req_priority": "HIGH", "req_priority_desc": "High urgency.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_priority_id": 3, "req_priority": "CRITICAL", "req_priority_desc": "Immediate attention is required.", "last_updated_at": LOOKUP_TIMESTAMP},
        ],
        "request_statuses": [
            {"req_status_id": 0, "req_status": "CREATED", "req_status_desc": "Request has been created.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_status_id": 1, "req_status": "MATCHING_VOLUNTEER", "req_status_desc": "A volunteer is being matched.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_status_id": 2, "req_status": "IN_PROGRESS", "req_status_desc": "Help is in progress.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_status_id": 3, "req_status": "RESOLVED", "req_status_desc": "The request has been resolved.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_status_id": 4, "req_status": "CANCELLED", "req_status_desc": "The request was cancelled.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_status_id": 5, "req_status": "DELETED", "req_status_desc": "The request was deleted.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_status_id": 6, "req_status": "RATED_BY_REQUESTER", "req_status_desc": "The requester submitted a rating.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_status_id": 7, "req_status": "RATED_BY_VOLUNTEER", "req_status_desc": "The volunteer submitted a rating.", "last_updated_at": LOOKUP_TIMESTAMP},
            {"req_status_id": 8, "req_status": "VOLUNTEER_NOT_FOUND", "req_status_desc": "No volunteer was found.", "last_updated_at": LOOKUP_TIMESTAMP},
        ],
    }


def category_rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Build a small synthetic hierarchy and its parent-child edges."""
    nodes = [
        ("1", "Food", "Food and grocery support"),
        ("1.1", "Meals", "Prepared meals and meal delivery"),
        ("1.2", "Groceries", "Staple foods and grocery access"),
        ("1.3", "Infant Nutrition", "Formula and infant feeding supplies"),
        ("2", "Housing", "Housing stability and shelter"),
        ("2.1", "Emergency Shelter", "Short-term safe shelter"),
        ("2.2", "Rent Support", "Help with rent and housing costs"),
        ("2.3", "Home Repairs", "Basic repairs for a safe home"),
        ("3", "Health", "Health and wellness assistance"),
        ("3.1", "Medical Access", "Appointments and medical access"),
        ("3.2", "Mental Wellness", "Emotional and mental wellness support"),
        ("3.3", "Mobility Aids", "Mobility equipment and accessibility"),
        ("4", "Education", "Learning and educational support"),
        ("4.1", "School Supplies", "Supplies for school and learning"),
        ("4.2", "Tutoring", "Tutoring and study support"),
        ("5", "Transportation", "Local transportation assistance"),
        ("5.1", "Rides", "Rides to essential appointments"),
        ("5.2", "Vehicle Repair", "Small repairs needed for transportation"),
        ("6", "Community", "Social connection and community support"),
        ("6.1", "Language Support", "Interpretation and language assistance"),
    ]
    categories = [
        {"cat_id": cat_id, "cat_name": name, "cat_desc": desc, "last_updated_at": LOOKUP_TIMESTAMP}
        for cat_id, name, desc in nodes
    ]
    maps = []
    for cat_id, _, _ in nodes:
        if "." in cat_id:
            maps.append({"parent_id": cat_id.rsplit(".", 1)[0], "child_id": cat_id, "last_updated_at": LOOKUP_TIMESTAMP})
    return categories, maps


def user_id(index: int) -> str:
    """Return a synthetic identifier matching the documented SID pattern."""
    group, suffix = divmod(index, 1000)
    return f"SID-00-000-000-000-{group:03d}-{suffix:03d}"


def request_id(index: int) -> str:
    """Return a synthetic identifier matching the documented REQ pattern."""
    return f"REQ-000-000-000-{index:04d}"


def request_rows(count: int, seed: int) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Create synthetic requests with all specified edge cases."""
    if count < 20:
        raise ValueError("count must be at least 20 so all fixture cases fit")
    rng = random.Random(seed)
    category_ids = ["1.1", "1.2", "1.3", "2.1", "2.2", "2.3", "3.1", "3.2", "3.3", "4.1", "4.2", "5.1", "5.2", "6.1"]
    subjects = ["Grocery delivery request", "Ride to a medical appointment", "Help with school supplies", "Temporary housing support", "Spanish language assistance"]
    descriptions = [
        "A neighbor needs practical support this week.",
        "Please contact the requester to coordinate a suitable time.",
        "The family would appreciate help identifying local resources.",
    ]
    rows: list[dict[str, object]] = []
    pii_manifest: list[dict[str, str]] = []
    pii_payloads = [
        ("Alicia Example", "phone", "Please call Alicia at 202-555-0142 about the delivery."),
        ("José Ejemplo", "phone;email", "José can also be reached at (202) 555-0188 or jose.ejemplo@example.com."),
        ("María Sample", "address;name", "María Sample asked for a visit at 14 Example Street, Sampletown, ZZ 00000."),
        ("Wei Example", "phone_words;name", "Ask Wei Example for directions; the callback number is four eight zero, five five five, zero one two eight."),
        ("Sofía Demo", "phone;email;address", "Sofía Demo: +1 202.555.0175, sofia.demo@example.com, 22 Fictional Road, Sampletown."),
    ]
    boundary = datetime(2026, 10, 1, 12, 0, 0, 123456)
    base = datetime(2026, 1, 1, 8, 0, 0)
    lead_count = max(1, round(count * 3 / 221))
    # Mirror the observed mismatch: three of nine YES flags have a recorded
    # lead, while the other flagged rows remain null. Index 10 is kept null as
    # the individually documented contradiction fixture.
    recorded_flagged = set(range(11, 11 + min(3, lead_count)))
    remaining_leads = max(0, lead_count - len(recorded_flagged))
    candidates = [i for i in range(1, count + 1) if i not in {10, 11, 12, 13, 14, 21, 22, 23, 24}]
    extra_positions = set()
    for i in range(remaining_leads):
        candidate_index = round((i + 1) * (len(candidates) - 1) / (remaining_leads + 1))
        extra_positions.add(candidates[candidate_index])
    lead_positions = recorded_flagged | extra_positions
    beneficiary_null_count = max(1, round(count * 8 / 221))

    for index in range(1, count + 1):
        # Approximate the observed distribution: 7/500 recorded leads and 18/500
        # missing beneficiaries. Reserve specific rows for the special cases.
        lead_non_null = index in lead_positions
        beneficiary_null = index <= beneficiary_null_count
        submission = base + timedelta(days=rng.randrange(0, 300), minutes=rng.randrange(0, 1440))
        updated = submission + timedelta(minutes=rng.randrange(0, 1800))
        if 2 <= index <= 6:
            updated = boundary
        if index == 7:
            submission = datetime(2026, 8, 12, 9, 0, 0)
            updated = datetime(2026, 8, 11, 22, 30, 0, 654321)

        subject = subjects[(index - 1) % len(subjects)]
        description = descriptions[(index - 1) % len(descriptions)]
        if index == 8:
            subject = 'Need help, please bring "warm" meals\nfor the family'
            description = 'The request includes commas, a quoted phrase "if possible", and\na second line for CSV round-trip checks.'
        elif index == 9:
            subject = "Apoyo para la familia en español"
            description = "Necesitamos alimentos y transporte. Gracias por su ayuda; la situación es urgente."
        elif 10 <= index <= 14:
            name, kinds, body = pii_payloads[index - 10]
            subject = f"Synthetic privacy scan fixture: {name}"
            description = body
            pii_manifest.append({"req_id": request_id(index), "details_present": kinds, "note": "Entirely fictional test content; do not contact."})
        elif index == 15:
            subject = "Maximum subject length fixture"
            subject = subject + ("S" * (125 - len(subject)))
        elif index == 16:
            subject = "Maximum description length fixture"
            description = "D" * 255

        # Case 7: use explicit empty strings, not NULL, across each nullable
        # request text field. These three fields are nullable in the schema.
        doc_link: object = None if index % 4 == 0 else f"https://example.com/mock/request/{index}"
        audio_desc: object = None if index % 5 == 0 else "Audio description not supplied."
        deletion_reason: object = None
        if index == 17:
            doc_link = ""
        if index == 18:
            audio_desc = ""
        if index == 19:
            deletion_reason = ""
        if index == 20:
            doc_link = ""
            audio_desc = ""
            deletion_reason = ""
        if index == 25:
            audio_desc = "A" * 255

        # The first nine rows guarantee every status is represented; across
        # all rows every other lookup value is also selected at least once.
        status_id = index - 1 if index <= 9 else rng.randrange(0, 9)
        priority_id = (index - 1) % 4
        for_id = (index - 1) % 2
        islead_id = 1 if index in {10, 11, 12, 13, 14, 21, 22, 23, 24} else 0
        if index == 10:
            # Explicit contradiction fixture: says a lead is assigned, none recorded.
            lead_non_null = False
        row: dict[str, object] = {
            "req_id": request_id(index),
            "creator_id": user_id(index),
            "beneficiary_id": None if beneficiary_null else user_id(500 + index),
            "lead_volunteer_id": user_id(900 + index) if lead_non_null else None,
            "req_cat_id": category_ids[(index - 1) % len(category_ids)],
            "req_for_id": for_id,
            "req_islead_id": islead_id,
            "req_type_id": (index - 1) % 2,
            "req_priority_id": priority_id,
            "req_status_id": status_id,
            "req_subj": subject,
            "req_desc": description,
            "req_doc_link": doc_link,
            "audio_req_desc": audio_desc,
            "deletion_reason": deletion_reason,
            "req_loc": None,
            "created_loc": None,
            "iscalamity": bool(index % 17 == 0),
            "to_public": bool(index % 3 == 0),
            "submission_date": ts(submission),
            "serviced_date": ts(submission + timedelta(days=2)) if index % 6 == 0 else None,
            "last_updated_at": ts(updated),
        }
        rows.append(row)

    # The 11th case is intentionally invalid, isolated from every loadable file.
    broken = dict(rows[0])
    broken["req_id"] = "REQ-999-999-999-9999"
    broken["creator_id"] = "SID-99-999-999-999-999-999"
    broken["req_subj"] = "Broken reference fixture: creator does not exist"
    broken["req_desc"] = "This row is deliberately invalid and must never be loaded with the main data."
    broken["last_updated_at"] = ts(boundary)
    return rows, pii_manifest


def validate_data(rows: list[dict[str, object]], lookup: dict[str, list[dict[str, object]]], categories: list[dict[str, object]], count: int) -> None:
    """Check the output invariants before writing any files."""
    if len(rows) != count:
        raise AssertionError(f"expected {count} request rows, got {len(rows)}")
    if len({row["req_id"] for row in rows}) != count:
        raise AssertionError("request IDs must be unique")
    valid_users = {user_id(i) for i in range(1, count + 1)}
    valid_users |= {user_id(500 + i) for i in range(1, count + 1)}
    valid_users |= {user_id(900 + i) for i in range(1, count + 1)}
    valid_categories = {row["cat_id"] for row in categories}
    status_ids = {row["req_status_id"] for row in lookup["request_statuses"]}
    priority_ids = {row["req_priority_id"] for row in lookup["request_priorities"]}
    for_id_values = {row["req_for_id"] for row in lookup["request_for"]}
    lead_flag_ids = {row["req_islead_id"] for row in lookup["request_isleadvol"]}
    type_ids = {row["req_type_id"] for row in lookup["request_types"]}
    for row in rows:
        for field in ("creator_id", "beneficiary_id", "lead_volunteer_id"):
            if row[field] is not None and row[field] not in valid_users:
                raise AssertionError(f"unmatched {field}: {row[field]}")
        if row["req_cat_id"] not in valid_categories:
            raise AssertionError("unmatched category reference")
        for field, values in (("req_status_id", status_ids), ("req_priority_id", priority_ids),
                              ("req_for_id", for_id_values), ("req_islead_id", lead_flag_ids),
                              ("req_type_id", type_ids)):
            if row[field] not in values:
                raise AssertionError(f"unmatched lookup reference: {field}")
    expected_null_leads = count - max(1, round(count * 3 / 221))
    expected_null_beneficiaries = max(1, round(count * 8 / 221))
    if sum(row["lead_volunteer_id"] is None for row in rows) != expected_null_leads:
        raise AssertionError("lead volunteer null rate does not match the configured skew")
    if sum(row["beneficiary_id"] is None for row in rows) != expected_null_beneficiaries:
        raise AssertionError("beneficiary null rate does not match the configured skew")
    if not any(row["req_islead_id"] == 1 and row["lead_volunteer_id"] is None for row in rows):
        raise AssertionError("missing lead flag/null lead contradiction")
    for field, values in (("req_status_id", status_ids), ("req_priority_id", priority_ids),
                          ("req_for_id", for_id_values), ("req_islead_id", lead_flag_ids),
                          ("req_type_id", type_ids)):
        used = {row[field] for row in rows}
        if values - used:
            raise AssertionError(f"lookup values not represented in requests for {field}: {values - used}")
    if not any(len(str(row["req_subj"])) == 125 for row in rows):
        raise AssertionError("missing varchar(125) subject boundary")
    if not any(len(str(row["req_desc"])) == 255 for row in rows):
        raise AssertionError("missing varchar(255) description boundary")
    if not any(isinstance(row["audio_req_desc"], str) and len(row["audio_req_desc"]) == 255 for row in rows):
        raise AssertionError("missing varchar(255) audio description boundary")
    boundary_count = sum(row["last_updated_at"] == "2026-10-01 12:00:00.123456" for row in rows)
    if boundary_count < 5:
        raise AssertionError("missing multiple rows at the same microsecond boundary")
    if not any(row["last_updated_at"] < row["submission_date"] for row in rows):
        raise AssertionError("missing updated-before-submitted case")
    for field in ("req_doc_link", "audio_req_desc", "deletion_reason"):
        if not any(row[field] == "" for row in rows):
            raise AssertionError(f"missing explicit empty string for {field}")


def validate_schema(schema_file: Path) -> None:
    """Ensure the fixture column definitions still match the bundled DDL."""
    schema_text = schema_file.read_text(encoding="utf-8")
    sql_tables: dict[str, list[str]] = {}
    table_pattern = re.compile(
        r"CREATE\s+TABLE\s+virginia_dev_saayam_rdbms\.([a-z_]+)\s*\((.*?)\);",
        flags=re.IGNORECASE | re.DOTALL,
    )
    column_pattern = re.compile(
        r"^\s*([a-z_][a-z0-9_]*)\s+(?:varchar|integer|serial|text|timestamp|boolean|public\.geometry)\b",
        flags=re.IGNORECASE,
    )
    for match in table_pattern.finditer(schema_text):
        table_name, body = match.groups()
        columns = []
        for line in body.splitlines():
            column_match = column_pattern.match(line)
            if column_match:
                columns.append(column_match.group(1))
        sql_tables[table_name] = columns
    for table, csv_columns in TABLE_COLUMNS.items():
        if table not in sql_tables:
            raise ValueError(f"schema has no table {table}: {schema_file}")
        expected = sql_tables[table]
        # `users.csv` deliberately contains only the primary key to avoid
        # introducing the personal columns found in a real users table.
        if table == "users":
            expected = ["user_id"]
        if csv_columns != expected:
            raise ValueError(
                f"CSV columns for {table} differ from {schema_file}: "
                f"script={csv_columns}, schema={expected}"
            )


def write_outputs(output_dir: Path, count: int, seed: int, schema_file: Path | None = None) -> None:
    """Generate all CSVs and documentation in ``output_dir``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    lookup = lookup_rows()
    categories, category_map = category_rows()
    requests, pii_manifest = request_rows(count, seed)
    validate_data(requests, lookup, categories, count)

    table_data = {
        **lookup,
        "help_categories": categories,
        "help_categories_map": category_map,
        "requests": requests,
        "users": [{"user_id": user_id(i)} for i in range(1, 900 + count + 1)],
    }
    for table_name, columns in TABLE_COLUMNS.items():
        write_csv(output_dir / f"{table_name}.csv", columns, table_data[table_name])
    write_csv(output_dir / "pii_fixture_rows.csv", ["req_id", "details_present", "note"], pii_manifest)

    broken, _ = request_rows(count, seed)
    broken_row = dict(broken[0])
    broken_row.update({
        "req_id": "REQ-999-999-999-9999",
        "creator_id": "SID-99-999-999-999-999-999",
        "req_subj": "Broken reference fixture: creator does not exist",
        "req_desc": "This row is deliberately invalid and must never be loaded with the main data.",
        "last_updated_at": "2026-10-01 12:00:00.123456",
    })
    write_csv(output_dir / "broken_reference_fixture.csv", REQUEST_COLUMNS, [broken_row])

    if schema_file is not None:
        shutil.copyfile(schema_file, output_dir / "saayam_schema.sql")


def outputs_are_deterministic(count: int, seed: int, schema_file: Path | None) -> None:
    """Generate in two temporary folders and compare every emitted byte."""
    with tempfile.TemporaryDirectory(prefix="request-fixture-check-") as temporary:
        root = Path(temporary)
        first, second = root / "first", root / "second"
        write_outputs(first, count, seed, schema_file)
        write_outputs(second, count, seed, schema_file)
        files_first = sorted(path.name for path in first.iterdir())
        files_second = sorted(path.name for path in second.iterdir())
        if files_first != files_second:
            raise AssertionError("generator output file lists differ")
        for name in files_first:
            if (first / name).read_bytes() != (second / name).read_bytes():
                raise AssertionError(f"non-deterministic output: {name}")


def main() -> None:
    """Parse options and write deterministic request archive fixtures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=500, help="number of synthetic requests (default: 500)")
    parser.add_argument("--seed", type=int, default=SEED_DEFAULT, help=f"random seed (default: {SEED_DEFAULT})")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="directory for generated files")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="schema-only SQL file copied into output")
    parser.add_argument("--check-determinism", action="store_true", help="verify two generation runs have identical bytes")
    args = parser.parse_args()
    validate_schema(args.schema)
    if args.check_determinism:
        outputs_are_deterministic(args.count, args.seed, args.schema)
    write_outputs(args.output_dir, args.count, args.seed, args.schema)
    print(f"Generated {args.count} synthetic requests in {args.output_dir}")


if __name__ == "__main__":
    main()
