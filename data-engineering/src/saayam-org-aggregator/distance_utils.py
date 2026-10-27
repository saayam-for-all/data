import math


def haversine_miles(lat1, lon1, lat2, lon2):
    """
    Calculate straight-line distance between two GPS coordinates.

    Args:
        lat1, lon1: Beneficiary latitude and longitude
        lat2, lon2: Organization latitude and longitude

    Returns:
        Distance in miles, rounded to 2 decimal places.
    """
    lat1, lon1, lat2, lon2 = map(
        float, (lat1, lon1, lat2, lon2)
    )

    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90):
        raise ValueError("Latitude must be between -90 and 90")

    if not (-180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        raise ValueError("Longitude must be between -180 and 180")

    radius_miles = 3958.7613

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    a = min(1.0, max(0.0, a))

    distance = 2 * radius_miles * math.asin(math.sqrt(a))

    return round(distance, 2)
import re


def parse_point(value):
    """
    Parse PostgreSQL EWKT POINT coordinates.

    Example:
        SRID=4326;POINT(-72.9279 41.3083)

    Returns:
        (latitude, longitude), or None if invalid.
    """
    if not isinstance(value, str):
        return None

    match = re.fullmatch(
        r"\s*(?:SRID=4326;)?POINT\s*\(\s*"
        r"([-+]?\d+(?:\.\d+)?)\s+"
        r"([-+]?\d+(?:\.\d+)?)\s*\)\s*",
        value,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    longitude = float(match.group(1))
    latitude = float(match.group(2))

    if not (-90 <= latitude <= 90):
        return None

    if not (-180 <= longitude <= 180):
        return None

    return latitude, longitude

def parse_request_location(value):
    """
    Parse a request location such as:
    longitude:-72.9279,latitude:41.3083

    Returns (latitude, longitude), or None.
    """
    if not isinstance(value, str):
        return None

    try:
        parts = dict(
            item.strip().split(":", 1)
            for item in value.split(",")
        )

        latitude = float(parts["latitude"].strip())
        longitude = float(parts["longitude"].strip())

        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return latitude, longitude

    except (ValueError, KeyError):
        pass

    return None

def add_organization_distance(organization, beneficiary_coords, organization_coords):
    """
    Add distance information to an organization.

    Coordinates must be (latitude, longitude).
    If coordinates are unavailable, distance is None.
    """
    result = organization.copy()

    result["distance"] = None
    result["distance_unit"] = "miles"
    result["distance_method"] = "straight_line"
    result["distance_status"] = "unknown_location"

    if beneficiary_coords is None or organization_coords is None:
        return result

    try:
        result["distance"] = haversine_miles(
            beneficiary_coords[0],
            beneficiary_coords[1],
            organization_coords[0],
            organization_coords[1],
        )
        result["distance_status"] = "ok"

    except (ValueError, TypeError, IndexError):
        result["distance_status"] = "error"

    return result