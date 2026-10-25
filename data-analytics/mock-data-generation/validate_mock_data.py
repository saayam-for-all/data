#!/usr/bin/env python3
"""Validate the mock-data CSVs against the Virginia schema (schema.py).

Checks, per table:
  * header equals the schema's column names and order
  * every cell parses as its column type; NOT NULL columns are filled; varchar
    lengths, enum values, JSON and CHECK constraints hold
  * primary keys are unique and every foreign key resolves (no orphans)
  * created_at <= last_updated_at and related timestamps are ordered
  * country -> state -> city -> ZIP -> time zone -> coordinates are consistent
  * nothing looks like real data (reserved example.* domains, fictional phones,
    mock user IDs)

    python validate_mock_data.py [--dir PATH]

Exits 0 when every check passes, 1 otherwise. Standard library only.
"""

import argparse
import csv
import json
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import pools
import schema
from utils import DATE_FORMAT, TS_FORMAT, haversine_km, parse_ewkt_point, parse_pg_point, read_reference_csv

HERE = Path(__file__).resolve().parent
Row = Dict[str, Optional[str]]

MAX_CITY_DISTANCE_KM = 16.0  # generator clips location jitter at 15 km
LANGUAGE_IDS = set(range(1, 13))  # supporting_languages.language_id 1..12
POSTAL_PATTERNS = {
    "USA": r"\d{5}", "IND": r"\d{6}", "DEU": r"\d{5}", "AUS": r"\d{4}",
    "CAN": r"[A-Z]\d[A-Z] \d[A-Z]\d",
}
INT_LIMITS = {"int": 2**31, "bigint": 2**63}
MAX_ERRORS_SHOWN = 8


class Report:
    def __init__(self) -> None:
        self.errors: Dict[str, List[str]] = {}
        self.checked: Dict[str, int] = {}

    def fail(self, table: str, message: str) -> None:
        self.errors.setdefault(table, []).append(message)

    def ok(self) -> bool:
        return not self.errors


# --- cell-level type checks --------------------------------------------------------------
def check_cell(column: schema.Column, value: Optional[str]) -> Optional[str]:
    """Return an error string, or None if the value is valid for the column."""
    if value is None:
        return None if column.nullable else "NULL in NOT NULL column"
    t = column.type
    try:
        if t.startswith("varchar("):
            limit = int(t[8:-1])
            return None if len(value) <= limit else f"length {len(value)} > {limit}"
        if t == "text":
            return None
        if t in ("int", "bigint", "serial"):
            n = int(value)
            if t == "serial" and n < 1:
                return "serial must be >= 1"
            lim = INT_LIMITS.get(t, 2**31)
            return None if -lim <= n < lim else "integer out of range"
        if t == "bool":
            return None if value in ("true", "false") else f"boolean must be true/false, got {value!r}"
        if t == "timestamp":
            datetime.strptime(value, TS_FORMAT)
            return None
        if t == "date":
            datetime.strptime(value, DATE_FORMAT)
            return None
        if t.startswith("decimal("):
            precision, scale = (int(x) for x in t[8:-1].split(","))
            d = Decimal(value)
            if not d.is_finite():
                return "non-finite decimal"
            digits = d.as_tuple()
            frac = max(0, -digits.exponent)
            whole = len(digits.digits) - frac if len(digits.digits) > frac else 0
            if frac > scale or whole > precision - scale:
                return f"{value} does not fit decimal({precision},{scale})"
            return None
        if t == "point":
            p = parse_pg_point(value)
            return None if p and abs(p[0]) <= 90 and abs(p[1]) <= 180 else f"bad point {value!r}"
        if t == "geography_point":
            p = parse_ewkt_point(value)
            return None if p and abs(p[0]) <= 90 and abs(p[1]) <= 180 else f"bad geography point {value!r}"
        if t == "jsonb":
            json.loads(value)
            return None
        if t.startswith("enum:"):
            allowed = schema.ENUMS[t[5:]]
            return None if value in allowed else f"{value!r} not in enum {t[5:]}"
    except (ValueError, InvalidOperation) as exc:
        return f"invalid {t}: {value!r} ({exc})"
    return f"unhandled type {t}"


