import argparse
import csv
import random
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


DEFAULT_SEED = 587
DEFAULT_COUNT = 500
BASE_DATE = datetime(2026, 1, 1, 12, 0, 0)
LOOKUP_TIMESTAMP = "2026-10-01 12:00:00.000000"

LOOKUP_VALUES = {
    "request_for": {
        0: "SELF",
        1: "OTHER",
    },
    "request_isleadvol": {
        0: "NO",
        1: "YES",
    },
    "request_types": {
        0: "IN_PERSON",
        1: "REMOTE",
    },
    "request_priorities": {
        0: "LOW",
        1: "MEDIUM",
        2: "HIGH",
        3: "CRITICAL",
    },
    "request_statuses": {
        0: "CREATED",
        1: "MATCHING_VOLUNTEER",
        2: "IN_PROGRESS",
        3: "RESOLVED",
        4: "CANCELLED",
        5: "DELETED",
        6: "RATED_BY_REQUESTER",
        7: "RATED_BY_VOLUNTEER",
        8: "VOLUNTEER_NOT_FOUND",
    },
}

LOOKUP_COLUMNS = {
    "request_for": (
        "req_for_id",
        "req_for",
        "req_for_desc",
    ),
    "request_isleadvol": (
        "req_islead_id",
        "req_islead",
        "req_islead_desc",
    ),
    "request_types": (
        "req_type_id",
        "req_type",
        "req_type_desc",
    ),
    "request_priorities": (
        "req_priority_id",
        "req_priority",
        "req_priority_desc",
    ),
    "request_statuses": (
        "req_status_id",
        "req_status",
        "req_status_desc",
    ),
}

REQUEST_COLUMNS = [
    "req_id",
    "creator_id",
    "beneficiary_id",
    "lead_volunteer_id",
    "req_cat_id",
    "req_for_id",
    "req_islead_id",
    "req_type_id",
    "req_priority_id",
    "req_status_id",
    "req_subj",
    "req_desc",
    "req_doc_link",
    "audio_req_desc",
    "deletion_reason",
    "req_loc",
    "created_loc",
    "iscalamity",
    "to_public",
    "submission_date",
    "serviced_date",
    "last_updated_at",
]

NULLABLE_TEXT_COLUMNS = [
    "req_doc_link",
    "audio_req_desc",
    "deletion_reason",
]

FOREIGN_KEYS = {
    "creator_id": ("users", "user_id"),
    "beneficiary_id": ("users", "user_id"),
    "lead_volunteer_id": ("users", "user_id"),
    "req_cat_id": ("help_categories", "cat_id"),
    "req_for_id": ("request_for", "req_for_id"),
    "req_islead_id": ("request_isleadvol", "req_islead_id"),
    "req_type_id": ("request_types", "req_type_id"),
    "req_priority_id": ("request_priorities", "req_priority_id"),
    "req_status_id": ("request_statuses", "req_status_id"),
}


# ------------------------------------------------------------
# CSV SERIALIZATION
# ------------------------------------------------------------

def csv_field(value):
    """
    Serialize a value for PostgreSQL COPY CSV.

    None -> unquoted empty field -> SQL NULL
    ""   -> quoted empty field   -> empty string

    Other values are quoted to preserve commas, quotes,
    embedded newlines and Unicode.
    """
    if value is None:
        return ""

    if isinstance(value, bool):
        value = "true" if value else "false"

    value = str(value)

    return '"' + value.replace('"', '""') + '"'


