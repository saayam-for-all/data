"""Provider-neutral organization distance and geocoding utilities."""

import json
import math
import re
from typing import Any, Callable, MutableMapping, Optional


_EARTH_RADIUS_MILES = 3958.7613
_COORDINATE_CACHE: dict[str, tuple[float, float]] = {}
_WKT_POINT = re.compile(r"POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", re.IGNORECASE)
_LABELED_COORDINATE = re.compile(
    r"(?:longitude|lon|lng)\s*[:=]\s*(-?\d+(?:\.\d+)?)\s*[,; ]+"
    r"(?:latitude|lat)\s*[:=]\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_LAT_LON_COORDINATE = re.compile(
    r"(?:latitude|lat)\s*[:=]\s*(-?\d+(?:\.\d+)?)\s*[,; ]+"
    r"(?:longitude|lon|lng)\s*[:=]\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


class GeocodingDeferredError(Exception):
    """Signal that geocoding was postponed by provider limits or availability."""


def _has_value(value: Any) -> bool:
    """Return whether a value contains meaningful non-null data."""
    if value is None:
        return False
    try:
        if math.isnan(value):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return value.strip().casefold() not in ("", "nan", "none", "null", "n/a")
    return True


def parse_coordinates(location: Any) -> Optional[tuple[float, float]]:
    """Parse a location into a validated ``(latitude, longitude)`` pair."""
    if location is None:
        return None

    if isinstance(location, dict):
        if str(location.get("type", "")).casefold() == "point":
            point = location.get("coordinates")
            if isinstance(point, (tuple, list)) and len(point) >= 2:
                return _validated_coordinates(point[1], point[0])
        if isinstance(location.get("geometry"), dict):
            coordinates = parse_coordinates(location["geometry"])
            if coordinates is not None:
                return coordinates
        latitude = location.get("latitude", location.get("lat"))
        longitude = location.get("longitude", location.get("lon", location.get("lng")))
        if latitude is not None and longitude is not None:
            return _validated_coordinates(latitude, longitude)
        for key in ("coordinates", "req_loc", "curr_loc", "location"):
            if key in location:
                coordinates = parse_coordinates(location[key])
                if coordinates is not None:
                    return coordinates
        return None

    if isinstance(location, (tuple, list)) and len(location) >= 2:
        return _validated_coordinates(location[0], location[1])

    if not isinstance(location, str):
        return None

    value = location.strip()
    if not value:
        return None
    if value.startswith("{"):
        try:
            return parse_coordinates(json.loads(value))
        except (json.JSONDecodeError, TypeError):
            return None

    wkt_match = _WKT_POINT.search(value)
    if wkt_match:
        longitude, latitude = wkt_match.groups()
        return _validated_coordinates(latitude, longitude)

    labeled_match = _LABELED_COORDINATE.search(value)
    if labeled_match:
        longitude, latitude = labeled_match.groups()
        return _validated_coordinates(latitude, longitude)

    lat_lon_match = _LAT_LON_COORDINATE.search(value)
    if lat_lon_match:
        latitude, longitude = lat_lon_match.groups()
        return _validated_coordinates(latitude, longitude)

    pair = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*", value)
    if pair:
        latitude, longitude = pair.groups()
        return _validated_coordinates(latitude, longitude)
    return None


def _validated_coordinates(latitude: Any, longitude: Any) -> Optional[tuple[float, float]]:
    """Convert and range-check coordinate values."""
    try:
        if isinstance(latitude, bool) or isinstance(longitude, bool):
            return None
        latitude_value = float(latitude)
        longitude_value = float(longitude)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(latitude_value) or not math.isfinite(longitude_value):
        return None
    if not -90 <= latitude_value <= 90 or not -180 <= longitude_value <= 180:
        return None
    return latitude_value, longitude_value


def _address_from_location(location: Any) -> Optional[str]:
    """Extract a usable address from a string or named location fields."""
    if isinstance(location, str):
        address = location.strip()
        return address if _has_value(address) else None
    if not isinstance(location, dict):
        return None
    for key in ("address", "formatted_address", "location", "curr_loc", "req_loc"):
        value = location.get(key)
        if isinstance(value, str) and _has_value(value):
            return value.strip()
    fields = ("street", "street_address", "city_name", "city", "state_name", "state", "zip_code", "postal_code", "country_name", "country")
    parts = [
        str(location[key]).strip()
        for key in fields
        if _has_value(location.get(key))
    ]
    return ", ".join(parts) if parts else None


def select_beneficiary_location(
    request_location: Any,
    user_location: Any,
    profile_address: Any,
) -> Any:
    """Choose request coordinates, then user coordinates, then profile address."""
    for location in (request_location, user_location):
        coordinates = parse_coordinates(location)
        if coordinates is not None:
            return coordinates
    user_address = _address_from_location(user_location)
    if user_address and not _is_coordinate_notation(user_address):
        return user_address
    profile_coordinates = parse_coordinates(profile_address)
    if profile_coordinates is not None:
        return profile_coordinates
    return _address_from_location(profile_address)


def _is_coordinate_notation(value: str) -> bool:
    """Identify malformed coordinate strings so profile fallback can continue."""
    return bool(
        re.match(r"^(?:SRID=\d+;)?POINT\b", value, re.IGNORECASE)
        or _LABELED_COORDINATE.search(value)
        or _LAT_LON_COORDINATE.search(value)
    )


def _geocode_address(
    address: Optional[str],
    geocoder: Optional[Callable[[str], Any]],
    cache: Optional[MutableMapping[str, Any]],
) -> tuple[Optional[tuple[float, float]], str]:
    """Resolve an address through the injected provider and coordinate cache."""
    if not address:
        return None, "unknown_location"
    cache_key = " ".join(address.casefold().split())
    coordinate_cache = _COORDINATE_CACHE if cache is None else cache
    try:
        cached = coordinate_cache.get(cache_key)
        if cached is not None:
            coordinates = parse_coordinates(cached)
            if coordinates is not None:
                return coordinates, "ok"
    except Exception:
        pass

    if geocoder is None:
        return None, "deferred"
    try:
        coordinates = parse_coordinates(geocoder(address))
    except GeocodingDeferredError:
        return None, "deferred"
    except Exception:
        return None, "error"
    if coordinates is None:
        return None, "not_found"
    try:
        coordinate_cache[cache_key] = coordinates
    except Exception:
        pass
    return coordinates, "ok"


def _resolve_location(
    location: Any,
    geocoder: Optional[Callable[[str], Any]],
    cache: Optional[MutableMapping[str, Any]],
) -> tuple[Optional[tuple[float, float]], str]:
    """Resolve direct coordinates first and otherwise geocode a named address."""
    coordinates = parse_coordinates(location)
    if coordinates is not None:
        return coordinates, "ok"
    return _geocode_address(_address_from_location(location), geocoder, cache)


def _is_online_only(organization_location: Any) -> bool:
    """Return whether an organization explicitly has an online-only location."""
    if not isinstance(organization_location, dict):
        return False
    value = organization_location.get(
        "is_online",
        organization_location.get("online_only", organization_location.get("online", False)),
    )
    if not _has_value(value):
        return False
    return value is True or str(value).strip().casefold() in ("true", "1", "yes")


def _straight_line_miles(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    """Calculate Haversine great-circle distance in miles."""
    first_latitude, first_longitude = map(math.radians, first)
    second_latitude, second_longitude = map(math.radians, second)
    latitude_delta = second_latitude - first_latitude
    longitude_delta = second_longitude - first_longitude
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(first_latitude)
        * math.cos(second_latitude)
        * math.sin(longitude_delta / 2) ** 2
    )
    return _EARTH_RADIUS_MILES * 2 * math.asin(math.sqrt(min(1.0, haversine)))


def resolve_distance(
    beneficiary_location: Any,
    organization_location: Any,
    geocoder: Optional[Callable[[str], Any]] = None,
    cache: Optional[MutableMapping[str, Any]] = None,
) -> dict[str, Any]:
    """Return distance and metadata without allowing lookup failures to escape."""
    result = {
        "distance": None,
        "distance_unit": "miles",
        "distance_method": "straight_line",
        "distance_status": "unknown_location",
    }
    if _is_online_only(organization_location):
        result["distance_status"] = "online"
        return result

    beneficiary_coordinates, beneficiary_status = _resolve_location(
        beneficiary_location, geocoder, cache
    )
    if beneficiary_coordinates is None:
        result["distance_status"] = beneficiary_status
        return result

    organization_coordinates, organization_status = _resolve_location(
        organization_location, geocoder, cache
    )
    if organization_coordinates is None:
        result["distance_status"] = organization_status
        return result

    try:
        result["distance"] = _straight_line_miles(
            beneficiary_coordinates, organization_coordinates
        )
        result["distance_status"] = "ok"
    except Exception:
        result["distance_status"] = "error"
    return result


def _organization_location(organization: dict[str, Any]) -> Any:
    """Build an organization address from actual named location fields."""
    coordinates = parse_coordinates(organization)
    if coordinates is not None:
        return coordinates
    address_fields = (
        "street",
        "street_address",
        "address_line_1",
        "city_name",
        "city",
        "state_name",
        "state",
        "zip_code",
        "postal_code",
        "country_name",
        "country",
    )
    address_parts = [
        str(organization[field]).strip()
        for field in address_fields
        if _has_value(organization.get(field))
    ]
    if address_parts:
        return ", ".join(address_parts)
    return _address_from_location(organization)


def enrich_organizations(
    organizations: list[dict[str, Any]],
    beneficiary_location: Any,
    geocoder: Optional[Callable[[str], Any]] = None,
    cache: Optional[MutableMapping[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Add distance metadata while retaining each organization on failures."""
    prepared = [dict(organization) for organization in organizations]
    needs_distance = any(not _is_online_only(row) for row in prepared)
    beneficiary_coordinates = None
    beneficiary_status = "unknown_location"
    if needs_distance:
        try:
            beneficiary_coordinates, beneficiary_status = _resolve_location(
                beneficiary_location, geocoder, cache
            )
        except Exception:
            beneficiary_status = "error"

    enriched = []
    for row in prepared:
        try:
            organization_location = _organization_location(row)
            if _is_online_only(row):
                distance = resolve_distance(None, row)
            elif beneficiary_coordinates is None:
                distance = {
                    "distance": None,
                    "distance_unit": "miles",
                    "distance_method": "straight_line",
                    "distance_status": beneficiary_status,
                }
            else:
                distance = resolve_distance(
                    beneficiary_coordinates,
                    organization_location,
                    geocoder=geocoder,
                    cache=cache,
                )
        except Exception:
            distance = {
                "distance": None,
                "distance_unit": "miles",
                "distance_method": "straight_line",
                "distance_status": "error",
            }
        row.update(distance)
        enriched.append(row)
    return enriched