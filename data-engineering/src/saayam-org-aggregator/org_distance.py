"""Distance from the beneficiary/request location to each recommended org (#433).

The origin is always the beneficiary/request location, never the person
viewing the request. It is resolved in this order:

1. ``requests.req_loc`` when it contains coordinates
2. ``user_locations.curr_loc`` for the request's beneficiary
3. the beneficiary's profile address (users + cities/states/countries),
   geocoded
4. otherwise ``distance_status = "unknown_location"``. There is no default
   location.

Each organization gets four fields. All existing fields are left untouched:

    distance         float (miles, 1 decimal) or None. Unknown is never 0.
    distance_unit    "miles"
    distance_method  "straight_line" (not driving distance or travel time)
    distance_status  ok | online | unknown_location | not_found | deferred | error

Nothing in this module raises to the caller. Any failure is reported
through ``distance_status`` and the organization is still returned.
"""

from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from utils.geo import Coordinates, haversine_distance, parse_coordinates
from utils.geocoding import (
    GEOCODE_NO_ADDRESS,
    GEOCODE_OK,
    CoordinateCache,
    GeocodeResult,
    GeocodingProvider,
    LookupBudget,
    geocode_address,
)

logger = logging.getLogger(__name__)

DISTANCE_UNIT = "miles"
DISTANCE_METHOD = "straight_line"
DISTANCE_DECIMALS = 1

STATUS_OK = "ok"
STATUS_ONLINE = "online"
STATUS_UNKNOWN_LOCATION = "unknown_location"
STATUS_NOT_FOUND = "not_found"
STATUS_DEFERRED = "deferred"
STATUS_ERROR = "error"

DISTANCE_FIELDS = ("distance", "distance_unit", "distance_method", "distance_status")

# Internal keys that carry each org's precomputed location through
# merge_organizations(), which otherwise drops street/zip/state. Both are
# removed from the response by add_distance_fields() / apply_distances().
ADDRESS_KEY = "_distance_address"
LOCATION_STATUS_KEY = "_distance_location_status"
PRIVATE_KEYS = (ADDRESS_KEY, LOCATION_STATUS_KEY)

_UNSET = object()

DEFAULT_SCHEMA = "virginia_dev_saayam_rdbms"

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INTERNAL_ID = re.compile(r"^[\d.\-]+$")
_MISSING = {"", "nan", "none", "null", "<na>", "nat", "n/a", "na", "unknown", "not available", "-", "--"}
_ONLINE_WORDS = re.compile(
    r"\b(online|virtual|remote|web[\s-]*based|internet|digital|e-?services|only|services?|and|or)\b|[/&,()\-]",
    re.IGNORECASE,
)
_ONLINE_HINT = re.compile(r"\b(online|virtual|remote|web[\s-]*based|internet)\b", re.IGNORECASE)
_COARSE_LOCATIONS = {
    "nationwide", "national", "worldwide", "global", "international", "various",
    "multiple locations", "multiple", "everywhere", "anywhere",
    "united states", "united states of america", "usa", "us", "u s", "u s a", "america",
    "canada", "india", "united kingdom", "uk", "england", "australia", "mexico",
    "germany", "france", "ireland",
}


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SaayamTables:
    """Schema and table names used for location lookups (current plural names)."""

    schema: str = DEFAULT_SCHEMA
    requests: str = "requests"
    users: str = "users"
    user_locations: str = "user_locations"
    cities: str = "cities"
    states: str = "states"
    countries: str = "countries"

    def __post_init__(self) -> None:
        for name in ("schema", "requests", "users", "user_locations", "cities", "states", "countries"):
            if not _IDENTIFIER.match(getattr(self, name) or ""):
                raise ValueError(f"Invalid SQL identifier for {name}: {getattr(self, name)!r}")

    def q(self, table_attr: str) -> str:
        """Schema-qualified table name, e.g. ``virginia_dev_saayam_rdbms.requests``."""
        return f"{self.schema}.{getattr(self, table_attr)}"

    @classmethod
    def from_env(cls, default_schema: Optional[str] = None) -> "SaayamTables":
        """Read DB_SCHEMA and optional TABLE_* overrides from the environment."""
        return cls(
            schema=os.getenv("DB_SCHEMA") or default_schema or DEFAULT_SCHEMA,
            requests=os.getenv("TABLE_REQUESTS", "requests"),
            users=os.getenv("TABLE_USERS", "users"),
            user_locations=os.getenv("TABLE_USER_LOCATIONS", "user_locations"),
            cities=os.getenv("TABLE_CITIES", "cities"),
            states=os.getenv("TABLE_STATES", "states"),
            countries=os.getenv("TABLE_COUNTRIES", "countries"),
        )


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def clean_value(value: Any) -> Optional[str]:
    """Return a trimmed string, or None for empty/NaN/placeholder values."""
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            value = int(value)
    text = str(value).strip()
    return None if text.lower() in _MISSING else text