def write_csv(path, fieldnames, rows):
    """
    Write deterministic PostgreSQL-compatible CSV files.

    Import with:
      FORMAT csv, HEADER true, NULL ''
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:

        file.write(
            ",".join(csv_field(name) for name in fieldnames)
            + "\n"
        )

        for row in rows:
            file.write(
                ",".join(
                    csv_field(row.get(field))
                    for field in fieldnames
                )
                + "\n"
            )


def read_csv(path):
    with path.open(
        newline="",
        encoding="utf-8",
    ) as file:
        return list(csv.DictReader(file))


# ------------------------------------------------------------
# IDENTIFIERS
# ------------------------------------------------------------

def generate_user_id(number):
    padded = f"{number:015d}"

    return (
        "SID-00-"
        + "-".join(
            padded[index:index + 3]
            for index in range(0, 15, 3)
        )
    )


def generate_request_id(number):
    padded = f"{number:013d}"

    return (
        "REQ-"
        + "-".join([
            padded[0:3],
            padded[3:6],
            padded[6:9],
            padded[9:13],
        ])
    )


def format_timestamp(value):
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")


# ------------------------------------------------------------
# LOOKUP TABLES
# ------------------------------------------------------------

def generate_lookup_tables(output_dir):
    tables = {}

    for table_name, values in LOOKUP_VALUES.items():
        id_col, value_col, desc_col = LOOKUP_COLUMNS[
            table_name
        ]

        rows = []

        for lookup_id, lookup_value in values.items():
            rows.append({
                id_col: lookup_id,
                value_col: lookup_value,
                desc_col: (
                    f"Synthetic lookup: {lookup_value}"
                ),
                "last_updated_at": LOOKUP_TIMESTAMP,
            })

        write_csv(
            output_dir / f"{table_name}.csv",
            [
                id_col,
                value_col,
                desc_col,
                "last_updated_at",
            ],
            rows,
        )

        tables[table_name] = rows

        print(
            f"Generated {len(rows)} rows for {table_name}"
        )

    return tables


# ------------------------------------------------------------
# CATEGORY TREE
# ------------------------------------------------------------

def generate_categories(output_dir):
    category_tree = {
        "1": (
            "Food Assistance",
            [
                "Groceries",
                "Prepared Meals",
                "Food Delivery",
            ],
        ),
        "2": (
            "Housing Assistance",
            [
                "Temporary Shelter",
                "Rent Support",
                "Home Repairs",
            ],
        ),
        "3": (
            "Healthcare Assistance",
            [
                "Medical Transportation",
                "Medication Support",
                "Health Appointments",
            ],
        ),
        "4": (
            "Education Assistance",
            [
                "School Supplies",
                "Tutoring",
                "Digital Learning",
            ],
        ),
        "5": (
            "Transportation Assistance",
            [
                "Emergency Transportation",
                "Community Transportation",
                "Accessibility Support",
            ],
        ),
    }

    categories = []
    mappings = []

    for parent_id, (parent_name, children) in (
        category_tree.items()
    ):
        categories.append({
            "cat_id": parent_id,
            "cat_name": parent_name,
            "cat_desc": (
                f"Synthetic category for {parent_name}"
            ),
            "last_updated_at": LOOKUP_TIMESTAMP,
        })

        for index, child_name in enumerate(
            children,
            start=1,
        ):
            child_id = f"{parent_id}.{index}"

            categories.append({
                "cat_id": child_id,
                "cat_name": child_name,
                "cat_desc": (
                    f"Synthetic category for {child_name}"
                ),
                "last_updated_at": LOOKUP_TIMESTAMP,
            })

            mappings.append({
                "parent_id": parent_id,
                "child_id": child_id,
                "last_updated_at": LOOKUP_TIMESTAMP,
            })

    write_csv(
        output_dir / "help_categories.csv",
        [
            "cat_id",
            "cat_name",
            "cat_desc",
            "last_updated_at",
        ],
        categories,
    )

    write_csv(
        output_dir / "help_categories_map.csv",
        [
            "parent_id",
            "child_id",
            "last_updated_at",
        ],
        mappings,
    )

    print(f"Generated {len(categories)} categories")
    print(f"Generated {len(mappings)} category mappings")

    return categories, mappings


# ------------------------------------------------------------
# USERS
# ------------------------------------------------------------

def generate_users(count=250):
    return [
        {
            "user_id": generate_user_id(index),
            "last_updated_at": LOOKUP_TIMESTAMP,
        }
        for index in range(1, count + 1)
    ]


# ------------------------------------------------------------
# REQUEST GENERATION
# ------------------------------------------------------------

def generate_requests(count, users, categories, seed):
    if count < 20:
        raise ValueError(
            "At least 20 requests are required to cover "
            "all mandatory special cases."
        )

    rng = random.Random(seed)

    user_ids = [row["user_id"] for row in users]
    category_ids = [row["cat_id"] for row in categories]

    subjects = [
        "Need grocery assistance",
        "Request for medical transportation",
        "Need temporary housing support",
        "Help with school supplies",
        "Transportation assistance required",
        "Emergency food assistance",
        "Community support request",
        "Necesito ayuda con alimentos",
    ]

    descriptions = [
        "I need assistance with groceries this week.",
        "Looking for transportation to a medical appointment.",
        "Need temporary housing assistance for my family.",
        "Requesting school supplies for children.",
        "Necesito ayuda con alimentos y transporte.",
        'Please deliver supplies to "Building A", near the community center.',
        "First line of request.\nSecond line contains additional details.",
        "Please contact the coordinator for more information.",
    ]

    requests = []

    for index in range(1, count + 1):
        submission_date = BASE_DATE + timedelta(
            days=rng.randint(0, 270),
            hours=rng.randint(0, 23),
            minutes=rng.randint(0, 59),
        )

        updated_date = submission_date + timedelta(
            days=rng.randint(0, 30),
            microseconds=rng.randint(0, 999999),
        )

        request = {
            "req_id": generate_request_id(index),
            "creator_id": rng.choice(user_ids),
            "beneficiary_id": rng.choice(user_ids),
            "lead_volunteer_id": None,
            "req_cat_id": rng.choice(category_ids),
            "req_for_id": rng.choice([0, 1]),
            "req_islead_id": rng.choice([0, 1]),
            "req_type_id": rng.choice([0, 1]),
            "req_priority_id": rng.choice([0, 1, 2, 3]),
            "req_status_id": rng.choice(list(range(9))),
            "req_subj": rng.choice(subjects),
            "req_desc": rng.choice(descriptions),
            "req_doc_link": None,
            "audio_req_desc": None,
            "deletion_reason": None,
            "req_loc": None,
            "created_loc": None,
            "iscalamity": rng.choice(
                [True, False, None]
            ),
            "to_public": rng.choice(
                [True, False]
            ),
            "submission_date": format_timestamp(
                submission_date
            ),
            "serviced_date": None,
            "last_updated_at": format_timestamp(
                updated_date
            ),
        }

        requests.append(request)

    # Match the approximate live-data NULL distributions.
    lead_count = round(count * 3 / 221)
    beneficiary_null_count = round(count * 8 / 221)

    for request in rng.sample(requests, lead_count):
        request["lead_volunteer_id"] = rng.choice(
            user_ids
        )

    for request in rng.sample(
        requests,
        beneficiary_null_count,
    ):
        request["beneficiary_id"] = None

    # Make the first twelve requests deterministic fixtures.
    # Remove any randomly assigned lead volunteers from these
    # rows, then restore the target number elsewhere.
    for request in requests[:12]:
        request["lead_volunteer_id"] = None

    assigned = [
        request
        for request in requests
        if request["lead_volunteer_id"] is not None
    ]

    needed = lead_count - len(assigned)

    candidates = [
        request
        for request in requests[12:]
        if request["lead_volunteer_id"] is None
    ]

    for request in rng.sample(candidates, needed):
        request["lead_volunteer_id"] = rng.choice(
            user_ids
        )

    # CASE 1: Skewed NULL references.
    # Handled above.

    # CASE 2: Shared microsecond timestamp.
    shared_timestamp = "2026-07-15 10:30:45.123456"

    for request in requests[:5]:
        request["last_updated_at"] = shared_timestamp

    # CASE 3: Update earlier than submission.
    requests[5]["submission_date"] = (
        "2026-08-15 12:00:00.000000"
    )
    requests[5]["last_updated_at"] = (
        "2026-08-14 12:00:00.000000"
    )

    # CASE 4: Embedded CSV special characters.
    requests[6]["req_desc"] = (
        'Please deliver food to "Building A",\n'
        "near the community center."
    )

    # CASE 5: Non-ASCII text.
    requests[7]["req_desc"] = (
        "Necesito ayuda con alimentos para mi familia."
    )

    # CASE 6: Synthetic personal details.
    requests[8]["req_desc"] = (
        "Contact María López at maria.lopez@example.com "
        "or 202-555-0147."
    )

    requests[9]["req_desc"] = (
        "Please call (202) 555-0184 or email "
        "helpdesk@example.org."
    )

    requests[10]["req_desc"] = (
        "Synthetic address: 123 Example Street, "
        "Sample City. Call four eight zero "
        "five five five zero one two three."
    )

    # CASE 7: NULL and empty strings are different.
    requests[11]["req_doc_link"] = ""
    requests[11]["audio_req_desc"] = ""
    requests[11]["deletion_reason"] = ""

    # CASE 8: Maximum field lengths.
    requests[12]["req_subj"] = "S" * 125
    requests[13]["req_desc"] = "D" * 255

    # CASE 9: Every lookup value represented.
    for index, status_id in enumerate(range(9)):
        requests[index]["req_status_id"] = status_id

    for index, priority_id in enumerate(range(4)):
        requests[index]["req_priority_id"] = priority_id

    for index, value in enumerate(range(2)):
        requests[index]["req_for_id"] = value
        requests[index]["req_islead_id"] = value
        requests[index]["req_type_id"] = value

    # CASE 10: Contradictory lead-volunteer flag.
    requests[14]["req_islead_id"] = 1
    requests[14]["lead_volunteer_id"] = None

    # Include optional text values as well as NULL/empty.
    requests[15]["req_doc_link"] = (
        "https://example.com/synthetic-document"
    )
    requests[16]["audio_req_desc"] = (
        "Synthetic audio description."
    )
    requests[17]["deletion_reason"] = (
        "Synthetic cancellation reason."
    )

    # Optional timestamps.
    requests[18]["serviced_date"] = (
        "2026-09-01 10:00:00.000000"
    )

    # Optional location fields, using PostGIS EWKT.
    requests[19]["req_loc"] = (
        "SRID=4326;POINT(-84.5120 39.1031)"
    )
    requests[19]["created_loc"] = (
        "SRID=4326;POINT(-84.5100 39.1000)"
    )

    # Make sure each nullable reference has a NULL.
    # Preserve the overall beneficiary NULL target.
    if all(
        request["beneficiary_id"] is not None
        for request in requests
    ):
        requests[0]["beneficiary_id"] = None

    return requests


# ------------------------------------------------------------
# SPECIAL-CASE MANIFEST
# ------------------------------------------------------------

def generate_special_cases(output_dir, requests):
    cases = [
        (
            1,
            "Skewed NULL references",
            requests[0]["req_id"],
        ),
        (
            2,
            "Shared microsecond timestamp",
            requests[0]["req_id"],
        ),
        (
            3,
            "Update earlier than submission",
            requests[5]["req_id"],
        ),
        (
            4,
            "Embedded newline comma and quotes",
            requests[6]["req_id"],
        ),
        (
            5,
            "Non-ASCII text",
            requests[7]["req_id"],
        ),
        (
            6,
            "Synthetic personal details",
            requests[8]["req_id"],
        ),
        (
            7,
            "Empty string distinct from NULL",
            requests[11]["req_id"],
        ),
        (
            8,
            "Maximum-length subject and description",
            requests[12]["req_id"],
        ),
        (
            9,
            "All lookup values represented",
            requests[0]["req_id"],
        ),
        (
            10,
            "Lead flag contradicts volunteer ID",
            requests[14]["req_id"],
        ),
        (
            11,
            "Broken foreign-key reference",
            "BROKEN_REFERENCE_FIXTURE",
        ),
    ]

    rows = [
        {
            "case_number": number,
            "description": description,
            "req_id": req_id,
        }
        for number, description, req_id in cases
    ]

    write_csv(
        output_dir / "special_cases.csv",
        [
            "case_number",
            "description",
            "req_id",
        ],
        rows,
    )

    return rows


# ------------------------------------------------------------
# BROKEN-REFERENCE FIXTURE
# ------------------------------------------------------------

def generate_broken_reference_fixture(
    output_dir,
    requests,
):
    broken = requests[0].copy()

    broken["req_id"] = (
        "REQ-999-999-999-9999"
    )

    broken["creator_id"] = (
        "SID-99-999-999-999-999-999"
    )

    write_csv(
        output_dir / "broken_reference_fixture.csv",
        REQUEST_COLUMNS,
        [broken],
    )

    print("Generated broken-reference fixture")


# ------------------------------------------------------------
# VALIDATION
# ------------------------------------------------------------

def validate_foreign_keys(tables):
    requests = tables["requests"]

    for field, (table_name, key) in (
        FOREIGN_KEYS.items()
    ):
        valid_ids = {
            str(row[key])
            for row in tables[table_name]
        }

        for request in requests:
            value = request[field]

            if value is None:
                continue

            if str(value) not in valid_ids:
                raise ValueError(
                    f"Invalid foreign key: "
                    f"{request['req_id']} "
                    f"{field}={value}"
                )

    print(
        "PASS: All nine request foreign-key "
        "relationships are valid"
    )


def validate_requests(requests, tables):
    if not requests:
        raise ValueError("No requests generated")

    request_ids = [
        request["req_id"]
        for request in requests
    ]

    assert len(request_ids) == len(set(request_ids))

    for request in requests:
        assert request["req_subj"] is not None
        assert request["req_desc"] is not None

        assert len(request["req_subj"]) <= 125
        assert len(request["req_desc"]) <= 255

    assert any(
        len(request["req_subj"]) == 125
        for request in requests
    )

    assert any(
        len(request["req_desc"]) == 255
        for request in requests
    )

    for field, table_name in [
        ("req_for_id", "request_for"),
        ("req_islead_id", "request_isleadvol"),
        ("req_type_id", "request_types"),
        ("req_priority_id", "request_priorities"),
        ("req_status_id", "request_statuses"),
    ]:
        expected = {
            str(row[LOOKUP_COLUMNS[table_name][0]])
            for row in tables[table_name]
        }

        actual = {
            str(request[field])
            for request in requests
        }

        assert expected <= actual, (
            f"Missing lookup coverage for {field}"
        )

    assert any(
        request["req_islead_id"] == 1
        and request["lead_volunteer_id"] is None
        for request in requests
    )

    assert any(
        request["req_doc_link"] == ""
        for request in requests
    )

    assert any(
        request["req_doc_link"] is None
        for request in requests
    )

    assert any(
        request["audio_req_desc"] == ""
        for request in requests
    )

    assert any(
        request["deletion_reason"] == ""
        for request in requests
    )

    assert any(
        "\n" in request["req_desc"]
        for request in requests
    )

    assert any(
        '"' in request["req_desc"]
        for request in requests
    )

    assert any(
        any(ord(char) > 127 for char in request["req_desc"])
        for request in requests
    )

    assert any(
        request["last_updated_at"]
        < request["submission_date"]
        for request in requests
    )

    timestamps = Counter(
        request["last_updated_at"]
        for request in requests
    )

    assert any(
        count >= 5
        for count in timestamps.values()
    )

    print(
        f"PASS: Validated {len(requests)} requests"
    )


def print_summary(requests):
    total = len(requests)

    missing_lead = sum(
        request["lead_volunteer_id"] is None
        for request in requests
    )

    missing_beneficiary = sum(
        request["beneficiary_id"] is None
        for request in requests
    )

    timestamps = Counter(
        request["last_updated_at"]
        for request in requests
    )

    shared_rows = sum(
        count
        for count in timestamps.values()
        if count > 1
    )

    contradictory = sum(
        request["req_islead_id"] == 1
        and request["lead_volunteer_id"] is None
        for request in requests
    )

    print()
    print("=" * 55)
    print("SAAYAM ISSUE #587 - GENERATION SUMMARY")
    print("=" * 55)

    print("Total requests:", total)
    print("Missing lead volunteers:", missing_lead)
    print("Missing beneficiaries:", missing_beneficiary)
    print("Rows with shared timestamps:", shared_rows)
    print(
        "Contradictory lead-volunteer records:",
        contradictory,
    )

    print(
        "Lead volunteer NULL percentage:",
        round(missing_lead / total * 100, 2),
    )

    print(
        "Beneficiary NULL percentage:",
        round(missing_beneficiary / total * 100, 2),
    )

    print("=" * 55)


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate deterministic synthetic request "
            "data for Saayam Issue #587."
        )
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
    )

    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
    )

    parser.add_argument(
        "--output-dir",
        default="/tmp/saayam_mock_587",
    )

    args = parser.parse_args()

    if args.count < 20:
        parser.error(
            "--count must be at least 20"
        )

    output_dir = Path(args.output_dir)

    print("Generating synthetic Saayam data...")

    tables = generate_lookup_tables(output_dir)

    categories, mappings = generate_categories(
        output_dir
    )

    tables["help_categories"] = categories
    tables["help_categories_map"] = mappings

    users = generate_users(
        count=max(250, args.count // 2)
    )

    tables["users"] = users

    write_csv(
        output_dir / "users.csv",
        [
            "user_id",
            "last_updated_at",
        ],
        users,
    )

    print(f"Generated {len(users)} users")

    requests = generate_requests(
        count=args.count,
        users=users,
        categories=categories,
        seed=args.seed,
    )

    tables["requests"] = requests

    write_csv(
        output_dir / "requests.csv",
        REQUEST_COLUMNS,
        requests,
    )

    print(f"Generated {len(requests)} requests")

    generate_broken_reference_fixture(
        output_dir,
        requests,
    )

    special_cases = generate_special_cases(
        output_dir,
        requests,
    )

    print(
        f"Generated {len(special_cases)} "
        "special-case records"
    )

    validate_foreign_keys(tables)
    validate_requests(requests, tables)

    print_summary(requests)

    print()
    print("Mock-data generation completed successfully.")
    print("Output directory:", output_dir)


if __name__ == "__main__":
    main()