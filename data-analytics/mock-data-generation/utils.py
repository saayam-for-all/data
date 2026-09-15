"""Shared helpers for the issue #301 mock data generator.

No third-party dependencies (matches the existing database/mock-data-generation
convention) - only stdlib random/csv/datetime/json/re.
"""
import csv
import json
import os
import random
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_SEED = 42
DEFAULT_COUNT = 100

# Fixed anchor so generated timestamps are deterministic under a given seed
# regardless of what day the script actually runs.
REFERENCE_NOW = datetime(2026, 9, 15, 12, 0, 0)

TABLE_FILENAMES = {
    "countries": "countries.csv",
    "states": "states.csv",
    "cities": "cities.csv",
    "users": "users.csv",
    "organizations": "organizations.csv",
    "volunteer_details": "volunteer_details.csv",
    "user_skills": "user_skills.csv",
    "volunteer_locations": "volunteer_locations.csv",
    "user_locations": "user_locations.csv",
    "help_categories": "help_categories.csv",
}

# Single-column and composite primary keys per table.
PK_SPECS: Dict[str, Tuple[str, ...]] = {
    "countries": ("country_id",),
    "states": ("state_id",),
    "cities": ("city_id",),
    "users": ("user_id",),
    "organizations": ("org_id",),
    "volunteer_details": ("user_id",),
    "user_skills": ("user_id", "cat_id"),
    "volunteer_locations": ("user_id",),
    "user_locations": ("user_id",),
    "help_categories": ("cat_id",),
}

# (child_table, child_columns, parent_table, parent_columns)
FK_SPECS: List[Tuple[str, Tuple[str, ...], str, Tuple[str, ...]]] = [
    ("states", ("country_id",), "countries", ("country_id",)),
    ("cities", ("state_id",), "states", ("state_id",)),
    ("users", ("state_id",), "states", ("state_id",)),
    ("users", ("country_id",), "countries", ("country_id",)),
    ("organizations", ("state_id",), "states", ("state_id",)),
    ("volunteer_details", ("user_id",), "users", ("user_id",)),
    ("user_skills", ("user_id",), "users", ("user_id",)),
    ("user_skills", ("cat_id",), "help_categories", ("cat_id",)),
    # Scoped to the volunteer subset, per the issue's explicit FK note -
    # not a direct FK to users.
    ("volunteer_locations", ("user_id",), "volunteer_details", ("user_id",)),
    ("user_locations", ("user_id",), "users", ("user_id",)),
]

# Loose bounding box (continental US + AK/HI) used as a geo sanity check -
# catches jitter bugs that push a point into an ocean/another continent.
US_LAT_RANGE = (18.0, 72.0)
US_LON_RANGE = (-170.0, -65.0)

