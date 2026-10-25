#!/usr/bin/env python3
"""Validate the generated fixture contract against the 2026-09-08 schema snapshot."""

import argparse
import csv
import json
import math
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from geography import SEEDED_CITIES
from schema import BASE, DEFAULT_LOOKUP, SCHEMA

KEYS = {
    "countries": "country_id",
    "states": "state_id",
    "cities": "city_id",
    "users": "user_id",
    "volunteer_details": "user_id",
    "help_categories": "cat_id",
    "organizations": "org_id",
    "user_locations": "user_id",
    "volunteer_locations": "user_id",
}
FKS = [
    ("states", "country_id", "countries", "country_id"),
    ("cities", "state_id", "states", "state_id"),
    ("users", "state_id", "states", "state_id"),
    ("users", "country_id", "countries", "country_id"),
    ("users", "user_status_id", "user_status", "user_status_id"),
    *[
        ("users", f"language_{i}", "supporting_languages", "language_id")
        for i in range(1, 4)
    ],
    ("volunteer_details", "user_id", "users", "user_id"),
    ("user_skills", "user_id", "users", "user_id"),
    ("user_skills", "cat_id", "help_categories", "cat_id"),
    ("organizations", "state_id", "states", "state_id"),
    ("user_locations", "user_id", "users", "user_id"),
    ("volunteer_locations", "user_id", "volunteer_details", "user_id"),
]
ENUMS = {
    "skill_level": {"BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"},
    "org_type": {"non_profit", "for_profit"},
    "org_size": {"small", "medium", "large"},
}


