"""Generate synthetic request-archival fixtures from the issue #573 schema."""

import argparse
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import random
import re


HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "saayam_schema.sql"
DEFAULT_OUTPUT = HERE.parents[1] / "sql"
NULL = r"\N"
STAMP = datetime(2026, 10, 24, 12, 0, 0, 123456)
LONG_USER = "SID-MAX-" + "X" * 247
LONG_CATEGORY = "9." + "1" * 48
LONG_REQUEST = "REQ-MAX-" + "X" * 247
TABLES = (
    "help_categories",
    "help_categories_map",
    "request_for",
    "request_isleadvol",
    "request_types",
    "request_priorities",
    "request_statuses",
    "users",
    "requests",
)
LOOKUPS = {
    "request_for": ("req_for", ("SELF", "OTHER")),
    "request_isleadvol": ("req_islead", ("NO", "YES")),
    "request_types": ("req_type", ("IN_PERSON", "REMOTE")),
    "request_priorities": ("req_priority", ("LOW", "MEDIUM", "HIGH", "CRITICAL")),
    "request_statuses": (
        "req_status",
        (
            "CREATED",
            "MATCHING_VOLUNTEER",
            "IN_PROGRESS",
            "RESOLVED",
            "CANCELLED",
            "DELETED",
            "RATED_BY_REQUESTER",
            "RATED_BY_VOLUNTEER",
            "VOLUNTEER_NOT_FOUND",
        ),
    ),
}


def read_schema():
    """Read column definitions and inline references in the supplied DDL."""
    sql = re.sub(r"--[^\n]*", "", SCHEMA_PATH.read_text(encoding="utf-8"))
    schema = {}
    for table in TABLES:
        body = re.search(
            rf"CREATE TABLE virginia_dev_saayam_rdbms\.{table} \((.*?)\n\);", sql, re.S
        )[1]
        columns = list(
            re.finditer(
                r"^\s*(\w+)\s+(varchar\(\d+\)|public\.geometry\(Point,4326\)|"
                r"timestamp(?:\(6\))?|serial|integer|text|boolean)",
                body,
                re.M,
            )
        )
        definitions = {}
        for index, match in enumerate(columns):
            declaration = body[
                match.start() : columns[index + 1].start()
                if index + 1 < len(columns)
                else len(body)
            ]
            ref = re.search(
                r"REFERENCES virginia_dev_saayam_rdbms\.(\w+)\((\w+)\)", declaration
            )
            length = re.fullmatch(r"varchar\((\d+)\)", match[2])
            definitions[match[1]] = {
                "type": match[2],
                "limit": int(length[1]) if length else None,
                "nullable": "NOT NULL" not in declaration
                and "PRIMARY KEY" not in declaration,
                "primary_key": "PRIMARY KEY" in declaration,
                "reference": (ref[1], ref[2]) if ref else None,
            }
        schema[table] = definitions
    return schema


def timestamp(value):
    """Format UTC-by-convention, timezone-free values with microseconds."""
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


