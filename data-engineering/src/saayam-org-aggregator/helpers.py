import boto3
import json
import math
import re
from aws_lambda_powertools.utilities import parameters
import pandas as pd
import pg8000


GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"

# --- All cached at module level, initialized once on cold start ---
lambda_client = boto3.client('lambda')

_creds = json.loads(parameters.get_parameter(
    '/dev/saayam/db/Virginia/Analytics/user',
    decrypt=True,
    max_age=3600
))
_db_name = _creds['DATABASE NAME']
_db_conn = pg8000.connect(
    host=_creds['HOST'],
    user=_creds['USERNAME'],
    password=_creds['PASSWORD'],
    database=_db_name,
    port=_creds['PORT'],
    ssl_context=True
)
# -----------------------------------------------------------------

# Address geocoding is deliberately provider-neutral. The issue owner has not
# selected a provider yet; once selected, wire it into _geocode_address_impl.
# Warm Lambda instances reuse successful results. This cache is process-local,
# so durable persistence still requires an approved storage choice.
_GEOCODE_CACHE = {}
_geocode_address_impl = None
MILES_PER_EARTH_RADIUS = 3958.7613


def parse_coordinates(value):
    """Parse supported coordinate values into (latitude, longitude).

    Accepts a mapping, a two-item (latitude, longitude) sequence, the issue's
    ``longitude:-... ,latitude:...`` format, and PostGIS ``POINT(lon lat)``.
    Invalid and missing coordinates return None; zero is a valid coordinate.
    """
    latitude = longitude = None
    if isinstance(value, dict):
        latitude = value.get("latitude", value.get("lat"))
        longitude = value.get("longitude", value.get("lon", value.get("lng")))
    elif isinstance(value, (tuple, list)) and len(value) == 2:
        latitude, longitude = value
    elif isinstance(value, str):
        text = value.strip()
        point = re.search(r"POINT\s*\(\s*([-+\d.eE]+)\s+([-+\d.eE]+)\s*\)", text, re.I)
        if point:
            longitude, latitude = point.group(1), point.group(2)
        else:
            lat_match = re.search(r"(?:latitude|lat)\s*[:=]\s*([-+\d.eE]+)", text, re.I)
            lon_match = re.search(r"(?:longitude|lon|lng)\s*[:=]\s*([-+\d.eE]+)", text, re.I)
            if lat_match and lon_match:
                latitude, longitude = lat_match.group(1), lon_match.group(1)
            else:
                # A bare pair is interpreted as latitude,longitude.
                pair = re.fullmatch(r"\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*", text)
                if pair:
                    latitude, longitude = pair.group(1), pair.group(2)
    if latitude is None or longitude is None:
        return None
    try:
        latitude, longitude = float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return latitude, longitude


def straight_line_distance_miles(origin, destination):
    """Return the great-circle distance in miles, or None for invalid points."""
    origin = parse_coordinates(origin)
    destination = parse_coordinates(destination)
    if origin is None or destination is None:
        return None
    lat1, lon1 = map(math.radians, origin)
    lat2, lon2 = map(math.radians, destination)
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    haversine = (math.sin(delta_lat / 2) ** 2
                 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2)
    # Clamp against floating point drift near antipodal points.
    haversine = min(1.0, max(0.0, haversine))
    return 2 * MILES_PER_EARTH_RADIUS * math.asin(math.sqrt(haversine))


def build_address(record):
    """Build a human-readable address from whichever real fields are present."""
    if not isinstance(record, dict):
        return ""

    def text_value(value):
        if value is None:
            return ""
        try:
            if pd.isna(value):
                return ""
        except (TypeError, ValueError):
            pass
        return str(value).strip()

    direct = text_value(record.get("address")) or text_value(record.get("full_address"))
    if direct:
        return direct
    fields = (
        "street", "addr_ln1", "addr_ln2", "addr_ln3", "city", "city_name",
        "state", "state_name", "state_code", "zip_code", "postal_code",
        "country", "country_name",
    )
    parts, seen = [], set()
    for field in fields:
        cleaned = text_value(record.get(field))
        if not cleaned:
            continue
        if cleaned.casefold() not in seen:
            parts.append(cleaned)
            seen.add(cleaned.casefold())
    return ", ".join(parts)


def geocode_address(address):
    """Resolve an address through an injected provider, if one is approved.

    Returns ``(coordinates, status)``. No provider is selected by this issue,
    so the default result is deferred rather than a guessed/default location.
    """
    address = (address or "").strip()
    if not address:
        return None, "unknown_location"
    cached = _GEOCODE_CACHE.get(address.casefold())
    if cached is not None:
        return cached, "ok"
    if _geocode_address_impl is None:
        return None, "deferred"
    try:
        coordinates = parse_coordinates(_geocode_address_impl(address))
    except TimeoutError:
        return None, "deferred"
    except Exception:
        return None, "error"
    if coordinates is None:
        return None, "not_found"
    _GEOCODE_CACHE[address.casefold()] = coordinates
    return coordinates, "ok"