# --- loading ----------------------------------------------------------------------------------
def load_tables(directory: Path, report: Report) -> Dict[str, List[Row]]:
    tables: Dict[str, List[Row]] = {}
    for name, table in schema.TABLES.items():
        path = directory / f"{name}.csv"
        if not path.exists():
            report.fail(name, f"{path.name} is missing")
            continue
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header != table.column_names:
                report.fail(name, f"header mismatch:\n      got      {header}\n      expected {table.column_names}")
                continue
            rows: List[Row] = []
            for lineno, cells in enumerate(reader, start=2):
                if len(cells) != len(header):
                    report.fail(name, f"line {lineno}: {len(cells)} cells, expected {len(header)}")
                    continue
                rows.append({h: (c if c != "" else None) for h, c in zip(header, cells)})
        tables[name] = rows
    return tables


# --- structural checks ---------------------------------------------------------------------------
def check_types(table: schema.Table, rows: List[Row], report: Report) -> None:
    for n, row in enumerate(rows, start=2):
        for col in table.columns:
            problem = check_cell(col, row[col.name])
            if problem:
                report.fail(table.name, f"line {n}, {col.name}: {problem}")


def check_keys(tables: Dict[str, List[Row]], report: Report) -> None:
    for name, table in schema.TABLES.items():
        rows = tables.get(name)
        if rows is None:
            continue
        seen: Set[Tuple] = set()
        for n, row in enumerate(rows, start=2):
            key = tuple(row[c] for c in table.primary_key)
            if key in seen:
                report.fail(name, f"line {n}: duplicate primary key {key}")
            seen.add(key)
        for fk in table.foreign_keys:
            parent = tables.get(fk.ref_table)
            if parent is None:
                continue
            parent_values = {r[fk.ref_column] for r in parent}
            for n, row in enumerate(rows, start=2):
                v = row[fk.column]
                if v is not None and v not in parent_values:
                    report.fail(name, f"line {n}: orphan {fk.column}={v!r} "
                                      f"(no {fk.ref_table}.{fk.ref_column})")


# --- semantic checks -------------------------------------------------------------------------------
class Geo:
    """Lookup structures for the geography consistency checks."""

    def __init__(self, tables: Dict[str, List[Row]], reference_dir: Path, report: Report) -> None:
        self.country_by_id = {r["country_id"]: r for r in tables["countries"]}
        self.state_by_id = {r["state_id"]: r for r in tables["states"]}
        ref = {(r["country_code"], r["state_code"], r["city_name"]): r
               for r in read_reference_csv(reference_dir / "cities.csv")}
        self.city: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.cities_in_state: Dict[str, List[Dict[str, Any]]] = {}
        for r in tables["cities"]:
            state = self.state_by_id.get(r["state_id"])
            country = self.country_by_id.get(state["country_id"]) if state else None
            if not (state and country):
                continue  # already reported as an orphan FK
            key = (country["country_code"], state["state_code"], r["city_name"])
            seed = ref.get(key)
            if seed is None:
                report.fail("cities", f"{r['city_name']!r} ({state['state_name']}) is not in reference_data/cities.csv")
                continue
            info = {"name": r["city_name"], "state_id": r["state_id"], "country_code": country["country_code"],
                    "lat": float(r["lattitude"]), "lon": float(r["longitude"]),
                    "zip_prefix": seed["zip_prefix"], "time_zone": seed["time_zone"]}
            if (r["state_id"], r["city_name"]) in self.city:
                report.fail("cities", f"duplicate city {r['city_name']!r} in state {r['state_id']}")
            self.city[(r["state_id"], r["city_name"])] = info
            self.cities_in_state.setdefault(r["state_id"], []).append(info)

    def near_city(self, point: Tuple[float, float], city: Dict[str, Any]) -> bool:
        return haversine_km(point[0], point[1], city["lat"], city["lon"]) <= MAX_CITY_DISTANCE_KM

    def near_state(self, point: Tuple[float, float], state_id: Optional[str]) -> bool:
        return any(self.near_city(point, c) for c in self.cities_in_state.get(state_id, []))


