"""Database-independent beneficiary location resolution.

These records are an adapter contract, not database table/column definitions.
Importing this module does not initialize the aggregator's AWS or DB clients.
"""

from dataclasses import dataclass
from decimal import Decimal
import math
from numbers import Real
from typing import Literal, Protocol


@dataclass(frozen=True)
class RequestRecord:
    """Normalized request identity and optional coordinates from a trusted source."""

    request_id: str
    beneficiary_id: str
    latitude: object = None
    longitude: object = None


@dataclass(frozen=True)
class BeneficiaryLocationRecord:
    """Normalized current location belonging to a beneficiary."""

    beneficiary_id: str
    latitude: object = None
    longitude: object = None


@dataclass(frozen=True)
class ProfileAddressRecord:
    """Beneficiary's supplied address text; no country is inferred or appended."""

    beneficiary_id: str
    address: str | None = None


class LocationRecordSource(Protocol):
    """Injectable retrieval boundary; the real database adapter is task 5.

    Return None for absent records. Retrieval failures should raise, rather than
    masquerade as missing data. IDs must be normalized consistently by adapters.
    """

    def get_request(self, request_id: str) -> RequestRecord | None:
        """Retrieve a request and its beneficiary association."""
        ...

    def get_beneficiary_location(self, beneficiary_id: str) -> BeneficiaryLocationRecord | None:
        """Retrieve the beneficiary's current coordinates."""
        ...

    def get_profile_address(self, beneficiary_id: str) -> ProfileAddressRecord | None:
        """Retrieve the beneficiary's profile address."""
        ...


@dataclass(frozen=True)
class LocationResolution:
    """Explicit coordinate, geocoding-required, or unresolved outcome."""

    status: Literal["resolved", "requires_geocoding", "unresolved"]
    source: Literal["request", "beneficiary_current", "profile_address"] | None = None
    coordinates: tuple[float, float] | None = None
    address: str | None = None
    reason: str | None = None


def _coordinate(value: object, limit: int) -> float | None:
    """Accept finite numbers/numeric strings in range, including zero, excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal, str)):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if math.isfinite(number) and -limit <= number <= limit else None


def _coordinates(latitude: object, longitude: object) -> tuple[float, float] | None:
    """Validate a complete pair; never combine coordinates from different sources."""
    lat, lon = _coordinate(latitude, 90), _coordinate(longitude, 180)
    return (lat, lon) if lat is not None and lon is not None else None


def resolve_beneficiary_location(
    request_id: str, beneficiary_id: str, records: LocationRecordSource
) -> LocationResolution:
    """Resolve request coordinates, current coordinates, then an address to geocode.

    A matching request association is mandatory, even for fallbacks. Mismatched
    records fail closed. Viewer/device location is deliberately absent from this
    interface. No geocoder or external service is called by this task.
    """
    if not request_id or not beneficiary_id:
        return LocationResolution("unresolved", reason="missing_identity")
    request = records.get_request(request_id)
    if request is None:
        return LocationResolution("unresolved", reason="missing_request")
    if request.request_id != request_id or request.beneficiary_id != beneficiary_id:
        return LocationResolution("unresolved", reason="request_beneficiary_mismatch")
    coordinates = _coordinates(request.latitude, request.longitude)
    if coordinates is not None:
        return LocationResolution("resolved", "request", coordinates)

    current = records.get_beneficiary_location(beneficiary_id)
    if current is not None:
        if current.beneficiary_id != beneficiary_id:
            return LocationResolution("unresolved", reason="beneficiary_location_mismatch")
        coordinates = _coordinates(current.latitude, current.longitude)
        if coordinates is not None:
            return LocationResolution("resolved", "beneficiary_current", coordinates)

    profile = records.get_profile_address(beneficiary_id)
    if profile is not None:
        if profile.beneficiary_id != beneficiary_id:
            return LocationResolution("unresolved", reason="profile_beneficiary_mismatch")
        if isinstance(profile.address, str) and profile.address.strip():
            return LocationResolution(
                "requires_geocoding", "profile_address", address=profile.address.strip()
            )
    return LocationResolution("unresolved", reason="no_usable_beneficiary_location")
