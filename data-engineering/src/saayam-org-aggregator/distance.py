
"""Utilities for geocoding addresses and calculating distances."""

import hashlib
import json
import math
import os
import re

import pandas as pd


EARTH_RADIUS_MILES = 3958.7613

# Successful results are reused during warm Lambda invocations.
_GEOCODE_CACHE = {}


def haversine_distance(lat1, lon1, lat2, lon2):
    """Return straight-line distance between two coordinates in miles."""
    coordinates = tuple(
        float(value) for value in (lat1, lon1, lat2, lon2)
    )

    if not all(math.isfinite(value) for value in coordinates):
        raise ValueError("Coordinates must be finite numbers")

    lat1, lon1, lat2, lon2 = coordinates

    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90):
        raise ValueError("Latitude must be between -90 and 90")

    if not (-180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        raise ValueError("Longitude must be between -180 and 180")

    lat1, lon1, lat2, lon2 = map(
        math.radians, (lat1, lon1, lat2, lon2)
    )

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )
    a = min(1.0, max(0.0, a))

    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def parse_coordinates(location):
    """Parse latitude and longitude from a labeled coordinate string."""
    if not isinstance(location, str) or not location.strip():
        return None

    text = location.strip().lower()
    lat_match = re.search(
        r"latitude\s*[:=]\s*(-?\d+(?:\.\d+)?)", text
    )
    lon_match = re.search(
        r"longitude\s*[:=]\s*(-?\d+(?:\.\d+)?)", text
    )

    if not lat_match or not lon_match:
        return None

    try:
        return validate_coordinates(
            lat_match.group(1), lon_match.group(1)
        )
    except (TypeError, ValueError):
        return None


def validate_coordinates(latitude, longitude):
    """Return validated coordinates or raise ValueError."""
    latitude = float(latitude)
    longitude = float(longitude)

    if not math.isfinite(latitude) or not math.isfinite(longitude):
        raise ValueError("Coordinates must be finite numbers")
    if not -90 <= latitude <= 90:
        raise ValueError("Invalid latitude")
    if not -180 <= longitude <= 180:
        raise ValueError("Invalid longitude")

    return {"latitude": latitude, "longitude": longitude}


def _address_key(address):
    """Hash normalized addresses so raw addresses aren't cache keys."""
    normalized = " ".join(address.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _dynamodb_table():
    """Return the optional geocoding cache table, if configured."""
    import boto3
    table_name = os.getenv("GEOCODE_CACHE_TABLE")
    if not table_name:
        return None
    return boto3.resource("dynamodb").Table(table_name)


def _read_cache(address_key):
    """Read an optional DynamoDB cache entry; ignore cache failures."""
    try:
        table = _dynamodb_table()
        if table is None:
            return None

        item = table.get_item(
            Key={"address_key": address_key}
        ).get("Item")

        if item:
            return validate_coordinates(
                item["latitude"], item["longitude"]
            )
    except Exception:
        pass

    return None


def _write_cache(address_key, coordinates):
    """Write a successful result to the optional DynamoDB cache."""
    try:
        table = _dynamodb_table()
        if table is not None:
            table.put_item(Item={
                "address_key": address_key,
                "latitude": coordinates["latitude"],
                "longitude": coordinates["longitude"],
            })
    except Exception:
        # Cache failures must not break the organization response.
        pass


def geocode_address(address):
    """Resolve an address using an optional configured geocoder Lambda."""
    if not isinstance(address, str) or not address.strip():
        return None

    address = " ".join(address.split())
    key = _address_key(address)

    if key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[key].copy()

    cached = _read_cache(key)
    if cached is not None:
        _GEOCODE_CACHE[key] = cached
        return cached.copy()

    function_name = os.getenv("GEOCODER_LAMBDA_NAME")
    if not function_name:
        return None

    try:
        import boto3
        response = boto3.client("lambda").invoke(
            FunctionName=function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps({"address": address}),
        )

        if response.get("FunctionError"):
            return None

        payload = json.loads(response["Payload"].read())

        # Support API Gateway-style Lambda responses.
        if isinstance(payload, dict) and "body" in payload:
            if payload.get("statusCode", 200) != 200:
                return None
            payload = payload["body"]
            if isinstance(payload, str):
                payload = json.loads(payload)

        if not isinstance(payload, dict):
            return None

        coordinates = payload.get("coordinates", payload)
        if not isinstance(coordinates, dict):
            return None

        result = validate_coordinates(
            coordinates["latitude"],
            coordinates["longitude"],
        )

        _GEOCODE_CACHE[key] = result
        _write_cache(key, result)
        return result.copy()

    except Exception:
        # Geocoding is optional; unavailable results are deferred.
        return None


def _present(value):
    """Treat None, NaN, and blank strings as missing."""
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return bool(str(value).strip())


def organization_address(organization):
    """Build a geocoding address from available organization fields."""
    parts = []
    for field in ("street", "location", "state_id", "zip_code"):
        value = organization.get(field)
        if _present(value):
            parts.append(str(value).strip())

    return ", ".join(parts) or None


def add_organization_distances(organizations, origin):
    """Add distance metadata without dropping organization rows."""
    result = organizations.copy()

    result["distance"] = None
    result["distance_unit"] = "miles"
    result["distance_method"] = "straight_line"
    result["distance_status"] = "unknown_location"

    for index, organization in result.iterrows():
        if (
            organization.get("db_or_ai") == "ai"
            and not _present(organization.get("location"))
        ):
            result.at[index, "distance_status"] = "online"
            continue

        if not origin:
            result.at[index, "distance_status"] = "unknown_location"
            continue

        try:
            org_lat = organization.get("latitude")
            org_lon = organization.get("longitude")

            if _present(org_lat) and _present(org_lon):
                org_coordinates = validate_coordinates(org_lat, org_lon)
            else:
                address = organization_address(organization)
                org_coordinates = geocode_address(address) if address else None

            if org_coordinates is None:
                result.at[index, "distance_status"] = "deferred"
                continue

            origin_coordinates = validate_coordinates(
                origin["latitude"], origin["longitude"]
            )

            result.at[index, "distance"] = haversine_distance(
                origin_coordinates["latitude"],
                origin_coordinates["longitude"],
                org_coordinates["latitude"],
                org_coordinates["longitude"],
            )
            result.at[index, "distance_status"] = "ok"

        except (KeyError, TypeError, ValueError, OverflowError):
            result.at[index, "distance_status"] = "error"

    return result