def ts(value: Optional[str]) -> Optional[datetime]:
    return datetime.strptime(value, TS_FORMAT) if value else None


def check_postal(report: Report, table: str, n: int, country_code: str, city: Dict[str, Any], zip_code: Optional[str]) -> None:
    if zip_code is None:
        return
    if not re.fullmatch(POSTAL_PATTERNS[country_code], zip_code):
        report.fail(table, f"line {n}: zip_code {zip_code!r} is not a valid {country_code} postal code")
    elif not zip_code.startswith(city["zip_prefix"]):
        report.fail(table, f"line {n}: zip_code {zip_code!r} does not match {city['name']} (prefix {city['zip_prefix']})")


def check_geography(tables: Dict[str, List[Row]], geo: Geo, report: Report) -> Dict[str, Dict[str, Any]]:
    """Users, organizations and the two location tables. Returns user_id -> city."""
    for n, r in enumerate(tables["states"], start=2):
        if r["country_id"] not in geo.country_by_id:
            report.fail("states", f"line {n}: unknown country_id {r['country_id']}")

    user_city: Dict[str, Dict[str, Any]] = {}
    for n, u in enumerate(tables["users"], start=2):
        country = geo.country_by_id.get(u["country_id"]) if u["country_id"] else None
        if u["state_id"] and country:
            state = geo.state_by_id.get(u["state_id"])
            if state and state["country_id"] != u["country_id"]:
                report.fail("users", f"line {n}: state {u['state_id']} does not belong to country {u['country_id']}")
        if country and (u["is_eu"] == "true") != (country["is_eu_member"] == "true"):
            report.fail("users", f"line {n}: is_eu={u['is_eu']} disagrees with countries.is_eu_member")

        if u["city_name"]:
            city = geo.city.get((u["state_id"], u["city_name"])) if u["state_id"] else None
            if city is None:
                report.fail("users", f"line {n}: city {u['city_name']!r} is not a city of state {u['state_id']}")
            else:
                user_city[u["user_id"]] = city
                check_postal(report, "users", n, city["country_code"], city, u["zip_code"])
                if u["time_zone"] != city["time_zone"]:
                    report.fail("users", f"line {n}: time_zone {u['time_zone']} != {city['time_zone']} for {city['name']}")
        elif u["zip_code"] or u["addr_ln1"]:
            report.fail("users", f"line {n}: address/zip present without a city")

        for lang in (u["language_1"], u["language_2"], u["language_3"]):
            if lang is not None and int(lang) not in LANGUAGE_IDS:
                report.fail("users", f"line {n}: language id {lang} not in supporting_languages 1..12")
        if u["language_1"] is None and (u["language_2"] or u["language_3"]):
            report.fail("users", f"line {n}: language_2/3 set without language_1")
        if u["user_status_id"] != "1":
            report.fail("users", f"line {n}: user_status_id {u['user_status_id']} is not the ACTIVE lookup value (1)")
        if u["promotion_wizard_last_updated_at"] and ts(u["promotion_wizard_last_updated_at"]) > ts(u["last_updated_at"]):
            report.fail("users", f"line {n}: promotion_wizard_last_updated_at is after last_updated_at")

        if u["last_location"]:
            point = parse_pg_point(u["last_location"])
            city = user_city.get(u["user_id"])
            if city is None or not geo.near_city(point, city):
                report.fail("users", f"line {n}: last_location {u['last_location']} is not near the user's city")

    for n, o in enumerate(tables["organizations"], start=2):
        if o["state_id"] is None:
            continue
        state = geo.state_by_id.get(o["state_id"])
        city = geo.city.get((o["state_id"], o["city_name"])) if o["city_name"] else None
        if o["city_name"] and city is None:
            report.fail("organizations", f"line {n}: city {o['city_name']!r} is not a city of state {o['state_id']}")
        elif city:
            check_postal(report, "organizations", n, city["country_code"], city, o["zip_code"])

    def check_locations(name: str, created: Dict[str, datetime]) -> None:
        for n, r in enumerate(tables[name], start=2):
            city = user_city.get(r["user_id"])
            if city is None:
                report.fail(name, f"line {n}: user {r['user_id']} has no city to anchor the coordinates")
                continue
            curr = parse_ewkt_point(r["curr_loc"]) if r["curr_loc"] else None
            prev = parse_ewkt_point(r["prev_loc"]) if r["prev_loc"] else None
            if curr and not geo.near_city(curr, city):
                report.fail(name, f"line {n}: curr_loc is >{MAX_CITY_DISTANCE_KM:.0f} km from {city['name']}")
            if prev and not geo.near_state(prev, city["state_id"]):
                report.fail(name, f"line {n}: prev_loc is not near any city of the user's state")
            floor = created.get(r["user_id"])
            if floor and ts(r["last_updated_at"]) < floor:
                report.fail(name, f"line {n}: last_updated_at is before the volunteer's created_at")

    volunteer_created = {r["user_id"]: ts(r["created_at"]) for r in tables["volunteer_details"]}
    check_locations("user_locations", {})
    check_locations("volunteer_locations", volunteer_created)

    # users.last_location mirrors user_locations.curr_loc
    curr_by_user = {r["user_id"]: parse_ewkt_point(r["curr_loc"]) for r in tables["user_locations"] if r["curr_loc"]}
    for n, u in enumerate(tables["users"], start=2):
        expected = curr_by_user.get(u["user_id"])
        actual = parse_pg_point(u["last_location"]) if u["last_location"] else None
        if expected and (actual is None or haversine_km(*expected, *actual) > 0.01):
            report.fail("users", f"line {n}: last_location differs from user_locations.curr_loc")
    return user_city