def _table_columns(table_name):
    """Return the known column names for a table in the configured schema."""
    rows = pd.read_sql(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        _db_conn,
        params=(_db_name, table_name),
    )
    return set(rows.get("column_name", []))


def _first_row(sql, params=()):
    """Execute a parameterized lookup and return its first row as a dict."""
    rows = pd.read_sql(sql, _db_conn, params=params)
    return None if rows.empty else rows.iloc[0].to_dict()


def _get_request_and_beneficiary(request_id, beneficiary_id=None):
    """Read request location and beneficiary ID without relying on viewer data."""
    request_row = None
    if request_id:
        request_cols = _table_columns("requests")
        id_col = "req_id" if "req_id" in request_cols else "request_id" if "request_id" in request_cols else None
        beneficiary_col = "beneficiary_id" if "beneficiary_id" in request_cols else None
        if id_col:
            select_cols = [id_col]
            if "req_loc" in request_cols:
                select_cols.append("req_loc")
            if beneficiary_col:
                select_cols.append(beneficiary_col)
            elif "req_for_id" in request_cols:
                select_cols.append("req_for_id")
            request_row = _first_row(
                f"SELECT {', '.join(select_cols)} FROM {_db_name}.requests WHERE {id_col} = %s",
                (request_id,),
            )
    if request_row:
        beneficiary_id = (request_row.get("beneficiary_id") or request_row.get("req_for_id")
                          or beneficiary_id)
    return request_row or {}, beneficiary_id


def _get_user_coordinates(beneficiary_id):
    """Read the beneficiary's current PostGIS point (never the current viewer)."""
    if not beneficiary_id:
        return None
    location_cols = _table_columns("user_locations")
    id_col = ("beneficiary_id" if "beneficiary_id" in location_cols else
              "user_id" if "user_id" in location_cols else None)
    if id_col is None or "curr_loc" not in location_cols:
        return None
    updated_col = ("updated_at" if "updated_at" in location_cols else
                   "last_updated_at" if "last_updated_at" in location_cols else None)
    order_clause = f"ORDER BY {updated_col} DESC NULLS LAST " if updated_col else ""
    row = _first_row(
        f"SELECT ST_Y(curr_loc::geometry) AS latitude, "
        f"ST_X(curr_loc::geometry) AS longitude "
        f"FROM {_db_name}.user_locations WHERE {id_col} = %s AND curr_loc IS NOT NULL "
        f"{order_clause}LIMIT 1",
        (beneficiary_id,),
    )
    return parse_coordinates(row) if row else None


def _get_profile_address(beneficiary_id):
    """Build the beneficiary profile address using available plural tables."""
    if not beneficiary_id:
        return ""
    user_cols = _table_columns("users")
    state_cols = _table_columns("states")
    country_cols = _table_columns("countries")
    city_cols = _table_columns("cities")
    select = [f"u.{column} AS {column}" for column in
              ("addr_ln1", "addr_ln2", "addr_ln3", "city_name", "zip_code")
              if column in user_cols]
    joins = []
    if "state_id" in user_cols and {"state_id", "state_name"}.issubset(state_cols):
        select.append("s.state_name AS state_name")
        joins.append(f"LEFT JOIN {_db_name}.states s ON s.state_id = u.state_id")
    if "country_id" in user_cols and {"country_id", "country_name"}.issubset(country_cols):
        select.append("co.country_name AS country_name")
        joins.append(f"LEFT JOIN {_db_name}.countries co ON co.country_id = u.country_id")
    if "city_id" in user_cols and {"city_id", "city_name"}.issubset(city_cols):
        select = [item for item in select if item != "u.city_name AS city_name"]
        select.append("ci.city_name AS city_name")
        joins.append(f"LEFT JOIN {_db_name}.cities ci ON ci.city_id = u.city_id")
    if not select:
        return ""
    row = _first_row(
        f"SELECT {', '.join(select)} FROM {_db_name}.users u "
        f"{' '.join(joins)} WHERE u.user_id = %s",
        (beneficiary_id,),
    )
    return build_address(row or {})


