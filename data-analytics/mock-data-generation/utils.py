"""Shared helpers: CSV I/O, PostgreSQL-compatible value formatting, random
sampling, postal codes and geographic math."""

import csv
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, TypeVar

from schema import Table

T = TypeVar("T")

TS_FORMAT = "%Y-%m-%d %H:%M:%S"  # PostgreSQL TIMESTAMP WITHOUT TIME ZONE, e.g. 2026-08-31 14:30:00
DATE_FORMAT = "%Y-%m-%d"
EARTH_RADIUS_KM = 6371.0088

# Total postal-code length per ISO alpha-3 country code; the city's zip_prefix
# fills the front and random digits fill the rest. Canada is handled separately
# (letter-digit-letter FSA prefix + "digit letter digit").
POSTAL_LENGTH = {"USA": 5, "IND": 6, "DEU": 5, "AUS": 4}
CANADA_POSTAL_LETTERS = "ABCEGHJKLMNPRSTVWXYZ"


# --- CSV -----------------------------------------------------------------------
def read_reference_csv(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def format_value(value: Any) -> str:
    """Render a Python value as a PostgreSQL COPY ... CSV cell.

    None becomes an empty (unquoted) cell, which COPY reads as NULL.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.strftime(TS_FORMAT)
    if isinstance(value, date):
        return value.strftime(DATE_FORMAT)
    return str(value)


def write_csv(path: Path, table: Table, rows: Sequence[Dict[str, Any]]) -> None:
    """Write rows with the table's exact column order. Unknown keys are an error
    (catches typos); missing keys are written as NULL."""
    columns = table.column_names
    allowed = set(columns)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            extra = set(row) - allowed
            if extra:
                raise KeyError(f"{table.name}: unknown column(s) {sorted(extra)}")
            writer.writerow([format_value(row.get(c)) for c in columns])


# --- Random sampling -------------------------------------------------------------
def weighted_choice(rng: random.Random, pairs: Sequence[Tuple[T, float]]) -> T:
    """Pick from (value, weight) pairs; weights need not sum to 1."""
    return rng.choices([p[0] for p in pairs], weights=[p[1] for p in pairs], k=1)[0]


def chance(rng: random.Random, probability: float) -> bool:
    return rng.random() < probability


def rand_datetime(rng: random.Random, start: datetime, end: datetime) -> datetime:
    """Uniform whole-second timestamp in [start, end]; returns start if end < start."""
    span = int((end - start).total_seconds())
    if span <= 0:
        return start
    return start + timedelta(seconds=rng.randint(0, span))


def rand_after(rng: random.Random, start: datetime, max_delta: timedelta, cap: datetime) -> datetime:
    """A timestamp within max_delta after `start`, never later than `cap`."""
    return min(rand_datetime(rng, start, start + max_delta), cap)


# --- Postal codes / phones -------------------------------------------------------
def postal_code(rng: random.Random, country_code: str, zip_prefix: str) -> str:
    if country_code == "CAN":
        ldu = f"{rng.randint(0, 9)}{rng.choice(CANADA_POSTAL_LETTERS)}{rng.randint(0, 9)}"
        return f"{zip_prefix} {ldu}"
    length = POSTAL_LENGTH[country_code]
    rest = length - len(zip_prefix)
    return zip_prefix + "".join(str(rng.randint(0, 9)) for _ in range(rest))


def fictional_phone(rng: random.Random, phone_code: str) -> str:
    """E.164-style number whose subscriber part is the fictional 555-01xx range."""
    area = rng.randint(201, 989)
    return f"+{phone_code.replace('-', '')}{area}55501{rng.randint(0, 99):02d}"


# --- Geography --------------------------------------------------------------------
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def jitter_point(
    rng: random.Random, lat: float, lon: float, sigma_km: float = 4.0, max_km: float = 15.0
) -> Tuple[float, float]:
    """A point near (lat, lon): Gaussian offset in km, clipped to max_km, so the
    result stays plausibly inside the same city/metro area."""
    dx, dy = rng.gauss(0, sigma_km), rng.gauss(0, sigma_km)  # east, north (km)
    dist = math.hypot(dx, dy)
    if dist > max_km:
        dx, dy = dx * max_km / dist, dy * max_km / dist
    dlat = dy / EARTH_RADIUS_KM * 180 / math.pi
    dlon = dx / (EARTH_RADIUS_KM * math.cos(math.radians(lat))) * 180 / math.pi
    return round(lat + dlat, 6), round(lon + dlon, 6)


def ewkt_point(lat: float, lon: float) -> str:
    """geography(Point, 4326) literal; PostGIS order is POINT(longitude latitude)."""
    return f"SRID=4326;POINT({lon:.6f} {lat:.6f})"


def pg_point(lat: float, lon: float) -> str:
    """PostgreSQL native `point` literal, x = longitude, y = latitude."""
    return f"({lon:.6f},{lat:.6f})"


def parse_ewkt_point(text: str) -> Optional[Tuple[float, float]]:
    """Inverse of ewkt_point -> (lat, lon), or None if the text is not one."""
    if not text.startswith("SRID=4326;POINT(") or not text.endswith(")"):
        return None
    lon_s, lat_s = text[len("SRID=4326;POINT("):-1].split(" ")
    return float(lat_s), float(lon_s)


def parse_pg_point(text: str) -> Optional[Tuple[float, float]]:
    """Inverse of pg_point -> (lat, lon), or None if the text is not one."""
    if not (text.startswith("(") and text.endswith(")")):
        return None
    lon_s, lat_s = text[1:-1].split(",")
    return float(lat_s), float(lon_s)