# 2 well-known real cities per US state (largest city, capital), used to
# seed cities.csv with plausible coordinates rather than random ones.
SEED_CITIES: Dict[str, List[Tuple[str, float, float]]] = {
    "AL": [("Birmingham", 33.52, -86.80), ("Montgomery", 32.37, -86.30)],
    "AK": [("Anchorage", 61.22, -149.90), ("Juneau", 58.30, -134.42)],
    "AZ": [("Phoenix", 33.45, -112.07), ("Tucson", 32.22, -110.93)],
    "AR": [("Little Rock", 34.75, -92.29), ("Fayetteville", 36.06, -94.16)],
    "CA": [("Los Angeles", 34.05, -118.24), ("Sacramento", 38.58, -121.49)],
    "CO": [("Denver", 39.74, -104.99), ("Colorado Springs", 38.83, -104.82)],
    "CT": [("Bridgeport", 41.18, -73.19), ("Hartford", 41.76, -72.69)],
    "DE": [("Wilmington", 39.74, -75.55), ("Dover", 39.16, -75.52)],
    "DC": [("Washington", 38.9072, -77.0369), ("Georgetown", 38.9097, -77.0654)],
    "FL": [("Jacksonville", 30.33, -81.66), ("Miami", 25.76, -80.19)],
    "GA": [("Atlanta", 33.75, -84.39), ("Augusta", 33.47, -81.97)],
    "HI": [("Honolulu", 21.31, -157.86), ("Hilo", 19.71, -155.09)],
    "ID": [("Boise", 43.62, -116.20), ("Idaho Falls", 43.49, -112.03)],
    "IL": [("Chicago", 41.88, -87.63), ("Springfield", 39.78, -89.65)],
    "IN": [("Indianapolis", 39.77, -86.16), ("Fort Wayne", 41.08, -85.14)],
    "IA": [("Des Moines", 41.60, -93.61), ("Cedar Rapids", 41.98, -91.67)],
    "KS": [("Wichita", 37.69, -97.34), ("Topeka", 39.06, -95.68)],
    "KY": [("Louisville", 38.25, -85.76), ("Lexington", 38.04, -84.50)],
    "LA": [("New Orleans", 29.95, -90.07), ("Baton Rouge", 30.45, -91.15)],
    "ME": [("Portland", 43.66, -70.26), ("Augusta", 44.31, -69.78)],
    "MD": [("Baltimore", 39.29, -76.61), ("Annapolis", 38.98, -76.49)],
    "MA": [("Boston", 42.36, -71.06), ("Worcester", 42.26, -71.80)],
    "MI": [("Detroit", 42.33, -83.05), ("Lansing", 42.73, -84.56)],
    "MN": [("Minneapolis", 44.98, -93.27), ("Saint Paul", 44.95, -93.09)],
    "MS": [("Jackson", 32.30, -90.18), ("Gulfport", 30.37, -89.09)],
    "MO": [("Kansas City", 39.10, -94.58), ("St. Louis", 38.63, -90.20)],
    "MT": [("Billings", 45.78, -108.50), ("Helena", 46.59, -112.04)],
    "NE": [("Omaha", 41.26, -95.94), ("Lincoln", 40.81, -96.68)],
    "NV": [("Las Vegas", 36.17, -115.14), ("Reno", 39.53, -119.81)],
    "NH": [("Manchester", 42.99, -71.46), ("Concord", 43.21, -71.54)],
    "NJ": [("Newark", 40.74, -74.17), ("Trenton", 40.22, -74.76)],
    "NM": [("Albuquerque", 35.08, -106.65), ("Santa Fe", 35.69, -105.94)],
    "NY": [("New York City", 40.71, -74.01), ("Albany", 42.65, -73.75)],
    "NC": [("Charlotte", 35.23, -80.84), ("Raleigh", 35.78, -78.64)],
    "ND": [("Fargo", 46.88, -96.79), ("Bismarck", 46.81, -100.78)],
    "OH": [("Columbus", 39.96, -83.00), ("Cleveland", 41.50, -81.69)],
    "OK": [("Oklahoma City", 35.47, -97.52), ("Tulsa", 36.15, -95.99)],
    "OR": [("Portland", 45.52, -122.68), ("Salem", 44.94, -123.04)],
    "PA": [("Philadelphia", 39.95, -75.16), ("Pittsburgh", 40.44, -79.99)],
    "RI": [("Providence", 41.82, -71.41), ("Warwick", 41.70, -71.42)],
    "SC": [("Charleston", 32.78, -79.93), ("Columbia", 34.00, -81.03)],
    "SD": [("Sioux Falls", 43.55, -96.70), ("Pierre", 44.37, -100.35)],
    "TN": [("Nashville", 36.16, -86.78), ("Memphis", 35.15, -90.05)],
    "TX": [("Houston", 29.76, -95.37), ("Austin", 30.27, -97.74)],
    "UT": [("Salt Lake City", 40.76, -111.89), ("Provo", 40.23, -111.66)],
    "VT": [("Burlington", 44.48, -73.21), ("Montpelier", 44.26, -72.58)],
    "VA": [("Virginia Beach", 36.85, -75.98), ("Richmond", 37.54, -77.44)],
    "WA": [("Seattle", 47.61, -122.33), ("Olympia", 47.04, -122.90)],
    "WV": [("Charleston", 38.35, -81.63), ("Huntington", 38.42, -82.44)],
    "WI": [("Milwaukee", 43.04, -87.91), ("Madison", 43.07, -89.40)],
    "WY": [("Cheyenne", 41.14, -104.82), ("Casper", 42.85, -106.32)],
}

CITY_NAME_SUFFIXES = ["Heights", "Falls", "Springs", "Park", "Junction", "Crossing"]