def read_csv_data(path: str | Path) -> tuple[list[str] | None, list[dict]]:
    """Read UTF-8 CSV headers and rows without coercing empty cells."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def parse_point_wkt(value: str) -> tuple[float, float]:
    """Parse a WGS84 POINT and return bounded (longitude, latitude)."""
    match = re.fullmatch(r"POINT\(\s*([-+\d.eE]+)\s+([-+\d.eE]+)\s*\)", value)
    if not match:
        raise ValueError("expected POINT(longitude latitude)")
    lon, lat = map(float, match.groups())
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("coordinates out of bounds")
    return lon, lat


def native_point(value: str) -> tuple[float, float]:
    """Convert the schema's native (latitude, longitude) point to lon/lat."""
    match = re.fullmatch(r"\(\s*([-+\d.eE]+),\s*([-+\d.eE]+)\s*\)", value)
    if not match:
        raise ValueError("expected native (latitude, longitude) point")
    lat, lon = map(float, match.groups())
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("coordinates out of bounds")
    return lon, lat


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Return the great-circle distance in kilometers between lon/lat points."""
    lon1, lat1, lon2, lat2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def canonical_id(table: str, column: str, value: str) -> str:
    """Normalize numeric keys as PostgreSQL does for uniqueness and FK checks."""
    spec = SCHEMA.get(table + ".csv", {}).get(column, {})
    if spec.get("type", "").upper() in (
        "INT",
        "INTEGER",
        "BIGINT",
        "SERIAL",
    ) or table in ("supporting_languages", "user_status"):
        try:
            return str(int(value))
        except ValueError:
            pass
    return value


def load_dataset(data_dir: Path, lookup_dir: Path, errors: list[str]) -> dict:
    """Read fixtures and prerequisite lookups, rejecting malformed CSV rows."""
    data = {}
    for filename, columns in SCHEMA.items():
        try:
            headers, rows = read_csv_data(Path(data_dir) / filename)
            if headers != list(columns):
                raise ValueError("headers do not match schema column order")
            # Zero-sized optional subsets still require a valid header-only CSV.
            optional = {
                "volunteer_details.csv",
                "volunteer_locations.csv",
                "user_locations.csv",
            }
            if not rows and filename not in optional:
                raise ValueError("fixture table is empty")
            if any(None in r or any(v is None for v in r.values()) for r in rows):
                raise ValueError("row has missing or extra CSV fields")
            data[filename[:-4]] = rows
        except (OSError, ValueError, csv.Error) as e:
            errors.append(f"{filename}: {e}")
    for table in ("supporting_languages", "user_status"):
        try:
            _, data[table] = read_csv_data(Path(lookup_dir) / (table + ".csv"))
            key = "language_id" if table == "supporting_languages" else "user_status_id"
            ids = [r[key] for r in data[table]]
            if (
                not ids
                or len(ids) != len(set(ids))
                or any(not x or int(x) <= 0 for x in ids)
            ):
                raise ValueError("lookup must contain unique positive IDs")
        except (OSError, KeyError, ValueError, TypeError) as e:
            errors.append(f"{table} lookup: {e}")
    return data


def validate_rows(data: dict, errors: list[str]) -> None:
    """Check primary keys, schema field values, and timestamp ordering."""
    for filename, columns in SCHEMA.items():
        table = filename[:-4]
        seen = set()
        for n, row in enumerate(data[table], 2):
            label = f"{filename}:{n}"
            pk = (
                tuple(row[k] for k in ("user_id", "cat_id"))
                if table == "user_skills"
                else (row[KEYS[table]],)
            )
            if not all(pk) or pk in seen:
                errors.append(f"{label}: empty or duplicate primary key {pk}")
            normalized = tuple(
                canonical_id(table, k, row[k])
                for k in (
                    ("user_id", "cat_id") if table == "user_skills" else (KEYS[table],)
                )
            )
            if normalized != pk and normalized in seen:
                errors.append(
                    f"{label}: duplicate primary key after SQL integer conversion"
                )
            seen.add(normalized)
            seen.add(pk)
            for col, spec in columns.items():
                value = row[col]
                try:
                    if not value:
                        if spec["required"]:
                            raise ValueError("required field is empty")
                        continue
                    if spec["length"] and len(value) > spec["length"]:
                        raise ValueError("exceeds VARCHAR length")
                    kind = spec["type"].upper()
                    if kind in ("INT", "INTEGER", "SERIAL", "BIGINT"):
                        number = int(value)
                        bits = 64 if kind == "BIGINT" else 32
                        if not -(2 ** (bits - 1)) <= number < 2 ** (bits - 1):
                            raise ValueError("integer overflow")
                    elif kind == "BOOLEAN" and value.lower() not in (
                        "true",
                        "false",
                        "t",
                        "f",
                        "1",
                        "0",
                    ):
                        raise ValueError("invalid boolean")
                    elif kind.startswith("TIMESTAMP"):
                        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
                    elif kind == "DATE":
                        datetime.strptime(value, "%Y-%m-%d")
                    elif kind == "JSONB":
                        parsed = json.loads(value)
                        if not isinstance(parsed, list) or not all(
                            isinstance(x, str) for x in parsed
                        ):
                            raise ValueError(
                                "availability must be a JSON array of strings"
                            )
                    elif kind.startswith("DECIMAL"):
                        number = Decimal(value)
                        if (
                            not number.is_finite()
                            or abs(number) >= 1000
                            or number.as_tuple().exponent < -6
                        ):
                            raise ValueError("invalid DECIMAL(9,6)")
                    elif kind.startswith("GEOGRAPHY"):
                        parse_point_wkt(value)
                    elif kind == "POINT":
                        native_point(value)
                    if col in ENUMS and value not in ENUMS[col]:
                        raise ValueError("invalid enum")
                    if col == "org_rating" and not 1 <= int(value) <= 5:
                        raise ValueError("rating outside 1..5")
                    if col == "org_id" and not re.fullmatch(
                        r"ORG-\d{3}-\d{3}-\d{3}-\d{4}", value
                    ):
                        raise ValueError("invalid organization ID format")
                    if col == "user_id" and not re.fullmatch(
                        r"SID-00-(?:\d{3}-){4}\d{3}", value
                    ):
                        raise ValueError("invalid user ID format")
                    if col in ("email", "primary_email_address") and not re.fullmatch(
                        r"[^@\s]+@example\.(com|org|net)", value
                    ):
                        raise ValueError("use a reserved example email domain")
                    if col in (
                        "web_url",
                        "profile_picture_path",
                        "govt_id_path1",
                        "govt_id_path2",
                    ):
                        url = urlparse(value)
                        if url.scheme not in ("http", "https") or url.hostname not in (
                            "example.com",
                            "example.org",
                            "example.net",
                        ):
                            raise ValueError(
                                "use an HTTP(S) URL on a reserved example domain"
                            )
                    if col in ("phone", "primary_phone_number"):
                        raise ValueError(
                            "phone fields must be empty in these international fixtures"
                        )
                except (ValueError, ArithmeticError) as e:
                    errors.append(f"{label} {col}: {e}")
            try:
                updated = (
                    datetime.strptime(row["last_updated_at"], "%Y-%m-%d %H:%M:%S")
                    if row["last_updated_at"]
                    else None
                )
                for col in (
                    "created_at",
                    "terms_accepted_at",
                    "path1_updated_at",
                    "path2_updated_at",
                    "promotion_wizard_last_updated_at",
                ):
                    if (
                        row.get(col)
                        and updated
                        and datetime.strptime(row[col], "%Y-%m-%d %H:%M:%S") > updated
                    ):
                        errors.append(f"{label}: {col} is after last_updated_at")
            except ValueError:
                pass  # Field validation already reports malformed timestamps.


def validate_foreign_keys(data: dict, errors: list[str]) -> None:
    """Check all scoped relationships and external language/status references."""
    for child, key, parent, target in FKS:
        valid = {canonical_id(parent, target, r[target]) for r in data[parent]}
        for n, row in enumerate(data[child], 2):
            if row[key] and canonical_id(parent, target, row[key]) not in valid:
                errors.append(f"{child}.csv:{n}: orphan {key}={row[key]}")


def validate_geography(data: dict, errors: list[str]) -> None:
    """Check fixture relationships and distances to curated city anchors."""
    # Check curated anchors as well as relationships between CSV files.
    anchors = {(c["state_id"], c["city_name"]): c for c in SEEDED_CITIES}
    states = {r["state_id"]: r for r in data["states"]}
    countries = {r["country_id"]: r for r in data["countries"]}
    cities = {(r["state_id"], r["city_name"]): r for r in data["cities"]}
    if len(cities) != len(data["cities"]):
        errors.append("cities.csv: duplicate state/city lookup entries")
    users = {r["user_id"]: r for r in data["users"]}
    for table in (
        "cities",
        "users",
        "organizations",
        "user_locations",
        "volunteer_locations",
    ):
        for n, row in enumerate(data[table], 2):
            try:
                owner = users[row["user_id"]] if table.endswith("_locations") else row
                city = (
                    row
                    if table == "cities"
                    else cities[(owner["state_id"], owner["city_name"])]
                )
                anchor = anchors[(city["state_id"], city["city_name"])]
                state = states[city["state_id"]]
                if (
                    state["state_code"] != anchor["state_code"]
                    or state["country_id"] != anchor["state_id"].split(".")[0]
                ):
                    raise ValueError(
                        "state/country lookup conflicts with curated city anchor"
                    )
                centroid = (float(city["longitude"]), float(city["lattitude"]))
                if distance(centroid, (anchor["lon"], anchor["lat"])) > 0.1:
                    raise ValueError("city centroid differs from its state/city anchor")
                if table == "users":
                    if row["country_id"] != states[row["state_id"]]["country_id"]:
                        raise ValueError("country does not match state")
                    if (
                        row["is_eu"].lower()
                        != countries[row["country_id"]]["is_eu_member"].lower()
                    ):
                        raise ValueError("EU membership does not match country")
                    if row["time_zone"] != anchor["tz"]:
                        raise ValueError("time zone does not match city")
                    if (
                        row["last_location"]
                        and distance(native_point(row["last_location"]), centroid) > 9
                    ):
                        raise ValueError("last_location is too far from city")
                if (
                    table in ("users", "organizations")
                    and row["zip_code"] != anchor["zip"]
                ):
                    raise ValueError("ZIP does not match city anchor")
                if table.endswith("_locations"):
                    for col in ("prev_loc", "curr_loc"):
                        if (
                            row[col]
                            and distance(parse_point_wkt(row[col]), centroid) > 12
                        ):
                            raise ValueError(f"{col} is too far from user city")
            except (KeyError, ValueError) as e:
                errors.append(f"{table}.csv:{n}: geographic mismatch: {e}")


def validate_dataset(
    data_dir: str | Path, lookup_dir: str | Path = DEFAULT_LOOKUP
) -> bool:
    """Run every validation pass and print a bounded, actionable error report."""
    errors: list[str] = []
    data = load_dataset(Path(data_dir), Path(lookup_dir), errors)
    if not errors:
        validate_rows(data, errors)
        validate_foreign_keys(data, errors)
        validate_geography(data, errors)
    if errors:
        print(f"FAIL: {len(errors)} errors\n" + "\n".join(errors[:30]))
        return False
    print(
        "PASS: all 10 CSVs passed schema, key, lookup, date, "
        "contact and geography checks."
    )
    return True


def main() -> None:
    """Validate a dataset directory and exit nonzero when checks fail."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=BASE)
    parser.add_argument("--lookup-dir", type=Path, default=DEFAULT_LOOKUP)
    args = parser.parse_args()
    raise SystemExit(0 if validate_dataset(args.data_dir, args.lookup_dir) else 1)


if __name__ == "__main__":
    main()
