"""
Shared helpers used by every table generator: reproducible randomness,
CSV writing, timestamp formatting, Virginia-schema ID generation, and
geo-coordinate helpers.

Standard library only - no third-party dependencies required.
"""

import csv
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

def set_seed(seed: int = 42) -> None:
    """Seed the shared random module so every run produces the same data."""
    random.seed(seed)


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def write_csv(filepath: str, rows: Sequence[Dict[str, Any]], fieldnames: Optional[List[str]] = None) -> None:
    """Write a list of dict rows to CSV. `fieldnames` fixes column order/
    presence even for a table with zero rows (still writes the header)."""
    if fieldnames is None:
        if not rows:
            raise ValueError(f"No rows and no fieldnames given for {filepath}")
        fieldnames = list(rows[0].keys())
    with open(filepath, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Timestamp / date helpers
# ---------------------------------------------------------------------------

TS_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"

# All generated activity falls inside this window so that every derived
# timestamp (created_at, last_updated_at, terms_accepted_at, ...) stays
# chronologically consistent (created_at <= last_updated_at, etc.).
WINDOW_START = datetime(2025, 6, 1, 8, 0, 0)
WINDOW_END = datetime(2026, 9, 1, 20, 0, 0)


def format_ts(value: Optional[datetime]) -> str:
    return value.strftime(TS_FORMAT) if value else ""


def format_date(value) -> str:
    return value.strftime(DATE_FORMAT) if value else ""


def random_datetime_in_window(start: Optional[datetime] = None, end: Optional[datetime] = None) -> datetime:
    start = start or WINDOW_START
    end = end or WINDOW_END
    delta_seconds = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, max(delta_seconds, 0)))


def random_datetime_after(base: datetime, max_days: int = 30, max_hours: int = 23) -> datetime:
    """A timestamp that is >= base, used to keep created_at <= last_updated_at
    (and similar ordering rules) always true."""
    return base + timedelta(
        days=random.randint(0, max_days),
        hours=random.randint(0, max_hours),
        minutes=random.randint(0, 59),
        seconds=random.randint(0, 59),
    )


def random_dob(min_age: int = 18, max_age: int = 80, as_of: Optional[datetime] = None) -> datetime.date:
    as_of = as_of or WINDOW_END
    age_days = random.randint(min_age * 365, max_age * 365)
    return (as_of - timedelta(days=age_days)).date()


# ---------------------------------------------------------------------------
# Virginia-schema ID generators
# (Mirrors the generate_sid()/generate_org_id() trigger logic documented in
# the database wiki, so mock IDs look exactly like what the DB would emit.)
# ---------------------------------------------------------------------------

def make_user_id(seq: int) -> str:
    padded = str(seq).zfill(15)
    parts = [padded[0:3], padded[3:6], padded[6:9], padded[9:12], padded[12:15]]
    return "SID-00-" + "-".join(parts)


def make_org_id(seq: int) -> str:
    padded = str(seq).zfill(13)
    parts = [padded[0:3], padded[3:6], padded[6:9], padded[9:13]]
    return "ORG-" + "-".join(parts)


# ---------------------------------------------------------------------------
# Geography helpers
# ---------------------------------------------------------------------------

def jitter_coord(lat: float, lon: float, max_delta: float = 0.05) -> "tuple[float, float]":
    """Nudge a centroid coordinate a small, plausible amount so not every
    record in the same city lands on the exact same point."""
    return (
        round(lat + random.uniform(-max_delta, max_delta), 6),
        round(lon + random.uniform(-max_delta, max_delta), 6),
    )


def ewkt_point(lat: float, lon: float) -> str:
    """geography(Point,4326) text form, per the wiki's documented EWKT
    convention: 'SRID=4326;POINT(lon lat)'."""
    return f"SRID=4326;POINT({lon:.6f} {lat:.6f})"


def pg_point(lat: float, lon: float) -> str:
    """Postgres `point` text form for users.last_location, following the
    DDL's own inline example: 'last_location (37.3382, -121.8863)' i.e.
    (latitude, longitude) order."""
    return f"({lat:.6f},{lon:.6f})"


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def weighted_bool(true_probability: float) -> bool:
    return random.random() < true_probability


def unique_sample(population: Sequence[Any], k: int) -> List[Any]:
    k = min(k, len(population))
    return random.sample(list(population), k)