def build_dataset(seed=42, row_count=500):
    """Build independent deterministic data and row-level case/PII manifests."""
    if row_count < 50:
        raise ValueError(
            "At least 50 requests are needed to preserve every fixture case"
        )
    rng = random.Random(seed)
    tables = {table: [] for table in TABLES}
    categories = [
        ("1", "MOCK_ESSENTIALS", None),
        ("1.1", "MOCK_MEALS", "1"),
        ("1.2", "MOCK_SUPPLIES", "1"),
        ("2", "MOCK_MOBILITY", None),
        ("2.1", "MOCK_LOCAL_TRANSPORT", "2"),
        ("2.2", "MOCK_DELIVERY", "2"),
        ("3", "MOCK_LEARNING", None),
        ("3.1", "MOCK_LANGUAGE_PRACTICE", "3"),
        ("3.2", "MOCK_DIGITAL_SKILLS", "3"),
        ("4", "MOCK_HOME_SUPPORT", None),
        ("4.1", "MOCK_SMALL_REPAIRS", "4"),
        ("4.2", "MOCK_GARDEN_HELP", "4"),
        ("9", "MOCK_LENGTH_BOUNDARY", None),
        (LONG_CATEGORY, "MOCK_LONG_CATEGORY_KEY", "9"),
    ]
    for key, name, parent in categories:
        tables["help_categories"].append(
            {
                "cat_id": key,
                "cat_name": name,
                "cat_desc": "Synthetic category for local pipeline testing.",
                "last_updated_at": timestamp(STAMP),
            }
        )
        tables["help_categories_map"].append(
            {
                "parent_id": parent,
                "child_id": key,
                "last_updated_at": timestamp(STAMP),
            }
        )
    for table, (prefix, values) in LOOKUPS.items():
        for key, value in enumerate(values):
            tables[table].append(
                {
                    prefix + "_id": key,
                    prefix: value,
                    prefix + "_desc": None
                    if key == 0
                    else ("" if key == 1 else "Synthetic lookup description."),
                    "last_updated_at": timestamp(STAMP),
                }
            )
    user_ids = [f"SID-MOCK-{index:04d}" for index in range(1, 101)]
    tables["users"] = [{"user_id": key} for key in [*user_ids, "", LONG_USER]]

    # Preserve the observed shape, with explicit empty and maximum-length FK cases.
    lead_count = max(2, round(row_count * 3 / 221))
    lead_present = {8, 11}
    lead_present.update(
        rng.sample(
            [i for i in range(row_count) if i not in {0, 8, 10, 11}], lead_count - 2
        )
    )
    beneficiary_null = {0}
    beneficiary_null.update(
        rng.sample(
            [i for i in range(row_count) if i not in {0, 8, 11}],
            round(row_count * 8 / 221) - 1,
        )
    )
    lead_flags = lead_present | {10}
    flag_count = max(len(lead_flags), round(row_count * 9 / 221))
    lead_flags.update(
        rng.sample(
            [i for i in range(row_count) if i not in lead_flags],
            flag_count - len(lead_flags),
        )
    )

    for index in range(row_count):
        submitted = datetime(2026, 7, 1) + timedelta(
            days=rng.randrange(110), seconds=rng.randrange(86400)
        )
        updated = submitted + timedelta(
            days=rng.randrange(4), microseconds=rng.randrange(1000000)
        )
        row = {
            "req_id": f"REQ-MOCK-{index + 1:04d}",
            "creator_id": rng.choice(user_ids),
            "beneficiary_id": None
            if index in beneficiary_null
            else rng.choice(user_ids),
            "lead_volunteer_id": rng.choice(user_ids)
            if index in lead_present
            else None,
            "req_cat_id": categories[index % len(categories)][0],
            "req_for_id": index % 2,
            "req_islead_id": int(index in lead_flags),
            "req_type_id": index % 2,
            "req_priority_id": index % 4,
            "req_status_id": index % 9,
            "req_subj": f"Synthetic support request {index + 1}",
            "req_desc": f"Mock request {index + 1}: please help with a local community task.",
            "req_doc_link": None
            if index % 3 == 0
            else ("" if index % 3 == 1 else f"https://example.org/mock/{index + 1}"),
            "audio_req_desc": None
            if index % 3 == 0
            else ("" if index % 3 == 1 else "Synthetic audio transcript."),
            "deletion_reason": None
            if index % 3 == 0
            else ("" if index % 3 == 1 else "Synthetic cleanup request."),
            "req_loc": None
            if index % 5 == 0
            else f"SRID=4326;POINT({-112 + rng.random():.6f} {33 + rng.random():.6f})",
            "created_loc": None
            if index % 7 == 0
            else "SRID=4326;POINT(-111.900000 33.400000)",
            "iscalamity": None if index % 4 == 0 else index % 4 == 1,
            "to_public": None if index % 6 == 0 else index % 2 == 0,
            "submission_date": timestamp(submitted),
            "serviced_date": timestamp(submitted + timedelta(days=2))
            if index % 9 == 3
            else None,
            "last_updated_at": timestamp(updated),
        }
        tables["requests"].append(row)
    requests = tables["requests"]
    for row in requests[:3]:
        row["last_updated_at"] = timestamp(STAMP)
    requests[3]["last_updated_at"] = timestamp(STAMP - timedelta(microseconds=1))
    requests[4]["last_updated_at"] = timestamp(STAMP + timedelta(microseconds=1))
    requests[5]["submission_date"] = timestamp(STAMP + timedelta(days=1))
    requests[5]["last_updated_at"] = timestamp(STAMP)
    requests[6]["req_desc"] = (
        'Please bring "blankets", coats,\nand food. This is synthetic text.'
    )
    requests[7]["req_desc"] = (
        "Necesito ayuda mañana: información, educación y acompañamiento. Datos sintéticos."
    )
    for field in (
        "beneficiary_id",
        "lead_volunteer_id",
        "req_doc_link",
        "audio_req_desc",
        "deletion_reason",
    ):
        requests[0][field] = None
        requests[8][field] = ""
    requests[11].update(
        {
            "req_id": LONG_REQUEST,
            "creator_id": LONG_USER,
            "beneficiary_id": LONG_USER,
            "lead_volunteer_id": LONG_USER,
            "req_cat_id": LONG_CATEGORY,
            "req_subj": "S" * 125,
            "req_desc": "D" * 255,
            "audio_req_desc": "A" * 255,
        }
    )

    planted = [
        (
            "Lucía Ejemplo",
            "(202) 555-0101",
            "lucia.ejemplo@example.org",
            "101 Fictional Example Street",
        ),
        (
            "José Prueba",
            "202.555.0102",
            "jose.prueba@example.net",
            "202 Imaginary Test Avenue",
        ),
        (
            "Zoë Ficticia",
            "+1-202-555-0103",
            "zoe.ficticia@example.com",
            "303 Synthetic Sample Road",
        ),
        (
            "Ananya Sample",
            "202 555 0104",
            "ananya.sample@example.org",
            "404 Fabricated Demo Lane",
        ),
        (
            "李示例",
            "two zero two five five five zero one zero five",
            "sample.li@example.net",
            "505 Mock Example Boulevard",
        ),
        (
            "أمل مثال",
            "four eight zero five five five zero one zero six",
            "amal.example@example.com",
            "606 Pretend Testing Drive",
        ),
    ]
    pii = []
    for index, (name, phone, email, address) in enumerate(planted, 16):
        requests[index]["req_desc"] = (
            f"Synthetic person: {name}. Phone: {phone}. Email: {email}. Address: {address}, Fictional City."
        )
        pii.append(
            {
                "req_id": requests[index]["req_id"],
                "fields": "req_desc",
                "pii_types": "name;phone;email;street_address",
                "synthetic": "true",
            }
        )

    cases = []

    def mark(case, indexes, columns, detail):
        """Record actual request identifiers for a numbered issue case."""
        for index in indexes:
            cases.append(
                {
                    "case_number": case,
                    "file": "requests.csv",
                    "req_id": requests[index]["req_id"],
                    "columns": columns,
                    "description": detail,
                }
            )

    mark(
        1,
        [0],
        "beneficiary_id;lead_volunteer_id",
        "Both nullable references are null; the README documents the full-column null rates.",
    )
    mark(
        2,
        [0, 1, 2, 3, 4, 5],
        "last_updated_at",
        "Rows 1-3 and 6 share 2026-10-24 12:00:00.123456; rows 4 and 5 differ by one microsecond.",
    )
    mark(
        3,
        [5],
        "last_updated_at;submission_date",
        "Update timestamp precedes submission by one day.",
    )
    mark(4, [6], "req_desc", "Embedded newline, comma and double quotes.")
    mark(5, [7], "req_desc", "Non-ASCII Spanish text.")
    mark(
        6,
        range(16, 22),
        "req_desc",
        "Planted synthetic personal details; see pii_manifest.csv.",
    )
    mark(
        7,
        [0, 8],
        "beneficiary_id;lead_volunteer_id;req_doc_link;audio_req_desc;deletion_reason",
        r"Row 1 has nulls (\N); row 9 has empty strings, including valid FKs to the empty user key.",
    )
    mark(
        8,
        [11],
        "req_id;creator_id;beneficiary_id;lead_volunteer_id;req_cat_id;req_subj;req_desc;audio_req_desc",
        "Every varchar column in requests reaches its declared maximum length.",
    )
    coverage = set()
    for field in (
        "req_cat_id",
        "req_for_id",
        "req_islead_id",
        "req_type_id",
        "req_priority_id",
        "req_status_id",
    ):
        first = {}
        for index, row in enumerate(requests):
            first.setdefault(row[field], index)
        coverage.update(first.values())
    mark(
        9,
        sorted(coverage),
        "req_cat_id;req_for_id;req_islead_id;req_type_id;req_priority_id;req_status_id",
        "These rows collectively exercise every lookup and category value.",
    )
    mark(
        10,
        [10],
        "req_islead_id;lead_volunteer_id",
        "Lead flag is 1 but the lead volunteer is null.",
    )
    broken = dict(
        requests[0], req_id="REQ-BROKEN-REFERENCE", creator_id="SID-MISSING-FIXTURE"
    )
    cases.append(
        {
            "case_number": 11,
            "file": "fixtures/requests_broken_reference.csv",
            "req_id": broken["req_id"],
            "columns": "creator_id",
            "description": "Missing user reference, deliberately excluded from the loadable main data.",
        }
    )
    return tables, cases, pii, broken


