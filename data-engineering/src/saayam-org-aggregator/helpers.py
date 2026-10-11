import json
import logging
import math
import os

import pandas as pd

logger = logging.getLogger(__name__)

GEN_AI_LAMBDA = "More_Org_GenAI_Py_v3126"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# CSV mock-data directory.  Override with the MOCK_DATA_DIR environment
# variable for local testing (e.g. point it at
# data-analytics/mock-data-generation/).
DATA_DIR = os.environ.get(
    "MOCK_DATA_DIR",
    os.path.join(os.path.dirname(__file__), "mock_data"),
)

# Final response columns (original + distance fields).
ORG_COLUMNS = [
    "name",
    "organization_type",
    "collaborator",
    "location",
    "size",
    "rating",
    "contact",
    "email",
    "web_url",
    "mission",
    "source",
    "distance",
    "distance_unit",
    "distance_method",
    "distance_status",
]

# Maps raw DB/CSV column names -> final response shape.
DB_RENAME = {
    "org_name": "name",
    "org_type": "organization_type",
    "is_collaborator": "collaborator",
    "org_rating": "rating",
    "org_size": "size",
    "web_url": "web_url",
    "phone": "contact",
}

# Maps raw GenAI payload column names -> final response shape.
AI_RENAME = {
    "organization_name": "name",
    "org_type": "organization_type",
    "is_collaborator": "collaborator",
    "contact": "contact",
    "web_url": "web_url",
}


# ---------------------------------------------------------------------------
# CSV data loading
# ---------------------------------------------------------------------------


def _load_csv(filename):
    """Load a CSV from the data directory.  Returns empty DataFrame if the
    file is missing so the caller can degrade gracefully."""
    path = os.path.join(DATA_DIR, filename)
    try:
        return pd.read_csv(path)
    except FileNotFoundError:
        logger.warning("CSV not found: %s", path)
        return pd.DataFrame()
    except Exception as e:
        logger.warning("Error loading %s: %s", path, e)
        return pd.DataFrame()


def _join_parts(parts, sep=", "):
    """Join values with *sep*, skipping None, NaN, and empty strings."""
    cleaned = [
        str(p).strip()
        for p in parts
        if p is not None
        and not (isinstance(p, float) and pd.isna(p))
        and str(p).strip()
        and str(p).strip().upper() != "NULL"
    ]
    return sep.join(cleaned) if cleaned else None


def _empty_ai_frame():
    """Return an empty AI DataFrame with the final response columns."""
    return pd.DataFrame(columns=ORG_COLUMNS)


# ---------------------------------------------------------------------------
# Geocoding — pluggable provider
# ---------------------------------------------------------------------------

# In-memory cache so repeated lookups within a single Lambda invocation
# are free.  This satisfies the caching requirement in the task spec.
_geocode_cache = {}


def geocode_address(address):
    """Convert an address string to (latitude, longitude) or None.

    This is a **stub** implementation.  The geocoding provider has not
    been finalized, so no external service is called.

    When a provider is chosen (e.g. Google Maps, AWS Location Service,
    OpenCage), replace the body of this function.  The rest of the
    codebase calls only this function, so the swap is a single-file
    change.
    """
    if not address:
        return None

    cache_key = address.strip().lower()
    if cache_key in _geocode_cache:
        return _geocode_cache[cache_key]

    coords = _stub_geocode(address)
    _geocode_cache[cache_key] = coords
    return coords


def _stub_geocode(address):
    """Stub geocoder — returns None until a real provider is plugged in.

    For local testing with mock data, you can add known city coordinates
    here to demonstrate the distance calculation flow end-to-end.
    """
    return None


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

_EARTH_RADIUS_MILES = 3958.8


def haversine_miles(lat1, lon1, lat2, lon2):
    """Return straight-line distance in miles between two coordinates."""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return _EARTH_RADIUS_MILES * 2 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Coordinate parsing
# ---------------------------------------------------------------------------


def _parse_coordinates(loc_string):
    """Try to extract (lat, lon) from a coordinate string.

    Handles formats like:
      "longitude:-121.9780,latitude:37.7799"
      "latitude:37.7799,longitude:-121.9780"
      "37.7799,-121.9780"

    Returns (lat, lon) tuple or None.
    """
    if not loc_string or not isinstance(loc_string, str):
        return None

    loc_string = loc_string.strip()

    # --- "key:value" format (e.g. "longitude:-121.98,latitude:37.78") ---
    if "latitude:" in loc_string.lower() and "longitude:" in loc_string.lower():
        parts = {}
        for part in loc_string.split(","):
            part = part.strip()
            if ":" in part:
                key, val = part.split(":", 1)
                parts[key.strip().lower()] = val.strip()
        try:
            lat = float(parts["latitude"])
            lon = float(parts["longitude"])
            return (lat, lon)
        except (ValueError, TypeError, KeyError):
            return None

    # --- Plain "lat,lon" format ---
    try:
        pieces = loc_string.split(",")
        if len(pieces) == 2:
            lat = float(pieces[0].strip())
            lon = float(pieces[1].strip())
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)
    except (ValueError, TypeError):
        pass

    return None


