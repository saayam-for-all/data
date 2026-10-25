"""Validate the generated CSVs against the Virginia schema and issue #301.

Every check in the issue's "Data Quality Validation" section is implemented
here. The expected schema below is restated independently of the generators so
that this is a real check rather than a restatement of what was written.

Run:  python validate_mock_data.py
Exit status is 0 when every check passes, 1 otherwise.
"""

import csv
import json
import re
import sys
from datetime import datetime

import config

TIMESTAMP = "%Y-%m-%d %H:%M:%S"
DATE = "%Y-%m-%d"

POINT_RE = re.compile(r"^\(-?\d+\.\d+,-?\d+\.\d+\)$")
EWKT_RE = re.compile(r"^SRID=4326;POINT\(-?\d+\.\d+ -?\d+\.\d+\)$")

# column -> (type, nullable, extra)
SCHEMA = {
    "countries.csv": {
        "pk": ["country_id"],
        "columns": [
            ("country_id", "int", False),
            ("country_name", "varchar:100", False),
            ("phone_code", "varchar:5", False),
            ("country_code", "varchar:6", False),
            ("last_updated_at", "timestamp", True),
            ("is_eu_member", "bool", True),
        ],
    },
    "states.csv": {
        "pk": ["state_id"],
        "columns": [
            ("state_id", "varchar:50", False),
            ("country_id", "int", False),
            ("state_name", "varchar:100", False),
            ("state_code", "varchar:6", True),
            ("last_updated_at", "timestamp", True),
        ],
    },
    "cities.csv": {
        "pk": ["city_id"],
        "columns": [
            ("city_id", "int", False),
            ("state_id", "varchar:50", False),
            ("city_name", "varchar:30", False),
            ("lattitude", "decimal", True),
            ("longitude", "decimal", True),
            ("last_updated_at", "timestamp", True),
        ],
    },
    "help_categories.csv": {
        "pk": ["cat_id"],
        "columns": [
            ("cat_id", "varchar:50", False),
            ("cat_name", "varchar:100", False),
            ("cat_desc", "varchar:150", False),
            ("last_updated_at", "timestamp", True),
        ],
    },
    "users.csv": {
        "pk": ["user_id"],
        "columns": [
            ("user_id", "varchar:255", False),
            ("state_id", "varchar:30", True),
            ("country_id", "int", True),
            ("user_status_id", "int", True),
            ("full_name", "varchar:255", True),
            ("first_name", "varchar:255", True),
            ("middle_name", "varchar:255", True),
            ("last_name", "varchar:255", True),
            ("primary_email_address", "varchar:255", True),
            ("primary_phone_number", "varchar:255", True),
            ("addr_ln1", "varchar:255", True),
            ("addr_ln2", "varchar:255", True),
            ("addr_ln3", "varchar:255", True),
            ("city_name", "varchar:255", True),
            ("zip_code", "varchar:255", True),
            ("last_location", "point", True),
            ("last_updated_at", "timestamp", True),
            ("time_zone", "varchar:255", True),
            ("profile_picture_path", "varchar:255", True),
            ("gender", "varchar:255", True),
            ("language_1", "int", True),
            ("language_2", "int", True),
            ("language_3", "int", True),
            ("promotion_wizard_stage", "int", True),
            ("promotion_wizard_last_updated_at", "timestamp", True),
            ("external_auth_provider", "varchar:20", True),
            ("dob", "date", True),
            ("is_eu", "bool", True),
        ],
    },
    "volunteer_details.csv": {
        "pk": ["user_id"],
        "columns": [
            ("user_id", "varchar:255", False),
            ("terms_and_conditions", "bool", True),
            ("terms_accepted_at", "timestamp", True),
            ("govt_id_path1", "text", True),
            ("govt_id_path2", "text", True),
            ("path1_updated_at", "timestamp", True),
            ("path2_updated_at", "timestamp", True),
            ("availability_days", "jsonb", True),
            ("availability_times", "jsonb", True),
            ("created_at", "timestamp", True),
            ("last_updated_at", "timestamp", True),
        ],
    },
    "user_skills.csv": {
        "pk": ["user_id", "cat_id"],
        "columns": [
            ("user_id", "varchar:255", True),
            ("cat_id", "varchar:50", False),
            ("skill_level", "enum:BEGINNER,INTERMEDIATE,ADVANCED,EXPERT", True),
            ("created_at", "timestamp", True),
            ("last_updated_at", "timestamp", True),
        ],
    },
    "user_locations.csv": {
        "pk": ["user_id"],
        "columns": [
            ("user_id", "varchar:255", False),
            ("prev_loc", "geography", True),
            ("curr_loc", "geography", True),
            ("last_updated_at", "timestamp", True),
        ],
    },
    "volunteer_locations.csv": {
        "pk": ["user_id"],
        "columns": [
            ("user_id", "varchar:255", False),
            ("prev_loc", "geography", True),
            ("curr_loc", "geography", True),
            ("last_updated_at", "timestamp", True),
        ],
    },
    "organizations.csv": {
        "pk": ["org_id"],
        "columns": [
            ("org_id", "varchar:255", False),
            ("org_name", "varchar:125", False),
            ("street", "varchar:255", True),
            ("city_name", "varchar:100", True),
            ("state_id", "varchar:50", True),
            ("zip_code", "varchar:10", True),
            ("mission", "text", True),
            ("web_url", "varchar:255", True),
            ("phone", "varchar:20", True),
            ("email", "varchar:255", True),
            ("org_type", "enum:non_profit,for_profit", True),
            ("org_size", "enum:small,medium,large", True),
            ("org_rating", "int", True),
            ("is_collaborator", "bool", True),
            ("is_contributor", "bool", True),
            ("created_at", "timestamp", True),
            ("last_updated_at", "timestamp", True),
        ],
    },
}

