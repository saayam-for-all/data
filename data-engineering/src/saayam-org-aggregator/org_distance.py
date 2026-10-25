"""Add straight-line distance fields to organization records."""

from __future__ import annotations

import math
from typing import Any

from utils.geo import haversine_miles, parse_coordinates
from utils.geocoding import geocode_cached


def add_distance_fields(
    organizations,
    origin,
    geocoder=None,
):
    """Add distances using coordinates or a supplied address geocoder."""
    origin_coordinates = parse_coordinates(origin)

    if origin_coordinates is None and isinstance(origin, str):
        origin_coordinates = geocode_cached(origin, geocoder)

    for organization in organizations:
        if not isinstance(organization, dict):
            continue

        if _is_online_only(organization):
            organization.update(
                distance=None,
                distance_unit="miles",
                distance_status="online",
            )
            continue

        organization_coordinates = parse_coordinates(organization)

        if organization_coordinates is None:
            address = _organization_address(organization)
            if address:
                organization_coordinates = geocode_cached(address, geocoder)

        if origin_coordinates is None or organization_coordinates is None:
            organization.update(
                distance=None,
                distance_unit="miles",
                distance_status="unknown_location",
            )
            continue

        organization.update(
            distance=haversine_miles(
                origin_coordinates,
                organization_coordinates,
            ),
            distance_unit="miles",
            distance_status="ok",
        )

    return organizations


def _clean_address_part(value):
    """Convert a usable address value to text, or return None."""
    if value is None:
        return None

    try:
        if math.isnan(float(value)):
            return None
    except (TypeError, ValueError):
        pass

    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "null", "<na>", "nat"}:
        return None

    return text


def _organization_address(organization):
    """Build an address without missing values or duplicate city fields."""
    for key in ("full_address", "address", "street_address"):
        value = _clean_address_part(organization.get(key))
        if value:
            return value

    address_groups = (
        ("street",),
        ("city", "city_name", "location"),
        ("state", "state_name", "state_code"),
        ("zip_code", "postal_code", "zip"),
        ("country", "country_name"),
    )

    parts = []
    for keys in address_groups:
        for key in keys:
            value = _clean_address_part(organization.get(key))
            if value:
                parts.append(value)
                break

    return ", ".join(parts) or None

def _is_online_only(organization: dict[str, Any]) -> bool:
    """Return whether an organization is marked as online-only."""
    for key in ("is_online", "online_only"):
        value = organization.get(key)
        if value is True or str(value).strip().lower() == "true":
            return True

    return False

def sort_by_distance(
    organizations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sort nearest organizations first; keep unknown distances last."""
    def sort_key(organization: dict[str, Any]) -> tuple[int, float]:
        distance = organization.get("distance")

        if (
            isinstance(distance, (int, float))
            and not isinstance(distance, bool)
            and math.isfinite(distance)
        ):
            return (0, distance)

        return (1, math.inf)

    return sorted(organizations, key=sort_key)