def validate_dataset(tables, schema):
    """Validate keys, constraints, declared lengths and basic scalar types."""
    for table, rows in tables.items():
        definitions = schema[table]
        keys = [name for name, column in definitions.items() if column["primary_key"]]
        seen = set()
        for row in rows:
            expected = {"user_id"} if table == "users" else set(definitions)
            if set(row) != expected:
                raise ValueError(f"Column mismatch in {table}")
            key = tuple(row[name] for name in keys)
            if key in seen:
                raise ValueError(f"Duplicate primary key in {table}: {key}")
            seen.add(key)
            for name, value in row.items():
                column = definitions[name]
                if value is None:
                    if not column["nullable"]:
                        raise ValueError(f"Null in required column {table}.{name}")
                    continue
                if column["limit"] and len(value) > column["limit"]:
                    raise ValueError(f"Length exceeded in {table}.{name}")
                if value == NULL:
                    raise ValueError("The null marker cannot be used as literal text")
                if column["reference"]:
                    target, target_key = column["reference"]
                    if value not in {record[target_key] for record in tables[target]}:
                        raise ValueError(
                            f"Unmatched reference in {table}.{name}: {value}"
                        )
                if column["type"] in {"integer", "serial"} and type(value) is not int:
                    raise ValueError(f"Invalid integer in {table}.{name}")
                if column["type"] == "boolean" and type(value) is not bool:
                    raise ValueError(f"Invalid boolean in {table}.{name}")
                if column["type"].startswith("timestamp"):
                    datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f")