# ---------------------------------------------------------------------------
# Beneficiary location (fallback chain)
# ---------------------------------------------------------------------------


def get_beneficiary_location(beneficiary_id, request_id):
    """Determine the beneficiary's location using the priority chain.

    1. Request location  — requests.req_loc  (coordinates if available).
    2. User location     — user_locations.curr_loc.
    3. Profile address   — users + cities/states/countries, then geocode.
    4. Unavailable       — (None, None, None, "unknown_location").

    Do NOT fall back to a default like "United States".

    Returns
    -------
    (location_string, city, coordinates_or_None, status)
        *city* is extracted for organization filtering.
        *coordinates* is a (lat, lon) tuple when coordinates are known.
        *status* is "ok" or "unknown_location".
    """
    requests_df = _load_csv("requests.csv")

    # --- Step 1: Request location (coordinates) --------------------------
    if not requests_df.empty:
        req_row = requests_df[
            (requests_df["req_id"] == request_id)
            & (requests_df["beneficiary_id"] == beneficiary_id)
        ]
        if not req_row.empty:
            req_loc = req_row.iloc[0].get("req_loc")
            if pd.notna(req_loc) and str(req_loc).strip():
                loc_str = str(req_loc).strip()
                coords = _parse_coordinates(loc_str)
                if coords:
                    return loc_str, None, coords, "ok"
                # Not coordinates — treat as an address string.
                return loc_str, None, None, "ok"

    # --- Step 2: User location (user_locations.curr_loc) -----------------
    user_locations_df = _load_csv("user_locations.csv")
    if not user_locations_df.empty and "user_id" in user_locations_df.columns:
        uloc_row = user_locations_df[
            user_locations_df["user_id"] == beneficiary_id
        ]
        if not uloc_row.empty:
            curr_loc = uloc_row.iloc[0].get("curr_loc")
            if pd.notna(curr_loc) and str(curr_loc).strip():
                loc_str = str(curr_loc).strip()
                coords = _parse_coordinates(loc_str)
                if coords:
                    return loc_str, None, coords, "ok"
                return loc_str, None, None, "ok"

    # --- Step 3: Profile address -----------------------------------------
    users_df = _load_csv("users.csv")
    if not users_df.empty:
        user_row = users_df[users_df["user_id"] == beneficiary_id]
        if not user_row.empty:
            u = user_row.iloc[0]
            city_name = u.get("city_name")

            # Try to resolve a human-readable state name.
            state_name = u.get("state_id")
            state_id = u.get("state_id")
            if pd.notna(state_id):
                states_df = _load_csv("states.csv")
                if not states_df.empty and "state_id" in states_df.columns:
                    s_row = states_df[states_df["state_id"] == state_id]
                    if not s_row.empty and "state_name" in s_row.columns:
                        state_name = s_row.iloc[0].get(
                            "state_name", state_id
                        )

            location = _join_parts(
                [
                    u.get("addr_ln1"),
                    u.get("addr_ln2"),
                    city_name,
                    state_name,
                    u.get("zip_code"),
                ]
            )
            if location:
                return location, city_name, None, "ok"

    # --- Step 4: Location not available ----------------------------------
    return None, None, None, "unknown_location"


# ---------------------------------------------------------------------------
# Request info
# ---------------------------------------------------------------------------


def get_req_info(request_id, beneficiary_id):
    """Return category, description, and subject for one request."""
    requests_df = _load_csv("requests.csv")
    help_cat_df = _load_csv("help_categories.csv")

    if requests_df.empty:
        raise ValueError("Cannot load requests data — requests.csv not found")

    req_row = requests_df[
        (requests_df["req_id"] == request_id)
        & (requests_df["beneficiary_id"] == beneficiary_id)
    ]

    if req_row.empty:
        raise ValueError(
            f"No request found with req_id={request_id} "
            f"and beneficiary_id={beneficiary_id}"
        )

    req = req_row.iloc[0]
    cat_id = req.get("req_cat_id")

    cat_name = None
    if pd.notna(cat_id) and not help_cat_df.empty:
        cat_row = help_cat_df[help_cat_df["cat_id"] == cat_id]
        if not cat_row.empty:
            cat_name = cat_row.iloc[0].get("cat_name")

    return {
        "category": cat_name or str(cat_id),
        "description": req.get("req_desc"),
        "subject": req.get("req_subj"),
    }


# ---------------------------------------------------------------------------
# Organization retrieval
# ---------------------------------------------------------------------------


