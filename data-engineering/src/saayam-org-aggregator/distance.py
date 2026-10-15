"""Straight-line distance from the beneficiary to each organization (issue #433)."""

import logging
import math
from typing import Callable, Iterable, Optional, Sequence, Union

import pandas as pd

import db_columns as cols
from geocoding import STATUS_OK, geocode_address

logger = logging.getLogger(__name__)

EARTH_RADIUS_MILES = 3958.8
DISTANCE_UNIT = "miles"
DISTANCE_METHOD = "straight_line"

STATUS_ONLINE = "online"
STATUS_UNKNOWN_LOCATION = "unknown_location"
STATUS_ERROR = "error"

DISTANCE_COLUMNS = ["distance", "distance_unit", "distance_method", "distance_status"]

Point = tuple[float, float]  # (lat, lon)
ColumnSpec = Union[str, Sequence[str]]


def haversine_miles(origin: Point, destination: Point) -> float:
    """Great-circle distance in miles, rounded to 1 decimal."""
    lat1, lon1 = map(math.radians, origin)
    lat2, lon2 = map(math.radians, destination)
    a = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return round(EARTH_RADIUS_MILES * c, 1)


def _distance_fields(distance: Optional[float], status: str) -> dict:
    return {
        "distance": distance,
        "distance_unit": DISTANCE_UNIT,
        "distance_method": DISTANCE_METHOD,
        "distance_status": status,
    }


def clean_text(value: object) -> Optional[str]:
    """Return a stripped string, or None for None/NaN/blank values."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def _first_value(row: dict, spec: ColumnSpec) -> Optional[str]:
    names = (spec,) if isinstance(spec, str) else spec
    for name in names:
        value = clean_text(row.get(name))
        if value is not None:
            return value
    return None


def _is_truthy_flag(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "t", "yes", "y", "1"}
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return bool(value)


def compute_org_distance(origin: Optional[Point], address: Optional[str],
                         online: bool = False) -> dict:
    """Distance fields for one org. Never raises."""
    try:
        if online:
            return _distance_fields(None, STATUS_ONLINE)
        if origin is None or address is None:
            return _distance_fields(None, STATUS_UNKNOWN_LOCATION)
        result = geocode_address(address)
        if result.status != STATUS_OK:
            return _distance_fields(None, result.status)
        return _distance_fields(haversine_miles(origin, (result.lat, result.lon)), STATUS_OK)
    except Exception:
        logger.exception("Distance calculation failed for address %r", address)
        return _distance_fields(None, STATUS_ERROR)


def build_db_org_address(row: dict, state_names: Optional[dict] = None) -> Optional[str]:
    """Fullest address available for a DB org, or None if too vague.

    State IDs/codes are swapped for names via state_names when known. An
    address needs a street, city or zip so it never collapses to just a
    state or country.
    """
    street = _first_value(row, cols.ORG_STREET_COLUMN)
    city = _first_value(row, cols.ORG_CITY_COLUMN)
    zip_code = _first_value(row, cols.ORG_ZIP_COLUMN)
    if street is None and city is None and zip_code is None:
        return None
    state = _first_value(row, cols.ORG_STATE_COLUMNS)
    if state is not None and state_names:
        state = state_names.get(state, state)
    country = _first_value(row, cols.ORG_COUNTRY_COLUMNS)
    return join_address([street, city, state, zip_code, country])


def build_genai_org_address(row: dict) -> Optional[str]:
    """Address/location string returned by the GenAI Lambda, if any."""
    return _first_value(row, cols.GENAI_ADDRESS_COLUMNS)


def join_address(parts: Iterable[Optional[str]]) -> Optional[str]:
    """Join non-empty parts with ", "; underscores in lookup names become spaces."""
    cleaned = [p.replace("_", " ") for p in (clean_text(p) for p in parts) if p]
    return ", ".join(cleaned) or None


def _is_online(row: dict, flag_columns: Sequence[str]) -> bool:
    return any(_is_truthy_flag(row.get(name)) for name in flag_columns)


def add_distance_columns(df: pd.DataFrame, origin: Optional[Point],
                         address_builder: Callable[[dict], Optional[str]],
                         online_columns: Sequence[str] = ()) -> pd.DataFrame:
    """Return a copy of df with the four distance columns added.

    Each row is handled in isolation: a failure only marks that row "error".
    The distance column is object dtype so unknown stays None (not NaN) and
    a real 0.0 stays 0.0.
    """
    rows = []
    for row in df.to_dict(orient="records"):
        try:
            online = _is_online(row, online_columns)
            address = None if online else address_builder(row)
            rows.append(compute_org_distance(origin, address, online))
        except Exception:
            logger.exception("Could not prepare distance for org row")
            rows.append(_distance_fields(None, STATUS_ERROR))

    out = df.copy()
    for column in DISTANCE_COLUMNS:
        out[column] = pd.Series([r[column] for r in rows], index=df.index, dtype=object)
    return out
