"""Shared helpers for mock-data generation.

Formatting here follows the Virginia schema as documented in the database wiki
page "* Changes to the Database, Waiting for Microservice" (the "Table after
changes" blocks), which issue #301 names as the source of truth.
"""

import csv
import json
import random
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Sequence

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"


def set_seed(seed: int) -> None:
    random.seed(seed)


# --- Identifiers ----------------------------------------------------------


def user_id(sequence_value: int) -> str:
    """Mirror virginia_dev_saayam_rdbms.generate_sid() (updated 07/07/2026).

    The sequence value is zero-padded to 15 digits and split into five groups
    of three, e.g. 1 -> SID-00-000-000-000-000-001.
    """
    padded = str(sequence_value).zfill(15)
    groups = [padded[i:i + 3] for i in range(0, 15, 3)]
    return "SID-00-" + "-".join(groups)


def org_id(sequence_value: int) -> str:
    """Mirror virginia_dev_saayam_rdbms.generate_org_id().

    The sequence value is zero-padded to 13 digits and split 3-3-3-4,
    e.g. 1 -> ORG-000-000-000-0001.
    """
    padded = str(sequence_value).zfill(13)
    return "ORG-" + "-".join([padded[0:3], padded[3:6], padded[6:9], padded[9:13]])


# --- Value formatting -----------------------------------------------------


def format_timestamp(value: datetime) -> str:
    return value.strftime(TIMESTAMP_FORMAT)


def format_date(value: datetime) -> str:
    return value.strftime(DATE_FORMAT)


def format_bool(value: bool) -> str:
    """PostgreSQL accepts true/false for BOOLEAN columns in CSV input."""
    return "true" if value else "false"


def format_point(latitude: float, longitude: float) -> str:
    """PostgreSQL `point` literal, as used by users.last_location.

    ddl_users.sql documents the example `(37.3382, -121.8863)` for San Jose,
    i.e. latitude first.
    """
    return f"({latitude:.6f},{longitude:.6f})"


def format_geography(latitude: float, longitude: float) -> str:
    """EWKT for geography(Point, 4326) columns.

    PostGIS POINT takes longitude first. Matches the import documented in the
    wiki page on geography parsing for the cities table.
    """
    return f"SRID=4326;POINT({longitude:.6f} {latitude:.6f})"


def json_text(value: Any) -> str:
    """Compact JSON for jsonb columns; csv quoting is handled by the writer."""
    return json.dumps(value, separators=(",", ":"))


NULL = ""  # An empty CSV field is read as NULL by PostgreSQL COPY ... CSV.


# --- Timestamps -----------------------------------------------------------


def parse_window(start: str, end: str) -> tuple:
    return (
        datetime.strptime(start, TIMESTAMP_FORMAT),
        datetime.strptime(end, TIMESTAMP_FORMAT),
    )


def random_datetime(start: datetime, end: datetime) -> datetime:
    """Uniform random datetime in [start, end), to the second."""
    span = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, max(span - 1, 0)))


def later_than(value: datetime, ceiling: datetime) -> datetime:
    """A timestamp in [value, ceiling], so created_at <= last_updated_at holds."""
    if ceiling <= value:
        return value
    return random_datetime(value, ceiling)


# --- Geography ------------------------------------------------------------


def jitter_coordinate(latitude: float, longitude: float, max_degrees: float) -> tuple:
    """Offset a coordinate slightly, keeping it within the same locality.

    Longitude degrees are narrowed near the poles so the offset stays roughly
    circular on the ground rather than stretching east-west.
    """
    import math

    lat_offset = random.uniform(-max_degrees, max_degrees)
    scale = max(math.cos(math.radians(latitude)), 0.1)
    lon_offset = random.uniform(-max_degrees, max_degrees) / scale
    new_lat = max(min(latitude + lat_offset, 90.0), -90.0)
    new_lon = longitude + lon_offset
    if new_lon > 180.0:
        new_lon -= 360.0
    elif new_lon < -180.0:
        new_lon += 360.0
    return new_lat, new_lon


# --- CSV ------------------------------------------------------------------


def write_csv(path, fieldnames: Sequence[str], rows: Iterable[Dict[str, Any]]) -> int:
    rows = list(rows)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def read_csv(path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def weighted_choices(weights: Dict[Any, float], count: int) -> List[Any]:
    """Deterministic weighted sample of `count` keys."""
    keys = list(weights.keys())
    return random.choices(keys, weights=[weights[k] for k in keys], k=count)