def get_orgs_from_db(location, category):
    """Find organizations from CSV mock data.

    In the real Lambda this queries the DB by category via org_skills →
    help_categories.  The CSV mock data may not have an org_skills table,
    so we return all organizations.  Category- and city-based filtering
    can be added when the mock data supports it.
    """
    orgs_df = _load_csv("organizations.csv")

    if orgs_df.empty:
        return pd.DataFrame()

    orgs_df["source"] = "db"

    # Build a display location string.
    orgs_df["location"] = orgs_df.apply(
        lambda r: _join_parts([r.get("city_name"), r.get("state_id")]),
        axis=1,
    )

    # Build a full address for geocoding.
    orgs_df["full_address"] = orgs_df.apply(
        lambda r: _join_parts(
            [
                r.get("street"),
                r.get("city_name"),
                r.get("state_id"),
                r.get("zip_code"),
            ]
        ),
        axis=1,
    )

    return orgs_df


def get_ai_orgs(subject, description, location, category):
    """Placeholder for the GenAI Lambda call.

    In the real Lambda this invokes GEN_AI_LAMBDA.  For CSV mock data we
    return an empty DataFrame — the DB/CSV organizations are sufficient
    for testing the distance-calculation flow.
    """
    return _empty_ai_frame()


# ---------------------------------------------------------------------------
# Distance calculation
# ---------------------------------------------------------------------------


def calculate_distances(
    orgs_df, beneficiary_location, beneficiary_coords, ben_status
):
    """Add distance columns to every organization row.

    Distance calculation must **never** break the Organizations API.
    Organizations are always returned even if distance fails.

    Parameters
    ----------
    orgs_df : DataFrame
        Organizations (DB or AI).
    beneficiary_location : str | None
        Human-readable beneficiary address / location string.
    beneficiary_coords : tuple | None
        (lat, lon) if already known, else None.
    ben_status : str
        "ok" or "unknown_location".
    """
    if orgs_df is None or orgs_df.empty:
        return orgs_df

    distances = []
    units = []
    methods = []
    statuses = []

    # --- Beneficiary location unknown → mark all orgs -----------------
    if ben_status == "unknown_location" or (
        not beneficiary_location and beneficiary_coords is None
    ):
        for _ in range(len(orgs_df)):
            distances.append(None)
            units.append("miles")
            methods.append("straight_line")
            statuses.append("unknown_location")

        orgs_df = orgs_df.copy()
        orgs_df["distance"] = distances
        orgs_df["distance_unit"] = units
        orgs_df["distance_method"] = methods
        orgs_df["distance_status"] = statuses
        return orgs_df

    # --- Resolve beneficiary coordinates ------------------------------
    ben_lat, ben_lon = None, None

    if beneficiary_coords:
        ben_lat, ben_lon = beneficiary_coords
    elif beneficiary_location:
        geo = geocode_address(beneficiary_location)
        if geo:
            ben_lat, ben_lon = geo

    # If beneficiary cannot be geocoded, mark all orgs as not_found.
    if ben_lat is None or ben_lon is None:
        for _ in range(len(orgs_df)):
            distances.append(None)
            units.append("miles")
            methods.append("straight_line")
            statuses.append("not_found")

        orgs_df = orgs_df.copy()
        orgs_df["distance"] = distances
        orgs_df["distance_unit"] = units
        orgs_df["distance_method"] = methods
        orgs_df["distance_status"] = statuses
        return orgs_df

    # --- Per-organization distance ------------------------------------
    for _, row in orgs_df.iterrows():
        try:
            org_address = row.get("full_address") or row.get("location")
            org_coords = geocode_address(org_address) if org_address else None

            if org_coords is None:
                distances.append(None)
                units.append("miles")
                methods.append("straight_line")
                statuses.append("not_found")
            else:
                org_lat, org_lon = org_coords
                dist = round(
                    haversine_miles(ben_lat, ben_lon, org_lat, org_lon), 1
                )
                distances.append(dist)
                units.append("miles")
                methods.append("straight_line")
                statuses.append("ok")

        except Exception as e:
            logger.warning("Distance calc error for org: %s", e)
            distances.append(None)
            units.append("miles")
            methods.append("straight_line")
            statuses.append("error")

    orgs_df = orgs_df.copy()
    orgs_df["distance"] = distances
    orgs_df["distance_unit"] = units
    orgs_df["distance_method"] = methods
    orgs_df["distance_status"] = statuses
    return orgs_df


# ---------------------------------------------------------------------------
# Merge & normalize
# ---------------------------------------------------------------------------


def merge_organizations(db_organizations, genAI_organizations):
    """Normalize DB and AI organizations and combine them."""

    def _normalize(df, rename_map):
        if df is None or df.empty:
            return pd.DataFrame(columns=ORG_COLUMNS)
        normalized = df.rename(columns=rename_map).copy()
        return normalized.reindex(columns=ORG_COLUMNS)

    try:
        db_orgs = _normalize(db_organizations, DB_RENAME)
        ai_orgs = _normalize(genAI_organizations, AI_RENAME)
        return pd.concat([db_orgs, ai_orgs], ignore_index=True)

    except Exception as e:
        raise Exception(
            f"Failed to merge organization results: {e}"
        ) from e