# child file, child column, parent file, parent column
FOREIGN_KEYS = [
    ("states.csv", "country_id", "countries.csv", "country_id"),
    ("cities.csv", "state_id", "states.csv", "state_id"),
    ("users.csv", "country_id", "countries.csv", "country_id"),
    ("users.csv", "state_id", "states.csv", "state_id"),
    ("volunteer_details.csv", "user_id", "users.csv", "user_id"),
    ("user_skills.csv", "user_id", "users.csv", "user_id"),
    ("user_skills.csv", "cat_id", "help_categories.csv", "cat_id"),
    ("user_locations.csv", "user_id", "users.csv", "user_id"),
    # Not users.csv: the FK targets volunteer_details.
    ("volunteer_locations.csv", "user_id", "volunteer_details.csv", "user_id"),
    ("organizations.csv", "state_id", "states.csv", "state_id"),
]

# created_at/earlier column must be <= later column, where both are present.
TIMESTAMP_ORDER = [
    ("volunteer_details.csv", "created_at", "last_updated_at"),
    ("volunteer_details.csv", "created_at", "terms_accepted_at"),
    ("volunteer_details.csv", "created_at", "path1_updated_at"),
    ("volunteer_details.csv", "created_at", "path2_updated_at"),
    ("user_skills.csv", "created_at", "last_updated_at"),
    ("organizations.csv", "created_at", "last_updated_at"),
]


class Report:
    def __init__(self):
        self.failures = []
        self.checks = 0

    def check(self, name, ok, detail=""):
        self.checks += 1
        if ok:
            print(f"  PASS  {name}")
        else:
            print(f"  FAIL  {name}{(' -- ' + detail) if detail else ''}")
            self.failures.append(name)


