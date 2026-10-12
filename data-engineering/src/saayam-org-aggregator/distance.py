"""Coordinate parsing and beneficiary-to-organization distance helpers."""

import math
import re
import threading

import pandas as pd


EARTH_RADIUS_MILES = 3958.7613
_GEOCODE_CACHE = {}
_GEOCODE_CACHE_LOCK = threading.Lock()
_GEOCODING_PROVIDER = None


def configure_geocoding_provider(provider):
    """Register the approved address provider without coupling this module to it."""
    global _GEOCODING_PROVIDER
    _GEOCODING_PROVIDER = provider


def parse_coordinates(value):
    """Return validated coordinates as (latitude, longitude), if available."""
    latitude = longitude = None

    if isinstance(value, dict):
        latitude = value.get("latitude", value.get("lat"))
        longitude = value.get("longitude", value.get("lon", value.get("lng")))
    elif isinstance(value, (tuple, list)) and len(value) == 2:
        latitude, longitude = value
    elif isinstance(value, str):
        text = value.strip()
        point = re.search(
            r"POINT\s*\(\s*([-+\d.eE]+)\s+([-+\d.eE]+)\s*\)",
            text,
            re.IGNORECASE,
        )
        if point:
            longitude, latitude = point.groups()
        else:
            lat_match = re.search(
                r"(?:latitude|lat)\s*[:=]\s*([-+\d.eE]+)", text, re.IGNORECASE
            )
            lon_match = re.search(
                r"(?:longitude|lon|lng)\s*[:=]\s*([-+\d.eE]+)",
                text,
                re.IGNORECASE,
            )
            if lat_match and lon_match:
                latitude, longitude = lat_match.group(1), lon_match.group(1)
            else:
                pair = re.fullmatch(
                    r"\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*", text
                )
                if pair:
                    latitude, longitude = pair.groups()

    if latitude is None or longitude is None:
        return None

    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return latitude, longitude


def haversine_miles(origin, destination):
    """Calculate straight-line distance in miles between two coordinates."""
    origin = parse_coordinates(origin)
    destination = parse_coordinates(destination)
    if origin is None or destination is None:
        return None

    lat1, lon1 = map(math.radians, origin)
    lat2, lon2 = map(math.radians, destination)
    delta_latitude = lat2 - lat1
    delta_longitude = lon2 - lon1
    value = (
        math.sin(delta_latitude / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_longitude / 2) ** 2
    )
    value = min(1.0, max(0.0, value))
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(value))


def build_address(record):
    """Join available address fields, skipping blank and missing values."""
    if not isinstance(record, dict):
        return ""

    def clean(value):
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except (TypeError, ValueError):
            pass
        return str(value).strip()

    for field in ("address", "full_address"):
        value = clean(record.get(field))
        if value:
            return value

    fields = (
        "street",
        "addr_ln1",
        "addr_ln2",
        "addr_ln3",
        "city",
        "city_name",
        "state",
        "state_name",
        "state_code",
        "zip_code",
        "postal_code",
        "country",
        "country_name",
        "location",
    )
    parts = []
    seen = set()
    for field in fields:
        value = clean(record.get(field))
        key = value.casefold()
        if value and key not in seen:
            parts.append(value)
            seen.add(key)
    return ", ".join(parts)


def geocode_address(address, provider=None):
    """Resolve an address with an injected provider; no provider is selected yet.

    Successful lookups are cached for warm Lambda invocations. The cache can
    be replaced with persistent storage after the project selects a provider.
    """
    address = (address or "").strip()
    if not address:
        return None, "unknown_location"

    key = " ".join(address.casefold().split())
    with _GEOCODE_CACHE_LOCK:
        cached = _GEOCODE_CACHE.get(key)
    if cached is not None:
        return cached, "ok"
    provider = provider or _GEOCODING_PROVIDER
    if provider is None:
        return None, "deferred"

    try:
        coordinates = parse_coordinates(provider(address))
    except TimeoutError:
        return None, "deferred"
    except Exception:
        return None, "error"

    if coordinates is None:
        return None, "not_found"
    with _GEOCODE_CACHE_LOCK:
        _GEOCODE_CACHE[key] = coordinates
    return coordinates, "ok"


def add_distances(organizations, beneficiary_location, geocoder=geocode_address):
    """Add distance metadata without dropping organizations on lookup failure."""
    result = organizations.copy()
    result["distance"] = None
    result["distance_unit"] = "miles"
    result["distance_method"] = "straight_line"
    result["distance_status"] = "unknown_location"

    beneficiary_location = beneficiary_location or {}
    beneficiary = parse_coordinates(beneficiary_location.get("coordinates"))
    beneficiary_status = beneficiary_location.get("status", "unknown_location")

    for index, row in result.iterrows():
        record = row.to_dict()
        if any(
            str(record.get(flag)).strip().casefold() in {"true", "1", "yes"}
            for flag in ("online_only", "is_online")
            if record.get(flag) is not None
        ):
            result.at[index, "distance_status"] = "online"
            continue
        if beneficiary is None:
            result.at[index, "distance_status"] = beneficiary_status
            continue

        organization = parse_coordinates(record)
        if organization is None:
            address = build_address(record)
            organization, status = geocoder(address)
            if organization is None:
                result.at[index, "distance_status"] = status
                continue

        distance = haversine_miles(beneficiary, organization)
        if distance is None:
            result.at[index, "distance_status"] = "error"
            continue
        result.at[index, "distance"] = round(distance, 1)
        result.at[index, "distance_status"] = "ok"

    return result
