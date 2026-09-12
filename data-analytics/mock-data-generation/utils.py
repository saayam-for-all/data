from __future__ import annotations

import csv
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

GENERATION_START = datetime(2024, 1, 1, 0, 0, 0)
GENERATION_END = datetime(2026, 8, 31, 23, 59, 59)


def format_timestamp(value: datetime) -> str:
    return value.strftime(TIMESTAMP_FORMAT)


def parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, TIMESTAMP_FORMAT)


def random_datetime(
    rng: random.Random,
    start: datetime = GENERATION_START,
    end: datetime = GENERATION_END,
) -> datetime:
    if end < start:
        raise ValueError("end must not be before start")

    total_seconds = int((end - start).total_seconds())

    if total_seconds == 0:
        return start

    return start + timedelta(seconds=rng.randint(0, total_seconds))


def random_datetime_between(
    rng: random.Random,
    start: datetime,
    end: datetime,
) -> datetime:
    return random_datetime(rng, start, end)


def random_date_of_birth(
    rng: random.Random,
    min_age: int = 18,
    max_age: int = 75,
) -> str:
    reference_date = date(2026, 8, 31)

    youngest = reference_date.replace(
        year=reference_date.year - min_age
    )

    oldest = reference_date.replace(
        year=reference_date.year - max_age
    )

    total_days = (youngest - oldest).days

    dob = oldest + timedelta(days=rng.randint(0, total_days))

    return dob.isoformat()


def generate_user_id(sequence_number: int) -> str:
    """
    Match the current Virginia SID generator format.

    SID-00-000-000-000-000-001
    """

    if sequence_number <= 0:
        raise ValueError("sequence_number must be positive")

    padded = f"{sequence_number:015d}"

    groups = [
        padded[0:3],
        padded[3:6],
        padded[6:9],
        padded[9:12],
        padded[12:15],
    ]

    return "SID-00-" + "-".join(groups)


def generate_org_id(sequence_number: int) -> str:
    """
    Match the current Virginia organization ID format.

    ORG-000-000-000-0001
    """

    if sequence_number <= 0:
        raise ValueError("sequence_number must be positive")

    padded = f"{sequence_number:013d}"

    return (
        f"ORG-{padded[0:3]}-"
        f"{padded[3:6]}-"
        f"{padded[6:9]}-"
        f"{padded[9:13]}"
    )


def jitter_coordinates(
    rng: random.Random,
    latitude: float,
    longitude: float,
    max_delta: float,
) -> tuple[float, float]:
    new_latitude = latitude + rng.uniform(-max_delta, max_delta)
    new_longitude = longitude + rng.uniform(-max_delta, max_delta)

    new_latitude = max(-90.0, min(90.0, new_latitude))
    new_longitude = max(-180.0, min(180.0, new_longitude))

    return round(new_latitude, 6), round(new_longitude, 6)


def postgres_point(latitude: float, longitude: float) -> str:
    """
    PostgreSQL point representation used by users.last_location.

    The database wiki example represents San Jose as:
    (37.3382, -121.8863)
    """

    return f"({latitude:.6f},{longitude:.6f})"


def geography_point(latitude: float, longitude: float) -> str:
    """
    PostGIS EWKT representation.

    PostGIS POINT uses longitude first, then latitude.
    """

    return f"SRID=4326;POINT({longitude:.6f} {latitude:.6f})"


def parse_geography_point(value: str) -> tuple[float, float]:
    prefix = "SRID=4326;POINT("

    if not value.startswith(prefix) or not value.endswith(")"):
        raise ValueError(f"Invalid geography point: {value}")

    body = value[len(prefix):-1]

    parts = body.split()

    if len(parts) != 2:
        raise ValueError(f"Invalid geography point: {value}")

    longitude = float(parts[0])
    latitude = float(parts[1])

    return latitude, longitude


def haversine_distance_km(
    latitude_1: float,
    longitude_1: float,
    latitude_2: float,
    longitude_2: float,
) -> float:
    radius_km = 6371.0088

    lat1 = math.radians(latitude_1)
    lat2 = math.radians(latitude_2)

    delta_lat = math.radians(latitude_2 - latitude_1)
    delta_lon = math.radians(longitude_2 - longitude_1)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return radius_km * c


def boolean_csv(value: bool) -> str:
    return "true" if value else "false"


def normalize_csv_value(value: Any) -> Any:
    if value is None:
        return ""

    if isinstance(value, bool):
        return boolean_csv(value)

    return value


def write_csv(
    output_path: Path,
    columns: list[str],
    rows: Iterable[dict[str, Any]],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=columns,
            extrasaction="raise",
        )

        writer.writeheader()

        for row in rows:
            normalized_row = {
                column: normalize_csv_value(row.get(column))
                for column in columns
            }

            writer.writerow(normalized_row)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as csv_file:
        return list(csv.DictReader(csv_file))