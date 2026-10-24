"""Provider-neutral address geocoding; no default provider or cache is selected."""

from dataclasses import dataclass, replace
from typing import Literal, Protocol

from beneficiary_location import LocationResolution, _coordinates


@dataclass(frozen=True)
class CoordinateRecord:
    """Provider/cache pair in latitude, longitude order, validated at the boundary."""

    latitude: object
    longitude: object


class GeocodingProvider(Protocol):
    """Return None for unmatched addresses; raise for failures.

    Adapters must enforce their own network timeout and translate rate limits to
    GeocodingRateLimit and timeouts to TimeoutError. No retry is performed here.
    """

    def geocode(self, address: str) -> CoordinateRecord | None:
        """Find coordinates for supplied address text."""
        ...


class CoordinateCache(Protocol):
    """Address cache; backend, namespace, expiry and persistence are integration policy."""

    def get(self, address: str) -> CoordinateRecord | None:
        """Return cached coordinates or None on a miss; raise on failure."""
        ...

    def put(self, address: str, coordinates: CoordinateRecord) -> None:
        """Save a validated successful lookup; raise on failure."""
        ...


class GeocodingRateLimit(Exception):
    """Provider adapter reports a rate limit; caller may defer a later lookup."""


@dataclass(frozen=True)
class GeocodingResult:
    """Distinct outcomes with optional validated coordinates and cache diagnostics."""

    status: Literal["resolved", "missing_location", "not_found", "deferred", "timeout", "error"]
    coordinates: tuple[float, float] | None = None
    source: Literal["cache", "provider"] | None = None
    reason: str | None = None
    cache_error: Literal["read_error", "invalid_coordinates", "write_error"] | None = None


def _validated(record: CoordinateRecord | None) -> tuple[float, float] | None:
    """Reject malformed provider/cache records as well as invalid numeric pairs."""
    if not isinstance(record, CoordinateRecord):
        return None
    return _coordinates(record.latitude, record.longitude)


def geocode_address(
    address: object, provider: GeocodingProvider, cache: CoordinateCache
) -> GeocodingResult:
    """Check cache first; validate and save successes, preserving useful provider results.

    Only outer whitespace is trimmed: case, punctuation and interior whitespace
    remain intact to avoid conflating distinct addresses. Cache failure allows a
    provider lookup and is reported separately, never as an unmatched address.
    """
    if not isinstance(address, str) or not address.strip():
        return GeocodingResult("missing_location", reason="missing_address")
    address = address.strip()
    cache_error = None
    try:
        cached = cache.get(address)
        coordinates = _validated(cached)
        if coordinates is not None:
            return GeocodingResult("resolved", coordinates, "cache")
        if cached is not None:
            cache_error = "invalid_coordinates"
    except Exception:
        cache_error = "read_error"

    result = _call_provider(address, provider)
    if result.status == "resolved":
        try:
            cache.put(address, CoordinateRecord(*result.coordinates))
        except Exception:
            cache_error = "write_error"
    return replace(result, cache_error=cache_error)


def _call_provider(address: str, provider: GeocodingProvider) -> GeocodingResult:
    """Translate provider outcomes without exposing exception/address text."""
    try:
        record = provider.geocode(address)
    except GeocodingRateLimit:
        return GeocodingResult("deferred", reason="rate_limit")
    except TimeoutError:
        return GeocodingResult("timeout", reason="provider_timeout")
    except Exception:
        return GeocodingResult("error", reason="provider_error")
    if record is None:
        return GeocodingResult("not_found", reason="unmatched_address")
    coordinates = _validated(record)
    if coordinates is None:
        return GeocodingResult("error", reason="invalid_provider_coordinates")
    return GeocodingResult("resolved", coordinates, "provider")


def geocode_beneficiary_profile(
    location: LocationResolution, provider: GeocodingProvider, cache: CoordinateCache
) -> GeocodingResult:
    """Geocode only task 1's profile fallback; leave direct-coordinate resolution to task 1."""
    if location.status != "requires_geocoding" or location.source != "profile_address":
        raise ValueError("Expected beneficiary profile address requiring geocoding")
    return geocode_address(location.address, provider, cache)
