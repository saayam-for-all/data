
import re


def parse_coordinates(value):
    """Parse request coordinates in longitude,latitude format."""
    if not isinstance(value, str):
        return None

    match = re.fullmatch(
        r"\s*longitude\s*:\s*([+-]?\d+(?:\.\d+)?)"
        r"\s*,\s*latitude\s*:\s*([+-]?\d+(?:\.\d+)?)\s*",
        value,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    longitude = float(match.group(1))
    latitude = float(match.group(2))

    if not (-180 <= longitude <= 180):
        return None

    if not (-90 <= latitude <= 90):
        return None

    return latitude, longitude


def resolve_request_location(req_loc, beneficiary_location=None):
    """
    Resolve the beneficiary/request location.

    Priority:
    1. Explicit coordinates from requests.req_loc.
    2. Beneficiary coordinates from user_locations.curr_loc.

    The beneficiary profile address fallback is handled
    separately when both coordinate sources are unavailable.
    """
    coordinates = parse_coordinates(req_loc)

    if coordinates is not None:
        return coordinates

    return beneficiary_location

def get_user_location(cursor, schema, user_id):
    """
    Retrieve a user's coordinates from user_locations.

    Returns (latitude, longitude), or None if unavailable.
    """
    if not user_id:
        return None

    query = f"""
        SELECT
            ST_Y(curr_loc::geometry) AS latitude,
            ST_X(curr_loc::geometry) AS longitude
        FROM {schema}.user_locations
        WHERE user_id = %s
          AND curr_loc IS NOT NULL
        LIMIT 1
    """

    cursor.execute(query, (user_id,))
    result = cursor.fetchone()

    if result is None:
        return None

    latitude, longitude = result

    if latitude is None or longitude is None:
        return None

    return latitude, longitude

def build_beneficiary_address(profile):
    """
    Build a beneficiary address from database profile fields.

    State and country values must be resolved to their
    actual names before calling this function.
    """
    if not isinstance(profile, dict):
        return None

    fields = (
        "addr_ln1",
        "addr_ln2",
        "addr_ln3",
        "city_name",
        "state_name",
        "zip_code",
        "country_name",
    )

    parts = [
        str(profile[field]).strip()
        for field in fields
        if profile.get(field) is not None
        and str(profile[field]).strip()
    ]

    return ", ".join(parts) if parts else None

def get_beneficiary_profile_address(cursor, schema, beneficiary_id):
    """
    Retrieve the beneficiary's profile address from the database.

    Returns an address string or None.
    """
    if not beneficiary_id:
        return None

    query = f"""
        SELECT
            u.addr_ln1,
            u.addr_ln2,
            u.addr_ln3,
            u.city_name,
            s.state_name,
            u.zip_code,
            c.country_name
        FROM {schema}.users AS u
        LEFT JOIN {schema}.states AS s
            ON u.state_id = s.state_id
        LEFT JOIN {schema}.countries AS c
            ON u.country_id = c.country_id
        WHERE u.user_id = %s
        LIMIT 1
    """

    cursor.execute(query, (beneficiary_id,))
    row = cursor.fetchone()

    if row is None:
        return None

    fields = (
        "addr_ln1",
        "addr_ln2",
        "addr_ln3",
        "city_name",
        "state_name",
        "zip_code",
        "country_name",
    )

    profile = dict(zip(fields, row))

    return build_beneficiary_address(profile)

def get_request_details(cursor, schema, request_id):
    """
    Retrieve request metadata needed to resolve
    the beneficiary's location.
    """
    if not request_id:
        return None

    query = f"""
        SELECT
            req_id,
            req_user_id,
            req_for_id,
            req_loc
        FROM {schema}.requests
        WHERE req_id = %s
        LIMIT 1
    """

    cursor.execute(query, (request_id,))
    row = cursor.fetchone()

    if row is None:
        return None

    return {
        "req_id": row[0],
        "req_user_id": row[1],
        "req_for_id": row[2],
        "req_loc": row[3],
    }

def resolve_beneficiary_location(
    cursor, schema, request, beneficiary_id=None
):
    """
    Resolve beneficiary location without using the viewer's location.

    Returns a dictionary containing coordinates or an address.
    """
    if not request:
        return {"coordinates": None, "address": None}

    coordinates = parse_coordinates(request.get("req_loc"))

    if coordinates is not None:
        return {"coordinates": coordinates, "address": None}

    if beneficiary_id is None and request.get("req_for_id") == 0:
        beneficiary_id = request.get("req_user_id")

    if not beneficiary_id:
        return {"coordinates": None, "address": None}

    coordinates = get_user_location(cursor, schema, beneficiary_id)

    if coordinates is not None:
        return {"coordinates": coordinates, "address": None}

    address = get_beneficiary_profile_address(
        cursor, schema, beneficiary_id
    )

    return {"coordinates": None, "address": address}