def humanize_name(value: Optional[str]) -> Optional[str]:
    """Turn lookup-table names like ``UNITED_STATES_OF_AMERICA`` into ``United States Of America``.

    Short all-caps codes such as "VA" or "USA" are left alone.
    """
    if not value:
        return value
    if "_" in value or (value.isupper() and len(value) > 3):
        return " ".join(part for part in value.replace("_", " ").split() if part).title()
    return value


def compose_address(
    street: Optional[str] = None,
    city: Optional[str] = None,
    state: Optional[str] = None,
    zip_code: Optional[str] = None,
    country: Optional[str] = None,
) -> Optional[str]:
    """Join address parts into one geocodable line.

    Returns None when the parts are too coarse to locate a place: a country
    or state on its own is not enough, so nothing ever falls back to e.g.
    "United States".
    """
    street, city, state, zip_code, country = (clean_value(v) for v in (street, city, state, zip_code, country))
    if not (city or zip_code or (street and state)):
        return None
    region = " ".join(part for part in (state, zip_code) if part)
    parts = [street, city, region, country]
    return ", ".join(part for part in parts if part)


def round_distance(miles: float) -> float:
    """Round a distance for display (one decimal). 0 stays 0."""
    return round(miles, DISTANCE_DECIMALS)


def _first(record: dict, keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        if key in record:
            value = clean_value(record.get(key))
            if value:
                return value
    return None


def _fetch_one_dict(conn: Any, sql: str, params: tuple) -> Optional[dict]:
    """Run a query and return the first row as a dict (rolls back on failure)."""
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [col[0] for col in cursor.description]
        return dict(zip(columns, row))
    except Exception:
        _rollback(conn)
        raise
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass


def _fetch_all(conn: Any, sql: str, params: tuple) -> list:
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return list(cursor.fetchall())
    except Exception:
        _rollback(conn)
        raise
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass


def _rollback(conn: Any) -> None:
    """Keep a shared connection usable after a failed query."""
    try:
        conn.rollback()
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- #
# Lookup tables (cities / states / countries)
# --------------------------------------------------------------------------- #
_LOOKUP_MEMO: dict = {}
_LOOKUP_MEMO_LIMIT = 5000


class LocationLookups:
    """Resolves internal city/state/country IDs to real names.

    Results are memoized per process (lookup tables rarely change). Failed
    lookups are not memoized and return None.
    """

    def __init__(self, conn: Any, tables: SaayamTables):
        self._conn = conn
        self._tables = tables

    def _memo(self, key: tuple, loader: Callable[[], Any]) -> Any:
        full_key = (self._tables, *key)
        if full_key in _LOOKUP_MEMO:
            return _LOOKUP_MEMO[full_key]
        try:
            value = loader()
        except Exception:  # noqa: BLE001
            logger.warning("Location lookup failed for %s", key[0], exc_info=True)
            return None
        if len(_LOOKUP_MEMO) >= _LOOKUP_MEMO_LIMIT:
            _LOOKUP_MEMO.clear()
        _LOOKUP_MEMO[full_key] = value
        return value

    def city_name(self, city_id: Any) -> Optional[str]:
        """Name of a city from ``cities.city_id``."""
        ref = clean_value(city_id)
        if not ref:
            return None

        def load() -> Optional[str]:
            row = _fetch_one_dict(
                self._conn,
                f"SELECT city_name FROM {self._tables.q('cities')} WHERE CAST(city_id AS TEXT) = %s LIMIT 1",
                (ref,),
            )
            return humanize_name(clean_value(row.get("city_name"))) if row else None

        return self._memo(("city", ref), load)

    def country_name(self, country_id: Any) -> Optional[str]:
        """Name of a country from ``countries.country_id``."""
        ref = clean_value(country_id)
        if not ref:
            return None

        def load() -> Optional[str]:
            row = _fetch_one_dict(
                self._conn,
                f"SELECT country_name FROM {self._tables.q('countries')} WHERE CAST(country_id AS TEXT) = %s LIMIT 1",
                (ref,),
            )
            return humanize_name(clean_value(row.get("country_name"))) if row else None

        return self._memo(("country", ref), load)

    def state(self, state_ref: Any) -> tuple[Optional[str], Optional[str]]:
        """(state_name, country_name) for a ``state_id`` or ``state_code``.

        If the reference matches no row, or more than one, the raw value is
        used only when it reads like a name or code (e.g. "VA"). Internal IDs
        such as "100.1" are dropped.
        """
        ref = clean_value(state_ref)
        if not ref:
            return None, None

        def load() -> tuple[Optional[str], Optional[str]]:
            rows = _fetch_all(
                self._conn,
                f"""
                SELECT s.state_name, c.country_name
                FROM {self._tables.q('states')} s
                LEFT JOIN {self._tables.q('countries')} c ON c.country_id = s.country_id
                WHERE CAST(s.state_id AS TEXT) = %s OR s.state_code = %s
                LIMIT 2
                """,
                (ref, ref),
            )
            if len(rows) == 1:
                state_name, country_name = rows[0]
                return humanize_name(clean_value(state_name)), humanize_name(clean_value(country_name))
            return _raw_name(ref), None

        result = self._memo(("state", ref), load)
        return result if result is not None else (_raw_name(ref), None)


def _raw_name(value: Optional[str]) -> Optional[str]:
    if not value or _INTERNAL_ID.match(value):
        return None
    return humanize_name(value)


# --------------------------------------------------------------------------- #
# Beneficiary (origin) location
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BeneficiaryLocation:
    """Where distances are measured from. Kept server-side and never returned."""

    status: str
    coordinates: Optional[Coordinates] = None
    source: Optional[str] = None  # request | user_locations | profile_address
    beneficiary_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when the origin has coordinates."""
        return self.status == STATUS_OK and self.coordinates is not None


def build_profile_address(user: dict, lookups: Optional[LocationLookups]) -> Optional[str]:
    """Compose a geocodable address from a ``users`` row, using real names (not IDs)."""
    street = _first(user, ("addr_ln1", "street", "address"))
    city = _first(user, ("city_name", "city"))
    if not city and lookups is not None:
        city = lookups.city_name(user.get("city_id"))
    state_name, state_country = (None, None)
    state_ref = user.get("state_id") if "state_id" in user else user.get("state_code")
    if lookups is not None:
        state_name, state_country = lookups.state(state_ref)
    else:
        state_name = _raw_name(clean_value(state_ref))
    country = lookups.country_name(user.get("country_id")) if lookups is not None else None
    zip_code = _first(user, ("zip_code", "zip", "postal_code"))
    return compose_address(street, city, state_name, zip_code, country or state_country)


def resolve_beneficiary_location(
    conn: Any,
    tables: SaayamTables,
    *,
    request_id: Any = None,
    beneficiary_id: Any = None,
    request_location: Any = _UNSET,
    provider: Optional[GeocodingProvider] = None,
    cache: Optional[CoordinateCache] = None,
    budget: Optional[LookupBudget] = None,
) -> BeneficiaryLocation:
    """Resolve the beneficiary/request location (see module docstring for order).

    Args:
        request_location: the request's ``req_loc`` if the caller already
            loaded the request row (the aggregator does, in get_req_info).
            When given, even as None, the requests table is not queried again.
        request_id: used to load ``req_loc`` (and the beneficiary) when
            ``request_location`` is not supplied.
        beneficiary_id: the request's beneficiary. It is used for the
            user_locations and profile-address fallbacks. It is never the
            person viewing the request.
    """
    had_error = False
    request_id = clean_value(request_id)
    beneficiary_id = clean_value(beneficiary_id)

    # 1. Request location
    if request_location is not _UNSET:
        coords = parse_coordinates(request_location)
        if coords is not None:
            return BeneficiaryLocation(STATUS_OK, coords, "request", beneficiary_id)
    elif request_id:
        try:
            request_row = _fetch_one_dict(
                conn,
                f"SELECT * FROM {tables.q('requests')} WHERE req_id = %s LIMIT 1",
                (request_id,),
            )
        except Exception:  # noqa: BLE001
            logger.warning("Request lookup failed for distance calculation", exc_info=True)
            had_error, request_row = True, None
        if request_row:
            # Older schemas have no beneficiary_id; there the requester is the beneficiary.
            if "beneficiary_id" in request_row:
                request_beneficiary = clean_value(request_row.get("beneficiary_id"))
            else:
                request_beneficiary = clean_value(request_row.get("req_user_id"))
            beneficiary_id = request_beneficiary or beneficiary_id
            coords = parse_coordinates(request_row.get("req_loc"))
            if coords is not None:
                return BeneficiaryLocation(STATUS_OK, coords, "request", beneficiary_id)

    if not beneficiary_id:
        return BeneficiaryLocation(STATUS_ERROR if had_error else STATUS_UNKNOWN_LOCATION)

    # 2. user_locations.curr_loc
    try:
        location_row = _fetch_one_dict(
            conn,
            f"SELECT curr_loc FROM {tables.q('user_locations')} WHERE user_id = %s LIMIT 1",
            (beneficiary_id,),
        )
        coords = parse_coordinates(location_row.get("curr_loc")) if location_row else None
        if coords is not None:
            return BeneficiaryLocation(STATUS_OK, coords, "user_locations", beneficiary_id)
    except Exception:  # noqa: BLE001
        logger.warning("user_locations lookup failed for distance calculation", exc_info=True)
        had_error = True

    # 3. Beneficiary profile address
    geocode_status = None
    try:
        user_row = _fetch_one_dict(
            conn,
            f"SELECT * FROM {tables.q('users')} WHERE user_id = %s LIMIT 1",
            (beneficiary_id,),
        )
        address = build_profile_address(user_row, LocationLookups(conn, tables)) if user_row else None
        if address:
            result = geocode_address(address, provider=provider, cache=cache, budget=budget)
            if result.ok:
                return BeneficiaryLocation(STATUS_OK, result.coordinates, "profile_address", beneficiary_id)
            geocode_status = result.status
    except Exception:  # noqa: BLE001
        logger.warning("Profile address lookup failed for distance calculation", exc_info=True)
        had_error = True

    # 4. Nothing usable: no default location is substituted.
    if geocode_status and geocode_status != GEOCODE_NO_ADDRESS:
        status = geocode_status
    else:
        status = STATUS_ERROR if had_error else STATUS_UNKNOWN_LOCATION
    return BeneficiaryLocation(status, beneficiary_id=beneficiary_id)


# --------------------------------------------------------------------------- #
# Organization location
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OrganizationLocation:
    """What we know about where an organization is."""

    status: Optional[str] = None  # online / unknown_location when final, else None
    address: Optional[str] = None
    coordinates: Optional[Coordinates] = None


def is_online_only(text: Optional[str]) -> bool:
    """True for values like "Online", "Virtual", "Remote / Online only"."""
    if not text or not _ONLINE_HINT.search(text):
        return False
    return not _ONLINE_WORDS.sub(" ", text).strip()


def _is_coarse(text: str) -> bool:
    normalized = re.sub(r"[^a-z ]", " ", text.lower())
    return " ".join(normalized.split()) in _COARSE_LOCATIONS


def _record_coordinates(record: dict) -> Optional[Coordinates]:
    subset = {
        key: record[key]
        for key in ("latitude", "longitude", "lat", "lng", "lon")
        if key in record and clean_value(record[key]) is not None
    }
    return parse_coordinates(subset) if subset else None


def database_organization_address(record: dict, lookups: Optional[LocationLookups]) -> Optional[str]:
    """Full address for a row from ``organizations`` (street, city, state, zip, country).

    State and country IDs are swapped for real names using the lookup tables.
    """
    street = _first(record, ("street", "addr_ln1", "address"))
    city = _first(record, ("city_name", "city"))
    if not city and lookups is not None and "city_id" in record:
        city = lookups.city_name(record.get("city_id"))
    state_ref = next(
        (record.get(key) for key in ("state_id", "state_code", "state") if clean_value(record.get(key))),
        None,
    )
    if lookups is not None:
        state_name, state_country = lookups.state(state_ref)
    else:
        state_name, state_country = _raw_name(clean_value(state_ref)), None
    zip_code = _first(record, ("zip_code", "zip", "postal_code"))
    country = _first(record, ("country_name", "country"))
    if not country and lookups is not None and "country_id" in record:
        country = lookups.country_name(record.get("country_id"))
    return compose_address(street, city, state_name, zip_code, humanize_name(country) or state_country)


def organization_location(record: dict) -> OrganizationLocation:
    """Work out an organization's location from whatever the record carries.

    Order: precomputed hints (``_distance_location_status`` /
    ``_distance_address``, set before the merge) → explicit coordinates →
    online flag/text → structured address parts → free-text address/location
    (GenAI orgs).
    """
    hinted_status = clean_value(record.get(LOCATION_STATUS_KEY))
    if hinted_status in (STATUS_ONLINE, STATUS_UNKNOWN_LOCATION):
        return OrganizationLocation(status=hinted_status)

    precomputed = clean_value(record.get(ADDRESS_KEY))
    if precomputed:
        embedded = parse_coordinates(precomputed)
        if embedded is not None:
            return OrganizationLocation(coordinates=embedded)
        return OrganizationLocation(address=precomputed)

    coords = _record_coordinates(record)
    if coords is not None:
        return OrganizationLocation(coordinates=coords)

    for flag in ("is_online", "online_only"):
        if record.get(flag) is True or str(record.get(flag)).strip().lower() == "true":
            return OrganizationLocation(status=STATUS_ONLINE)

    structured = compose_address(
        _first(record, ("street", "street_address")),
        _first(record, ("city", "city_name")),
        _first(record, ("state", "state_code", "state_name")),
        _first(record, ("zip_code", "zip", "postal_code")),
        _first(record, ("country", "country_name")),
    )
    if structured:
        return OrganizationLocation(address=structured)

    for key in ("address", "full_address", "location", "headquarters"):
        text = clean_value(record.get(key))
        if not text:
            continue
        if is_online_only(text):
            return OrganizationLocation(status=STATUS_ONLINE)
        embedded = parse_coordinates(text)
        if embedded is not None:
            return OrganizationLocation(coordinates=embedded)
        if _is_coarse(text):
            continue
        return OrganizationLocation(address=text)

    return OrganizationLocation(status=STATUS_UNKNOWN_LOCATION)


def _hints(location: OrganizationLocation) -> tuple[Optional[str], Optional[str]]:
    """Encode a location as (address, status) strings that survive a DataFrame merge."""
    if location.coordinates is not None:
        coords = location.coordinates
        return f"latitude:{coords.latitude},longitude:{coords.longitude}", None
    if location.address:
        return location.address, None
    return None, location.status or STATUS_UNKNOWN_LOCATION


def database_organization_hints(record: dict, lookups: Optional[LocationLookups]) -> tuple[Optional[str], Optional[str]]:
    """(address, status) for a raw ``organizations`` row."""
    coords = _record_coordinates(record)
    if coords is not None:
        return _hints(OrganizationLocation(coordinates=coords))
    address = database_organization_address(record, lookups)
    return _hints(OrganizationLocation(address=address, status=None if address else STATUS_UNKNOWN_LOCATION))


def genai_organization_hints(record: dict) -> tuple[Optional[str], Optional[str]]:
    """(address, status) for a raw GenAI organization record."""
    return _hints(organization_location(record))


def attach_location_hints(frame: Any, lookups: Optional[LocationLookups] = None, *, source: str = "db") -> Any:
    """Add the private location-hint columns to a DB or GenAI orgs DataFrame.

    Call this before ``merge_organizations`` while street/zip/state are still
    present. It never raises. If a row fails, it gets no hints and falls back
    to its merged ``location`` field later.
    """
    try:
        if frame is None or getattr(frame, "empty", True):
            return frame
        addresses, statuses = [], []
        for record in frame.to_dict(orient="records"):
            try:
                if source == "db":
                    address, status = database_organization_hints(record, lookups)
                else:
                    address, status = genai_organization_hints(record)
            except Exception:  # noqa: BLE001
                logger.warning("Could not build location hints for one organization", exc_info=True)
                address, status = None, None
            addresses.append(address)
            statuses.append(status)
        frame[ADDRESS_KEY] = addresses
        frame[LOCATION_STATUS_KEY] = statuses
    except Exception:  # noqa: BLE001
        logger.warning("Could not attach location hints", exc_info=True)
    return frame


def strip_private_keys(organizations: list) -> list:
    """Remove the internal hint keys so they never reach the API response."""
    for org in organizations:
        if isinstance(org, dict):
            for key in PRIVATE_KEYS:
                org.pop(key, None)
    return organizations


# --------------------------------------------------------------------------- #
# Distance enrichment
# --------------------------------------------------------------------------- #
def distance_fields(distance: Optional[float], status: str) -> dict:
    """The four response fields. ``distance`` is None unless status is ok."""
    return {
        "distance": distance if status == STATUS_OK else None,
        "distance_unit": DISTANCE_UNIT,
        "distance_method": DISTANCE_METHOD,
        "distance_status": status,
    }


def add_distance_fields(
    organizations: list,
    origin: BeneficiaryLocation,
    *,
    locate: Callable[[dict], OrganizationLocation] = organization_location,
    provider: Optional[GeocodingProvider] = None,
    cache: Optional[CoordinateCache] = None,
    budget: Optional[LookupBudget] = None,
) -> list:
    """Add distance fields to every organization dict (in place) and return the list.

    Each organization is handled on its own, so a failure on one never
    removes or breaks the others.
    """
    seen: dict[str, GeocodeResult] = {}
    for org in organizations:
        if not isinstance(org, dict):
            continue
        try:
            location = locate(org)
            distance, status = _distance_for(location, origin, seen, provider, cache, budget)
        except Exception:  # noqa: BLE001
            logger.warning("Distance calculation failed for one organization", exc_info=True)
            distance, status = None, STATUS_ERROR
        for key in PRIVATE_KEYS:
            org.pop(key, None)
        org.update(distance_fields(distance, status))
    return organizations


def _distance_for(
    location: OrganizationLocation,
    origin: BeneficiaryLocation,
    seen: dict,
    provider: Optional[GeocodingProvider],
    cache: Optional[CoordinateCache],
    budget: Optional[LookupBudget],
) -> tuple[Optional[float], str]:
    if location.status == STATUS_ONLINE:
        return None, STATUS_ONLINE
    if location.coordinates is None and not location.address:
        return None, location.status or STATUS_UNKNOWN_LOCATION
    if not origin.ok:
        # No point geocoding the org when there is nothing to measure from.
        return None, origin.status or STATUS_UNKNOWN_LOCATION

    coords = location.coordinates
    if coords is None:
        result = seen.get(location.address)
        if result is None:
            result = geocode_address(location.address, provider=provider, cache=cache, budget=budget)
            seen[location.address] = result
        if not result.ok:
            return None, result.status if result.status != GEOCODE_OK else STATUS_ERROR
        coords = result.coordinates

    miles = haversine_distance(origin.coordinates, coords, DISTANCE_UNIT)
    return round_distance(miles), STATUS_OK


def apply_distances(
    organizations: list,
    conn: Any,
    *,
    request_id: Any = None,
    beneficiary_id: Any = None,
    request_location: Any = _UNSET,
    tables: Optional[SaayamTables] = None,
    locate: Optional[Callable[[dict], OrganizationLocation]] = None,
    provider: Optional[GeocodingProvider] = None,
    cache: Optional[CoordinateCache] = None,
    budget: Optional[LookupBudget] = None,
) -> list:
    """Resolve the origin, then add distance fields to every organization.

    This is the single entry point for the Lambda. It never raises: if
    anything unexpected happens, every org is still returned with
    ``distance = None`` and ``distance_status = "error"``.
    """
    try:
        tables = tables or SaayamTables.from_env()
        budget = budget if budget is not None else LookupBudget.from_env()
        if request_id is None and beneficiary_id is None and request_location is _UNSET:
            origin = BeneficiaryLocation(STATUS_UNKNOWN_LOCATION)
        else:
            origin = resolve_beneficiary_location(
                conn,
                tables,
                request_id=request_id,
                beneficiary_id=beneficiary_id,
                request_location=request_location,
                provider=provider,
                cache=cache,
                budget=budget,
            )
        return add_distance_fields(
            organizations,
            origin,
            locate=locate or organization_location,
            provider=provider,
            cache=cache,
            budget=budget,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Distance enrichment failed; returning organizations without distance")
        strip_private_keys(organizations)
        for org in organizations:
            if isinstance(org, dict):
                org.update(distance_fields(None, STATUS_ERROR))
        return organizations


def sort_by_distance(organizations: list) -> list:
    """Nearest first, then farther, then unknown distance (N/A) last.

    The sort is stable, so ties keep their original order.
    """

    def key(org: Any) -> tuple:
        distance = org.get("distance") if isinstance(org, dict) else None
        if isinstance(distance, (int, float)) and not isinstance(distance, bool) and math.isfinite(distance):
            return (0, float(distance))
        return (1, 0.0)

    return sorted(organizations, key=key)
