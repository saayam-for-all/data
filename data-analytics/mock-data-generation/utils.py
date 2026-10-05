"""Shared helpers: seeding, timestamp formatting, id synthesis, CSV writing.

Everything here is pure Python standard library so the generator runs with no
third-party dependencies.
"""

from __future__ import annotations

import csv
import json
import os
import random
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Sequence


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------
class ConfigError(Exception):
    """Raised for invalid CLI / configuration inputs."""


class ValidationError(Exception):
    """Raised when generated data fails a schema / integrity check."""


def set_seed(seed: int = 42) -> None:
    """Seed the global RNG so runs are reproducible."""
    random.seed(seed)


# ---------------------------------------------------------------------------
# PostgreSQL-compatible formatting
# ---------------------------------------------------------------------------
def format_ts(value: datetime) -> str:
    """``timestamp without time zone`` -> 'YYYY-MM-DD HH:MM:SS'."""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_tstz(value: datetime) -> str:
    """``timestamp with time zone`` -> 'YYYY-MM-DD HH:MM:SS+00'."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00")


def format_date(value: date) -> str:
    """``date`` -> 'YYYY-MM-DD'."""
    return value.strftime("%Y-%m-%d")


def geography_point(longitude: float, latitude: float) -> str:
    """Render a PostGIS ``geography(Point,4326)`` value as EWKT.

    Note PostGIS point order is (longitude, latitude).
    """
    return f"SRID=4326;POINT({longitude:.6f} {latitude:.6f})"


def native_point(longitude: float, latitude: float) -> str:
    """Render a native PostgreSQL ``point`` value as '(x,y)' = '(lon,lat)'."""
    return f"({longitude:.6f},{latitude:.6f})"


def json_text(value: Any) -> str:
    """Compact JSON for ``jsonb`` columns."""
    return json.dumps(value, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Value synthesis
# ---------------------------------------------------------------------------
def synthetic_user_id() -> str:
    """Cognito-``sub``-style UUID (8-4-4-4-12 lowercase hex), fully synthetic."""
    h = "%032x" % random.getrandbits(128)
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def base_datetime() -> datetime:
    """Reference start point for generated timestamps."""
    return datetime(2024, 1, 1, 9, 0, 0)


def random_datetime(days_span: int = 600) -> datetime:
    """A random datetime within ``days_span`` days after the base date."""
    base = base_datetime()
    return base + timedelta(
        days=random.randint(0, days_span),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
        seconds=random.randint(0, 59),
    )


def later_than(value: datetime, max_days: int = 120) -> datetime:
    """A datetime at or after ``value`` (for updated/last-modified columns)."""
    return value + timedelta(
        days=random.randint(0, max_days),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
        seconds=random.randint(0, 59),
    )


def between(start: datetime, end: datetime) -> datetime:
    """A datetime uniformly in the inclusive range [start, end].

    Guarantees ``start <= result <= end`` so callers can enforce ordering
    (e.g. created_at <= document_update <= last_updated_at).
    """
    if end < start:
        start, end = end, start
    span = int((end - start).total_seconds())
    return start + timedelta(seconds=random.randint(0, span) if span > 0 else 0)


# Postal-code letters (Canada/UK): omit visually ambiguous letters.
_POSTAL_LETTERS = "ABCEGHJKLMNPRSTVWXYZ"


def synth_postal(country_code: str, base: str) -> str:
    """Country-appropriate postal code for a synthesized city.

    Keeps the region-identifying prefix of the seed city's real ``base`` code
    and only varies the fine-grained local part, so the result stays in the same
    region and matches the country's postal format. Never a blind numeric offset.
    """
    r = random
    if country_code in ("USA", "DEU"):          # 5-digit
        return base[:3] + f"{r.randint(0, 99):02d}"
    if country_code == "AUS":                    # 4-digit
        return base[:2] + f"{r.randint(0, 99):02d}"
    if country_code == "IND":                    # 6-digit
        return base[:3] + f"{r.randint(0, 999):03d}"
    if country_code == "CAN":                    # A1A 1A1
        fsa = base.split(" ")[0]
        return f"{fsa} {r.randint(0, 9)}{r.choice(_POSTAL_LETTERS)}{r.randint(0, 9)}"
    if country_code == "GBR":                    # OUT 1AA
        out = base.split(" ")[0]
        return f"{out} {r.randint(0, 9)}{r.choice(_POSTAL_LETTERS)}{r.choice(_POSTAL_LETTERS)}"
    return base


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------
def write_csv(path: str, fieldnames: Sequence[str], rows: Sequence[Dict[str, Any]]) -> int:
    """Write ``rows`` to ``path`` with an explicit column order.

    Empty / None values are emitted as blank fields. Returns the number of data
    rows written.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fieldnames})
    return len(rows)


def pick(seq: Sequence[Any]) -> Any:
    return random.choice(seq)


def maybe(value: Any, probability: float = 0.85) -> Any:
    """Return ``value`` with the given probability, else ``None`` (NULL)."""
    return value if random.random() < probability else None
