import math


def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate straight-line distance between two
    geographic coordinates using the Haversine formula.

    Returns distance in miles, or None for missing
    or invalid coordinates.
    """
    try:
        if any(value is None for value in (lat1, lon1, lat2, lon2)):
            return None

        lat1, lon1, lat2, lon2 = map(
            float, (lat1, lon1, lat2, lon2)
        )

        if not all(
            math.isfinite(value)
            for value in (lat1, lon1, lat2, lon2)
        ):
            return None

        if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90):
            return None

        if not (-180 <= lon1 <= 180 and -180 <= lon2 <= 180):
            return None

        earth_radius_miles = 3958.7613

        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)

        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        a = (
            math.sin(delta_lat / 2) ** 2
            + math.cos(lat1_rad)
            * math.cos(lat2_rad)
            * math.sin(delta_lon / 2) ** 2
        )

        a = min(1.0, max(0.0, a))

        c = 2 * math.atan2(
            math.sqrt(a),
            math.sqrt(1 - a)
        )

        return round(earth_radius_miles * c, 1)

    except (TypeError, ValueError, OverflowError):
        return None

def build_distance_result(
    beneficiary_coordinates,
    organization_coordinates,
):
    """
    Build the distance fields for an organization.

    Coordinates must be (latitude, longitude).
    """
    result = {
        "distance": None,
        "distance_unit": "miles",
        "distance_method": "straight_line",
        "distance_status": "unknown_location",
    }

    if beneficiary_coordinates is None:
        return result

    if organization_coordinates is None:
        return result

    try:
        distance = calculate_distance(
            beneficiary_coordinates[0],
            beneficiary_coordinates[1],
            organization_coordinates[0],
            organization_coordinates[1],
        )

        if distance is None:
            result["distance_status"] = "error"
            return result

        result["distance"] = distance
        result["distance_status"] = "ok"

    except (TypeError, ValueError, IndexError):
        result["distance_status"] = "error"

    return result