def check_timestamps(tables: Dict[str, List[Row]], report: Report) -> None:
    def ordered(table: str, n: int, earlier: str, later: str, row: Row) -> None:
        if row[earlier] and row[later] and ts(row[earlier]) > ts(row[later]):
            report.fail(table, f"line {n}: {earlier} ({row[earlier]}) is after {later} ({row[later]})")

    for n, r in enumerate(tables["volunteer_details"], start=2):
        for col in ("terms_accepted_at", "path1_updated_at", "path2_updated_at"):
            ordered("volunteer_details", n, "created_at", col, r)
            ordered("volunteer_details", n, col, "last_updated_at", r)
        ordered("volunteer_details", n, "created_at", "last_updated_at", r)
        for path, updated in (("govt_id_path1", "path1_updated_at"), ("govt_id_path2", "path2_updated_at")):
            if (r[path] is None) != (r[updated] is None):
                report.fail("volunteer_details", f"line {n}: {path} and {updated} must both be set or both NULL")
        if (r["terms_and_conditions"] == "true") != (r["terms_accepted_at"] is not None):
            report.fail("volunteer_details", f"line {n}: terms_accepted_at must be set exactly when terms_and_conditions is true")
        for col, allowed in (("availability_days", pools.DAYS), ("availability_times", pools.TIME_SLOTS)):
            if r[col]:
                values = json.loads(r[col])
                if not isinstance(values, list) or not values or not set(values) <= set(allowed):
                    report.fail("volunteer_details", f"line {n}: {col} must be a non-empty list of known values")

    volunteer_created = {r["user_id"]: ts(r["created_at"]) for r in tables["volunteer_details"]}
    for n, r in enumerate(tables["user_skills"], start=2):
        ordered("user_skills", n, "created_at", "last_updated_at", r)
        floor = volunteer_created.get(r["user_id"])
        if floor is None:
            report.fail("user_skills", f"line {n}: user {r['user_id']} is not a volunteer")
        elif ts(r["created_at"]) < floor:
            report.fail("user_skills", f"line {n}: created_at is before the volunteer's created_at")

    for n, r in enumerate(tables["organizations"], start=2):
        ordered("organizations", n, "created_at", "last_updated_at", r)
        low, high = schema.ORG_RATING_RANGE
        if r["org_rating"] is not None and not low <= int(r["org_rating"]) <= high:
            report.fail("organizations", f"line {n}: org_rating outside {low}..{high}")
        if r["web_url"] is not None and not r["web_url"].startswith("http"):
            report.fail("organizations", f"line {n}: web_url must start with 'http'")
        if r["email"] is not None and "@" not in r["email"]:
            report.fail("organizations", f"line {n}: email must contain '@'")