def encode(value):
    """Encode SQL null independently of an empty string for COPY NULL '\\N'."""
    if value is None:
        return NULL
    if isinstance(value, bool):
        return str(value).lower()
    return value


def write_csv(path, columns, rows):
    """Write UTF-8 with standard CSV quoting and stable LF line endings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([encode(row[column]) for column in columns])


def generate(output_dir, seed=42, row_count=500):
    """Validate before writing only the generator's own explicitly named files."""
    schema = read_schema()
    tables, cases, pii, broken = build_dataset(seed, row_count)
    validate_dataset(tables, schema)
    output_dir = Path(output_dir)
    for table in TABLES:
        columns = ["user_id"] if table == "users" else list(schema[table])
        write_csv(output_dir / f"{table}.csv", columns, tables[table])
    write_csv(
        output_dir / "fixtures/requests_broken_reference.csv",
        list(schema["requests"]),
        [broken],
    )
    write_csv(output_dir / "special_cases.csv", list(cases[0]), cases)
    write_csv(output_dir / "pii_manifest.csv", list(pii[0]), pii)
    manifest = {
        "schema_source": "https://github.com/user-attachments/files/33914221/saayam_schema.sql",
        "seed": seed,
        "request_count": row_count,
        "null_marker": NULL,
        "table_rows": {table: len(rows) for table, rows in tables.items()},
        "null_counts": {
            key: sum(row[key] is None for row in tables["requests"])
            for key in ("lead_volunteer_id", "beneficiary_id")
        },
        "synthetic_pii_rows": [row["req_id"] for row in pii],
        "boundary_timestamp": timestamp(STAMP),
    }
    return manifest


def main():
    """Expose a dependency-free, seedable command-line generator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--rows", type=int, default=500, help="Number of requests, at least 50"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.rows < 50:
        parser.error("--rows must be at least 50")
    manifest = generate(args.output_dir, args.seed, args.rows)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
