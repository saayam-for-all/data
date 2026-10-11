"""Straight-line distances and resilient enrichment with explicitly injected dependencies."""

import math
from collections.abc import Callable, Iterable
from decimal import Decimal
from numbers import Real

from address_geocoding import (
    CoordinateCache,
    CoordinateRecord,
    GeocodingProvider,
    GeocodingResult,
    geocode_address,
    geocode_beneficiary_profile,
)
from beneficiary_location import LocationRecordSource, _coordinates, resolve_beneficiary_location
from organization_addresses import OrganizationAddress

# IUGG mean Earth radius (6371.0088 km), converted using the exact international mile.
EARTH_RADIUS_MILES = 6371.0088 / 1.609344
STATUS_MAP = {
    "resolved": "ok",
    "missing_location": "unknown_location",
    "not_found": "not_found",
    "deferred": "deferred",
    "timeout": "error",
    "error": "error",
}


def nearest_first(organizations: Iterable[dict]) -> list[dict]:
    """Return a stable sorted copy; only finite nonnegative ok distances are available.

    Zero sorts first. Invalid numbers, strings, booleans, and unavailable statuses
    sort last in their original order. This helper does not change live ordering.
    """
    def key(record):
        value = record.get("distance")
        if record.get("distance_status") != "ok" or isinstance(value, bool):
            return (1, 0)
        if not isinstance(value, (Real, Decimal)):
            return (1, 0)
        try:
            number = float(value)
        except (ValueError, OverflowError):
            return (1, 0)
        return (0, number) if math.isfinite(number) and number >= 0 else (1, 0)

    return sorted(organizations, key=key)


def straight_line_miles(origin: tuple, destination: tuple) -> float:
    """Return unrounded haversine miles on a mean-radius sphere; reject invalid pairs."""
    start, end = _coordinates(*origin), _coordinates(*destination)
    if start is None or end is None:
        raise ValueError("Distance requires two valid coordinate pairs")
    lat1, lon1 = map(math.radians, start)
    lat2, lon2 = map(math.radians, end)
    haversine = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))


def resolve_distance_origin(
    request_id: str,
    beneficiary_id: str,
    records: LocationRecordSource,
    provider: GeocodingProvider,
    cache: CoordinateCache,
    *,
    resolver: Callable = resolve_beneficiary_location,
) -> GeocodingResult:
    """Bridge task 1 to task 2 once per request; retrieval failures remain explicit errors."""
    try:
        location = resolver(request_id, beneficiary_id, records)
        if location.status == "requires_geocoding":
            return geocode_beneficiary_profile(location, provider, cache)
        if location.status == "resolved":
            pair = _coordinates(*location.coordinates)
            if pair is not None:
                return GeocodingResult("resolved", pair)
            return GeocodingResult("error")
        return GeocodingResult("missing_location")
    except Exception:
        return GeocodingResult("error")


def distance_fields(status: str, distance: float | None = None) -> dict:
    """Supply the response contract, preserving zero and representing unavailability as None."""
    return {
        "distance": distance,
        "distance_unit": "miles",
        "distance_method": "straight_line",
        "distance_status": status,
    }


def enrich_organizations(
    organizations: Iterable[OrganizationAddress],
    origin: GeocodingResult,
    provider: GeocodingProvider,
    cache: CoordinateCache,
    *,
    coordinate_reader: Callable[[OrganizationAddress], CoordinateRecord | None] | None = None,
) -> list[dict]:
    """Enrich independently; only an explicit reader can supply organization coordinates.

    Never read generator latitude/longitude automatically: those may be city centroids.
    A reader returning None falls back to address geocoding. Invalid injected coordinates
    produce error rather than silently substituting a different location.
    """
    results = []
    for organization in organizations:
        record = dict(organization.record)
        try:
            fields = _organization_distance(organization, origin, provider, cache, coordinate_reader)
        except Exception:
            fields = distance_fields("error")
        record.update(fields)
        results.append(record)
    return results


def _organization_distance(organization, origin, provider, cache, coordinate_reader):
    """Resolve an individual organization and map coordinate outcomes to distance status."""
    if organization.online_only is True:
        return distance_fields("online")
    supplied = coordinate_reader(organization) if coordinate_reader is not None else None
    if supplied is not None:
        if not isinstance(supplied, CoordinateRecord):
            return distance_fields("error")
        pair = _coordinates(supplied.latitude, supplied.longitude)
        if pair is None:
            return distance_fields("error")
        destination = GeocodingResult("resolved", pair)
    else:
        if not organization.address:
            return distance_fields("unknown_location")
        if origin.status != "resolved":
            return distance_fields(STATUS_MAP[origin.status])
        destination = geocode_address(organization.address, provider, cache)
    if destination.status != "resolved":
        return distance_fields(STATUS_MAP[destination.status])
    if origin.status != "resolved":
        return distance_fields(STATUS_MAP[origin.status])
    return distance_fields("ok", straight_line_miles(origin.coordinates, destination.coordinates))