FIRST_NAMES = [
    "Ananya", "Rohan", "Emily", "Arjun", "Priya", "Maya", "Aarav", "Lucas",
    "Divya", "Karan", "Sofia", "Nikhil", "Wei", "Fatima", "Leo", "Isha",
    "Omar", "Grace", "Tariq", "Zara", "Noah", "Ava", "Liam", "Mia",
]
LAST_NAMES = [
    "Rao", "Singh", "Brown", "Mehta", "Kapoor", "Krishnan", "Gupta", "Nair",
    "Iyer", "Patel", "Khan", "Chen", "Silva", "Reddy", "Ahmed", "Fox",
    "Das", "Costa", "Sharma", "Lee", "Garcia", "Kim", "Novak", "Diaz",
]
GENDERS = ["Male", "Female", "Non-binary", "Prefer not to say"]
GOVT_ID_NAMES = ["Driver's License", "Passport", "State ID Card"]
AUTH_PROVIDERS = ["", "Google", "Facebook", "Apple"]

STATE_TIMEZONES = {
    **{s: "America/New_York" for s in (
        "CT", "DE", "DC", "FL", "GA", "IN", "ME", "MD", "MA", "MI", "NH",
        "NJ", "NY", "NC", "OH", "PA", "RI", "SC", "VT", "VA", "WV",
    )},
    **{s: "America/Chicago" for s in (
        "AL", "AR", "IL", "IA", "KS", "KY", "LA", "MN", "MS", "MO", "NE",
        "ND", "OK", "SD", "TN", "TX", "WI",
    )},
    **{s: "America/Denver" for s in ("AZ", "CO", "ID", "MT", "NM", "UT", "WY")},
    **{s: "America/Los_Angeles" for s in ("CA", "NV", "OR", "WA")},
    "AK": "America/Anchorage",
    "HI": "Pacific/Honolulu",
}

ORG_NAME_CORE = [
    "Harbor", "Bright Path", "Neighborhood", "Riverside", "Unity", "Hope",
    "Cornerstone", "Heartland", "Lighthouse", "Evergreen", "Summit", "Compass",
]
ORG_NAME_SUFFIX = [
    "Veterans Support", "Food Bank", "Youth Alliance", "Family Services",
    "Shelter Network", "Community Outreach", "Relief Fund", "Aid Society",
]
ORG_TYPES = ["Non-Profit", "For-Profit", "Government", "Community"]
ORG_SIZES = ["Small", "Medium", "Large"]
MISSIONS = [
    "Connecting volunteers with neighbors in need across the community.",
    "Providing emergency shelter and food assistance to families in crisis.",
    "Supporting veterans and their families with housing and job resources.",
    "Delivering education and mentorship programs to underserved youth.",
    "Coordinating disaster relief and long-term recovery efforts.",
    "Offering free healthcare screenings and referrals to low-income residents.",
    "Building affordable housing in partnership with local volunteers.",
    "Running food pantries and meal programs for at-risk populations.",
]


def set_seed(seed: int = DEFAULT_SEED) -> None:
    random.seed(seed)