def get_beneficiary_location(request_id=None, beneficiary_id=None):
    """Resolve request coordinates, then beneficiary current location, then address.

    Returns a dict with coordinates/status. Failures are contained so missing
    location data never prevents the organizations from being returned.
    """
    request_row = {}
    had_lookup_error = False
    try:
        request_row, beneficiary_id = _get_request_and_beneficiary(request_id, beneficiary_id)
    except Exception:
        # Continue with an explicitly supplied beneficiary ID if request lookup
        # is unavailable; never substitute a viewer or a default location.
        had_lookup_error = True
    coordinates = parse_coordinates(request_row.get("req_loc"))
    if coordinates is not None:
        return {"coordinates": coordinates, "status": "ok"}
    try:
        coordinates = _get_user_coordinates(beneficiary_id)
        if coordinates is not None:
            return {"coordinates": coordinates, "status": "ok"}
    except Exception:
        had_lookup_error = True
    addresses = [build_address({"address": request_row.get("req_loc")})]
    try:
        addresses.append(_get_profile_address(beneficiary_id))
    except Exception:
        had_lookup_error = True
    latest_geocode_status = None
    for address in dict.fromkeys(addresses):
        if not address:
            continue
        coordinates, status = geocode_address(address)
        if coordinates is not None:
            return {"coordinates": coordinates, "status": "ok"}
        latest_geocode_status = status
    if latest_geocode_status:
        return {"coordinates": None, "status": latest_geocode_status}
    status = "error" if had_lookup_error else "unknown_location"
    return {"coordinates": None, "status": status}


def add_organization_distances(organizations, beneficiary_location):
    """Attach distance fields while preserving every organization on failures."""
    result = organizations.copy()
    result["distance"] = None
    result["distance_unit"] = "miles"
    result["distance_method"] = "straight_line"
    result["distance_status"] = "unknown_location"
    beneficiary_coordinates = parse_coordinates(
        (beneficiary_location or {}).get("coordinates")
    )
    beneficiary_status = (beneficiary_location or {}).get("status", "unknown_location")
    for index, row in result.iterrows():
        values = row.to_dict()
        online_flags = (values.get("online_only"), values.get("is_online"))
        if any(str(flag).strip().casefold() in {"true", "1", "yes"}
               for flag in online_flags if flag is not None and not pd.isna(flag)):
            result.at[index, "distance_status"] = "online"
            continue
        if beneficiary_coordinates is None:
            result.at[index, "distance_status"] = beneficiary_status
            continue
        org_coordinates = parse_coordinates(values)
        if org_coordinates is None:
            address = build_address(values) or build_address({"address": values.get("location")})
            org_coordinates, status = geocode_address(address)
            if org_coordinates is None:
                result.at[index, "distance_status"] = status
                continue
        distance = straight_line_distance_miles(beneficiary_coordinates, org_coordinates)
        if distance is None:
            result.at[index, "distance_status"] = "error"
            continue
        result.at[index, "distance"] = round(distance, 1)
        result.at[index, "distance_status"] = "ok"
    return result

def get_orgs_from_db(location, category):
    try:
        df = pd.read_sql(
            f"SELECT * FROM {_db_name}.organizations "
            "WHERE mission = %s AND city_name = %s",
            _db_conn,
            params=(category, location),
        )
        df["db_or_ai"] = "db"
        return df
    except pg8000.DatabaseError as e:
        raise Exception(f'Database error: {str(e)}')
    except Exception as e:
        raise Exception(f'Error fetching from DB: {str(e)}')


def get_ai_orgs(subject, description, location):
    try:
        response = lambda_client.invoke(
            FunctionName=GEN_AI_LAMBDA,
            InvocationType='RequestResponse',
            Payload=json.dumps({
                "subject": subject,
                "description": description,
                "location": location
            })
        )
        payload = json.loads(response['Payload'].read())
        if payload.get('statusCode') != 200:
            raise Exception(f'GenAI Lambda returned error: {payload}')
        orgs = pd.DataFrame(payload['body']['organizations'])
        orgs["db_or_ai"] = "ai"
        return orgs
    except boto3.exceptions.Boto3Error as e:
        raise Exception(f'Failed to invoke GenAI Lambda: {str(e)}')
    except (KeyError, TypeError) as e:
        raise Exception(f'Unexpected response structure from GenAI Lambda: {str(e)}')
    except Exception as e:
        raise Exception(f'Error fetching AI orgs: {str(e)}')


def merge_organizations(db_organizations, genAI_organizations):
    """Normalize source-specific names while retaining address and rating data."""
    db_organizations = db_organizations.rename(columns={
        "org_name": "name", "city_name": "location", "phone": "contact"
    }).copy()
    genAI_organizations = genAI_organizations.rename(columns={
        "organization_name": "name"
    }).copy()
    for frame in (db_organizations, genAI_organizations):
        if "db_or_ai" not in frame.columns:
            frame["db_or_ai"] = "db" if frame is db_organizations else "ai"
        for column in ("name", "location", "contact", "email", "web_url",
                       "mission", "source"):
            if column not in frame.columns:
                frame[column] = None
    return pd.concat([db_organizations, genAI_organizations], ignore_index=True, sort=False)