def check_no_real_data(tables: Dict[str, List[Row]], report: Report) -> None:
    for n, u in enumerate(tables["users"], start=2):
        if not u["user_id"].startswith("SID-99-"):
            report.fail("users", f"line {n}: user_id {u['user_id']!r} is not a mock ID (SID-99-...)")
        if u["primary_email_address"] and not u["primary_email_address"].endswith("@example.com"):
            report.fail("users", f"line {n}: email is not on the reserved example.com domain")
        if u["primary_phone_number"] and not re.fullmatch(r"\+\d{1,4}\d{3}55501\d\d", u["primary_phone_number"]):
            report.fail("users", f"line {n}: phone is not in the fictional 555-01xx range")
    for n, o in enumerate(tables["organizations"], start=2):
        for col in ("email", "web_url"):
            if o[col] and ".example.org" not in o[col]:
                report.fail("organizations", f"line {n}: {col} is not on the reserved example.org domain")
        if o["phone"] and not re.fullmatch(r"\+\d{1,4}\d{3}55501\d\d", o["phone"]):
            report.fail("organizations", f"line {n}: phone is not in the fictional 555-01xx range")


# --- entry points ----------------------------------------------------------------------------------------
def validate_directory(directory: Path, reference_dir: Path = HERE / "reference_data") -> bool:
    """Run every check on the CSVs in `directory`, print a report, return True if clean."""
    report = Report()
    tables = load_tables(directory, report)
    for name, rows in tables.items():
        check_types(schema.TABLES[name], rows, report)
    check_keys(tables, report)

    # The semantic checks parse cells and join tables, so they only run once every
    # table loaded and passed the structural checks above.
    if not report.ok():
        report.fail("(all)", "geography / timestamp / real-data checks skipped: fix the errors above first")
    else:
        geo = Geo(tables, reference_dir, report)
        check_geography(tables, geo, report)
        check_timestamps(tables, report)
        check_no_real_data(tables, report)

    print(f"Validation of {directory}")
    for name in schema.TABLES:
        errors = report.errors.get(name, [])
        count = len(tables.get(name, []))
        print(f"  {'FAIL' if errors else 'PASS'}  {name:<20}{count:>6} rows")
        for e in errors[:MAX_ERRORS_SHOWN]:
            print(f"        - {e}")
        if len(errors) > MAX_ERRORS_SHOWN:
            print(f"        ... and {len(errors) - MAX_ERRORS_SHOWN} more")
    for e in report.errors.get("(all)", []):
        print(f"  FAIL  {e}")
    print("\nAll checks passed." if report.ok() else "\nValidation FAILED.")
    return report.ok()


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--dir", type=Path, default=HERE, help="folder containing the CSVs")
    p.add_argument("--reference-dir", type=Path, default=HERE / "reference_data")
    a = p.parse_args(argv)
    return 0 if validate_directory(a.dir, a.reference_dir) else 1


if __name__ == "__main__":
    sys.exit(main())