def format_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_date(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def bool_str(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def random_datetime_between(start: datetime, end: datetime) -> datetime:
    delta_seconds = int((end - start).total_seconds())
    if delta_seconds <= 0:
        return start
    return start + timedelta(seconds=random.randint(0, delta_seconds))


def created_and_updated(earliest: datetime = None) -> Tuple[datetime, datetime]:
    """Returns (created_at, updated_at) with created_at <= updated_at <= REFERENCE_NOW."""
    earliest = earliest or (REFERENCE_NOW - timedelta(days=730))
    created = random_datetime_between(earliest, REFERENCE_NOW - timedelta(days=1))
    updated = random_datetime_between(created, REFERENCE_NOW)
    return created, updated


def make_user_id(index: int) -> str:
    """SID-00-000-XXX-XXX matching the existing data-analytics/sql/users.csv convention."""
    high, low = divmod(index, 1000)
    return f"SID-00-000-{high:03d}-{low:03d}"


def make_org_id(index: int) -> str:
    return f"ORG{index:05d}"


def jitter_point(lat: float, lon: float, max_delta: float = 0.15) -> Tuple[float, float]:
    new_lat = lat + random.uniform(-max_delta, max_delta)
    new_lon = lon + random.uniform(-max_delta, max_delta)
    new_lat = max(min(new_lat, 90.0), -90.0)
    new_lon = max(min(new_lon, 180.0), -180.0)
    return round(new_lat, 6), round(new_lon, 6)


def to_wkt_point(lat: float, lon: float) -> str:
    return f"SRID=4326;POINT({lon} {lat})"


_WKT_RE = re.compile(r"POINT\(([-\d.]+) ([-\d.]+)\)")


def parse_wkt_point(value: str) -> Optional[Tuple[float, float]]:
    if not value:
        return None
    match = _WKT_RE.search(value)
    if not match:
        return None
    lon, lat = float(match.group(1)), float(match.group(2))
    return lat, lon


def write_csv(path: str, rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write for {path}")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def load_reference_rows(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_all_csvs(directory: str) -> Dict[str, List[Dict[str, str]]]:
    tables = {}
    for table, filename in TABLE_FILENAMES.items():
        path = os.path.join(directory, filename)
        if os.path.exists(path):
            tables[table] = load_reference_rows(path)
        else:
            tables[table] = []
    return tables


def json_text(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _parse_ts(value: str) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def validate_all(tables: Dict[str, List[Dict[str, str]]]) -> List[str]:
    """Runs PK uniqueness, FK integrity, geo sanity, and timestamp sanity checks.

    Returns a list of human-readable violation strings; an empty list means valid.
    """
    errors: List[str] = []

    # 1. Primary key uniqueness.
    for table, pk_cols in PK_SPECS.items():
        seen = set()
        for row in tables.get(table, []):
            key = tuple(row.get(c, "") for c in pk_cols)
            if key in seen:
                errors.append(f"{table}: duplicate PK {pk_cols}={key}")
            seen.add(key)

    # 2. Foreign key integrity.
    for child, child_cols, parent, parent_cols in FK_SPECS:
        parent_keys = {
            tuple(row.get(c, "") for c in parent_cols)
            for row in tables.get(parent, [])
        }
        for row in tables.get(child, []):
            key = tuple(row.get(c, "") for c in child_cols)
            if key not in parent_keys:
                errors.append(
                    f"{child}: orphaned FK {child_cols}={key} not found in {parent}.{parent_cols}"
                )

    # 3. Geo sanity - cities lat/lon, and any WKT point columns.
    lat_lo, lat_hi = US_LAT_RANGE
    lon_lo, lon_hi = US_LON_RANGE
    for row in tables.get("cities", []):
        try:
            lat, lon = float(row["lattitude"]), float(row["longitude"])
        except (KeyError, ValueError):
            errors.append(f"cities: unparseable coordinates in row {row}")
            continue
        if not (lat_lo <= lat <= lat_hi and lon_lo <= lon <= lon_hi):
            errors.append(f"cities: city_id={row.get('city_id')} coordinates out of range")

    for table in ("volunteer_locations", "user_locations", "users"):
        for row in tables.get(table, []):
            for col in ("prev_loc", "curr_loc", "last_location"):
                if col not in row or not row[col]:
                    continue
                point = parse_wkt_point(row[col])
                if point is None:
                    errors.append(f"{table}: unparseable point in {col}={row[col]!r}")
                    continue
                lat, lon = point
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    errors.append(f"{table}: {col} out of hard lat/lon range")
                elif not (lat_lo <= lat <= lat_hi and lon_lo <= lon <= lon_hi):
                    errors.append(f"{table}: {col} outside plausible US bounding box")

    # 4. Timestamp sanity - parseable, and created_at <= last_updated_at where both exist.
    ts_pairs = {
        "volunteer_details": ("created_at", "last_updated_at"),
        "user_skills": ("created_at", "last_updated_at"),
        "organizations": ("created_at", "last_updated_at"),
    }
    for table, (created_col, updated_col) in ts_pairs.items():
        for row in tables.get(table, []):
            created = _parse_ts(row.get(created_col, ""))
            updated = _parse_ts(row.get(updated_col, ""))
            if row.get(created_col) and created is None:
                errors.append(f"{table}: unparseable {created_col}={row.get(created_col)!r}")
            if row.get(updated_col) and updated is None:
                errors.append(f"{table}: unparseable {updated_col}={row.get(updated_col)!r}")
            if created and updated and created > updated:
                errors.append(
                    f"{table}: {created_col} > {updated_col} for row {row.get('user_id') or row.get('org_id')}"
                )

    return errors