def load(filename):
    with open(config.OUTPUT_DIR / filename, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def value_ok(value, kind):
    """An empty field is NULL; nullability is checked separately."""
    if value == "":
        return True
    if kind == "int":
        return re.fullmatch(r"-?\d+", value) is not None
    if kind == "decimal":
        return re.fullmatch(r"-?\d+(\.\d+)?", value) is not None
    if kind == "bool":
        return value in ("true", "false")
    if kind == "timestamp":
        try:
            datetime.strptime(value, TIMESTAMP)
            return True
        except ValueError:
            return False
    if kind == "date":
        try:
            datetime.strptime(value, DATE)
            return True
        except ValueError:
            return False
    if kind == "point":
        return POINT_RE.fullmatch(value) is not None
    if kind == "geography":
        return EWKT_RE.fullmatch(value) is not None
    if kind == "jsonb":
        try:
            json.loads(value)
            return True
        except ValueError:
            return False
    if kind.startswith("varchar:"):
        return len(value) <= int(kind.split(":")[1])
    if kind.startswith("enum:"):
        return value in kind.split(":")[1].split(",")
    return True


def main() -> int:
    report = Report()
    data = {name: load(name) for name in SCHEMA}

    print("\n== Headers, types, required fields, primary keys ==")
    for filename, spec in SCHEMA.items():
        rows = data[filename]
        expected = [column for column, _, _ in spec["columns"]]
        actual = list(rows[0].keys()) if rows else []
        report.check(
            f"{filename}: header matches schema (name and order)",
            actual == expected,
            f"expected {expected}, got {actual}",
        )

        bad_type = []
        bad_null = []
        for index, row in enumerate(rows, start=2):
            for column, kind, nullable in spec["columns"]:
                value = row.get(column, "")
                if not nullable and value == "":
                    bad_null.append(f"line {index} {column}")
                if not value_ok(value, kind):
                    bad_type.append(f"line {index} {column}={value!r}")
        report.check(
            f"{filename}: values match declared data types",
            not bad_type,
            "; ".join(bad_type[:3]),
        )
        report.check(
            f"{filename}: required (NOT NULL) fields populated",
            not bad_null,
            "; ".join(bad_null[:3]),
        )

        keys = [tuple(row[c] for c in spec["pk"]) for row in rows]
        report.check(
            f"{filename}: primary key {tuple(spec['pk'])} is unique",
            len(keys) == len(set(keys)),
            f"{len(keys) - len(set(keys))} duplicates",
        )

    print("\n== Foreign keys (no orphan references) ==")
    for child, child_col, parent, parent_col in FOREIGN_KEYS:
        parent_values = {row[parent_col] for row in data[parent]}
        orphans = sorted(
            {
                row[child_col]
                for row in data[child]
                if row[child_col] != "" and row[child_col] not in parent_values
            }
        )
        report.check(
            f"{child}.{child_col} -> {parent}.{parent_col}",
            not orphans,
            f"{len(orphans)} orphans e.g. {orphans[:3]}",
        )

    print("\n== Forward-looking orphan checks (issue #301) ==")
    # No table in scope currently carries a city_id or org_id foreign key.
    city_fk = [
        (f, c)
        for f, spec in SCHEMA.items()
        for c, _, _ in spec["columns"]
        if c == "city_id" and f != "cities.csv"
    ]
    org_fk = [
        (f, c)
        for f, spec in SCHEMA.items()
        for c, _, _ in spec["columns"]
        if c == "org_id" and f != "organizations.csv"
    ]
    report.check("no orphan city_id values (no city_id FK in scope)", not city_fk)
    report.check("no orphan org_id values (no org_id FK in scope)", not org_fk)

    print("\n== Geographic consistency ==")
    state_country = {r["state_id"]: r["country_id"] for r in data["states.csv"]}
    city_state = {}
    city_coords = {}
    for row in data["cities.csv"]:
        city_state.setdefault(row["city_name"], set()).add(row["state_id"])
        city_coords.setdefault((row["city_name"], row["state_id"]), (
            float(row["lattitude"]), float(row["longitude"])
        ))

    mismatched = [
        row["user_id"]
        for row in data["users.csv"]
        if state_country.get(row["state_id"]) != row["country_id"]
    ]
    report.check(
        "users: state_id belongs to the user's country_id",
        not mismatched,
        f"{len(mismatched)} rows",
    )

    wrong_city = [
        row["user_id"]
        for row in data["users.csv"]
        if row["state_id"] not in city_state.get(row["city_name"], set())
    ]
    report.check(
        "users: city_name belongs to the user's state",
        not wrong_city,
        f"{len(wrong_city)} rows",
    )

    wrong_org_city = [
        row["org_id"]
        for row in data["organizations.csv"]
        if row["state_id"] not in city_state.get(row["city_name"], set())
    ]
    report.check(
        "organizations: city_name belongs to the organization's state",
        not wrong_org_city,
        f"{len(wrong_org_city)} rows",
    )

    # Coordinates must sit near the city the user was placed in.
    user_city = {
        row["user_id"]: (row["city_name"], row["state_id"]) for row in data["users.csv"]
    }
    volunteer_ids = {row["user_id"] for row in data["volunteer_details.csv"]}

    def coordinate_drift(filename, restrict=None):
        far = []
        for row in data[filename]:
            key = user_city.get(row["user_id"])
            if key is None or (restrict and row["user_id"] not in restrict):
                continue
            city_lat, city_lon = city_coords[key]
            for column in ("curr_loc", "prev_loc"):
                match = EWKT_RE.fullmatch(row[column])
                if not match:
                    continue
                lon, lat = row[column][len("SRID=4326;POINT("):-1].split(" ")
                if abs(float(lat) - city_lat) > 0.5 or abs(float(lon) - city_lon) > 1.0:
                    far.append(f"{row['user_id']}.{column}")
        return far

    report.check(
        "user_locations: coordinates lie within the user's city",
        not coordinate_drift("user_locations.csv"),
    )
    report.check(
        "volunteer_locations: coordinates lie within the volunteer's city",
        not coordinate_drift("volunteer_locations.csv", volunteer_ids),
    )

    # users.last_location must also match the user's own city.
    far_users = []
    for row in data["users.csv"]:
        match = POINT_RE.fullmatch(row["last_location"])
        if not match:
            continue
        lat, lon = row["last_location"][1:-1].split(",")
        city_lat, city_lon = city_coords[(row["city_name"], row["state_id"])]
        if abs(float(lat) - city_lat) > 0.5 or abs(float(lon) - city_lon) > 1.0:
            far_users.append(row["user_id"])
    report.check(
        "users: last_location lies within the user's city", not far_users,
        f"{len(far_users)} rows",
    )

    print("\n== Timestamp ordering ==")
    for filename, earlier, later in TIMESTAMP_ORDER:
        bad = []
        for row in data[filename]:
            a, b = row[earlier], row[later]
            if a == "" or b == "":
                continue
            if datetime.strptime(a, TIMESTAMP) > datetime.strptime(b, TIMESTAMP):
                bad.append(row[SCHEMA[filename]["pk"][0]])
        report.check(
            f"{filename}: {earlier} <= {later}", not bad, f"{len(bad)} rows"
        )

    print("\n== Schema CHECK constraints ==")
    bad_url = [
        r["org_id"] for r in data["organizations.csv"]
        if r["web_url"] and not r["web_url"].startswith("http")
    ]
    report.check("organizations: web_url LIKE 'http%'", not bad_url)
    bad_email = [
        r["org_id"] for r in data["organizations.csv"]
        if r["email"] and "@" not in r["email"]
    ]
    report.check("organizations: email LIKE '%@%'", not bad_email)
    bad_rating = [
        r["org_id"] for r in data["organizations.csv"]
        if r["org_rating"] and not 1 <= int(r["org_rating"]) <= 5
    ]
    report.check("organizations: org_rating BETWEEN 1 AND 5", not bad_rating)

    print("\n== No real or sensitive data ==")
    bad_domain = [
        r["user_id"] for r in data["users.csv"]
        if not r["primary_email_address"].endswith(
            ("@example.com", "@example.org", "@example.net")
        )
    ]
    report.check(
        "users: e-mail uses an RFC 2606 reserved domain", not bad_domain,
        f"{len(bad_domain)} rows",
    )
    phone_re = re.compile(r"^\+\d{1,5}-555-01\d{2}$")
    bad_phone = [
        r["user_id"]
        for r in data["users.csv"]
        if not phone_re.fullmatch(r["primary_phone_number"])
    ]
    report.check(
        "users: phone is inside the 555-0100..0199 reserved block", not bad_phone,
        f"{len(bad_phone)} rows",
    )
    bad_org_phone = [
        r["org_id"]
        for r in data["organizations.csv"]
        if not phone_re.fullmatch(r["phone"])
    ]
    report.check(
        "organizations: phone is inside the reserved block", not bad_org_phone,
        f"{len(bad_org_phone)} rows",
    )
    bad_org_domain = [
        r["org_id"] for r in data["organizations.csv"]
        if not r["email"].endswith(".example.org")
        or not r["web_url"].endswith(".example.org")
    ]
    report.check(
        "organizations: e-mail and web_url use a reserved domain", not bad_org_domain,
        f"{len(bad_org_domain)} rows",
    )

    print(f"\n{report.checks - len(report.failures)}/{report.checks} checks passed")
    if report.failures:
        print("FAILED:")
        for failure in report.failures:
            print(f"  - {failure}")
        return 1
    print("All data-quality checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
