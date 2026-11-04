"""Distance calculation for recommended organizations (issue #433).

Everything distance-related lives here so the aggregator only needs two calls:

    beneficiary = resolve_beneficiary_point(candidates)
    records = add_distances(records, beneficiary)

Distance is the straight-line (great-circle / haversine) distance in miles from
the BENEFICIARY / REQUEST location to each organization. It is never driving
distance and never measured from the person viewing the request.

Nothing in this module raises into the API: every failure is turned into a
`distance: null` plus a `distance_status`, so organizations are always returned.

Geocoding is provider-agnostic. The provider is chosen by the GEOCODER_PROVIDER
environment variable from a registry (see `register_geocoder`), so an approved
external provider can be plugged in later without touching the Lambda:

    none        - no geocoding; anything without coordinates is "deferred".
    city_table  - (default) resolves "city, state" against the internal
                  cities table (lattitude/longitude). No external API calls.
                  City-level precision only.
    <custom>    - any provider registered with register_geocoder().

Geocoding results are cached by normalized address in a module-level cache that
survives warm Lambda invocations, and a per-invocation call budget turns
anything beyond the budget into "deferred" instead of slowing the response.

Response fields added to every organization
-------------------------------------------
distance         number (miles, 1 decimal) or null. Unknown is ALWAYS null, never 0.
distance_unit    "miles"
distance_method  "straight_line"  both ends are exact points (request coordinates,
                                  saved location, or a street-level geocoder)
                 "city_centroid"  at least one end is the centre of its city from the
                                  cities table, so the distance is approximate
distance_status  decided in this order; the first that applies wins:
  online            the organization is online-only (no physical location)
  unknown_location  the organization has no address, OR the beneficiary has no
                    location anywhere (no req_loc, no saved location, no address)
  error             a lookup failed (DB error, geocoding provider error/exception)
  deferred          not attempted: geocoding time or call budget used up
  not_found         an address exists but could not be matched to coordinates
                    (the beneficiary's address, or the organization's)
  ok                distance calculated
"""
import json
import logging
import math
import os
import re
import struct
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

EARTH_RADIUS_MILES = 3958.7613
DISTANCE_UNIT = "miles"
DISTANCE_METHOD = "straight_line"            # both points exact
DISTANCE_METHOD_APPROX = "city_centroid"     # at least one point is a city centre
DISTANCE_DECIMALS = 1

STATUS_OK = "ok"
STATUS_ONLINE = "online"
STATUS_UNKNOWN_LOCATION = "unknown_location"
STATUS_NOT_FOUND = "not_found"
STATUS_DEFERRED = "deferred"
STATUS_ERROR = "error"
DISTANCE_STATUSES = (STATUS_OK, STATUS_ONLINE, STATUS_UNKNOWN_LOCATION,
                     STATUS_NOT_FOUND, STATUS_DEFERRED, STATUS_ERROR)

# Internal columns carried through the merge so organizations can be geocoded.
# They are stripped from every record before the response is returned.
GEO_ADDRESS = "_geo_address"     # full address string, names not IDs
GEO_CITY = "_geo_city"           # structured city, for the city_table provider
GEO_STATE = "_geo_state"         # structured state id / code / name
GEO_PREFIX = "_geo_"

ONLINE_PATTERN = re.compile(
    r"^\s*(online|virtual|remote|online[\s-]only|web[\s-]?based|internet|"
    r"nationwide|worldwide|global|international)\s*$", re.IGNORECASE)
MISSING_LOCATION_TOKENS = {"", "n/a", "na", "none", "null", "unknown", "nan", "-"}

DEFAULT_GEOCODE_BUDGET = 25          # external geocode calls per invocation
DEFAULT_GEOCODE_TIME_BUDGET_S = 5.0  # wall-clock seconds spent geocoding
DEFAULT_CITY_TABLE_RETRY_MAX_S = 60.0  # longest wait between retries of a failing cities load
DEFAULT_CITY_TABLE_REFRESH_S = 6 * 3600.0  # reload a good cities table this often
DEFAULT_CITY_TABLE_EMPTY_RECHECK_S = 60.0  # re-check an EMPTY cities table this often


class LookupUnavailable(Exception):
    """The data a geocoder needs could not be read right now (e.g. a DB error).

    This is a temporary failure, not an answer: callers report it as "error",
    and it is never cached, so the next request tries again.
    """


# --------------------------------------------------------------------------- #
# Basic types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GeoPoint:
    lat: float
    lon: float
    source: str = ""            # where the point came from, for logging only
    approximate: bool = False   # True for a city centre rather than an exact spot


@dataclass(frozen=True)
class GeocodeResult:
    status: str                      # ok | not_found | deferred | error
    point: Optional[GeoPoint] = None
    cacheable: bool = True           # False: don't remember this answer (see CityTableGeocoder)


def _is_valid(lat: Any, lon: Any) -> bool:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return (math.isfinite(lat) and math.isfinite(lon)
            and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0)


def _make_point(lat: Any, lon: Any, source: str,
                approximate: bool = False) -> Optional[GeoPoint]:
    if not _is_valid(lat, lon):
        return None
    return GeoPoint(float(lat), float(lon), source, approximate)


def is_blank(value: Any) -> bool:
    """None, NaN, empty, or a placeholder such as 'N/A'."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip().lower() in MISSING_LOCATION_TOKENS


def join_parts(parts: Iterable[Any], sep: str = ", ") -> Optional[str]:
    cleaned = [str(p).strip() for p in parts if not is_blank(p)]
    return sep.join(cleaned) if cleaned else None


# --------------------------------------------------------------------------- #
# Coordinate parsing (requests.req_loc, user_locations.curr_loc)
# --------------------------------------------------------------------------- #
_NUM = r"[-+]?\d+(?:\.\d+)?"
_POINT_RE = re.compile(rf"POINT\s*\(\s*({_NUM})\s+({_NUM})\s*\)", re.IGNORECASE)
_LABELLED_RE = {
    "lat": re.compile(rf"\b(?:lat|latitude)\b\s*[:=]\s*({_NUM})", re.IGNORECASE),
    "lon": re.compile(rf"\b(?:lon|lng|long|longitude)\b\s*[:=]\s*({_NUM})", re.IGNORECASE),
}
_PAIR_RE = re.compile(rf"^\s*\(?\s*({_NUM})\s*,\s*({_NUM})\s*\)?\s*$")
_HEX_RE = re.compile(r"^(?:\\x)?[0-9a-fA-F]+$")


def _parse_ewkb_hex(text: str) -> Optional[Tuple[float, float]]:
    """(lon, lat) from a PostGIS (E)WKB hex POINT, as returned for geography columns."""
    raw = text[2:] if text.startswith("\\x") else text
    if len(raw) < 42 or len(raw) % 2:
        return None
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return None
    order = "<" if data[0] == 1 else ">"
    geom_type = struct.unpack(order + "I", data[1:5])[0]
    offset = 5
    if geom_type & 0x20000000:          # EWKB: SRID present
        offset += 4
    if geom_type & 0x0FFFFFFF != 1:     # only POINT is supported
        return None
    if len(data) < offset + 16:
        return None
    return struct.unpack(order + "dd", data[offset:offset + 16])


def parse_coordinates(value: Any, source: str = "") -> Optional[GeoPoint]:
    """Parse a stored location into a GeoPoint, or None if it holds no coordinates.

    Accepts every format seen for req_loc / curr_loc:
      * PostGIS EWKT      'SRID=4326;POINT(-121.978 37.7799)'   (lon lat order)
      * PostGIS EWKB hex  '0101000020E6100000...'               (geography columns)
      * labelled text     'longitude:-121.9780,latitude:37.7799' (any order)
      * JSON / dict       {"latitude": 37.77, "longitude": -121.97}
      * plain pair        '37.7799, -121.9780'                   (lat, lon)
    Free text such as 'Suffolk, VA' returns None - it is an address, not coordinates.
    """
    if is_blank(value):
        return None

    if isinstance(value, dict):
        lat = next((value[k] for k in ("lat", "latitude") if k in value), None)
        lon = next((value[k] for k in ("lon", "lng", "long", "longitude") if k in value), None)
        return _make_point(lat, lon, source)

    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).hex()

    text = str(value).strip()

    if text.startswith("{"):
        try:
            return parse_coordinates(json.loads(text), source)
        except json.JSONDecodeError:
            pass

    match = _POINT_RE.search(text)
    if match:
        lon, lat = match.groups()
        return _make_point(lat, lon, source)

    lat_m, lon_m = _LABELLED_RE["lat"].search(text), _LABELLED_RE["lon"].search(text)
    if lat_m and lon_m:
        return _make_point(lat_m.group(1), lon_m.group(1), source)

    if _HEX_RE.match(text):
        lon_lat = _parse_ewkb_hex(text)
        if lon_lat:
            return _make_point(lon_lat[1], lon_lat[0], source)
        return None

    match = _PAIR_RE.match(text)
    if match:
        return _make_point(match.group(1), match.group(2), source)

    return None


# --------------------------------------------------------------------------- #
# Distance
# --------------------------------------------------------------------------- #
def haversine_miles(a: GeoPoint, b: GeoPoint) -> float:
    """Great-circle (straight-line) distance between two points, in miles."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(h)))


# --------------------------------------------------------------------------- #
# Geocoding providers (pluggable)
# --------------------------------------------------------------------------- #
class Geocoder:
    """Provider interface. Implementations must never raise for 'not found'."""

    name = "base"
    external = False   # True if each call costs an external API request

    def begin_request(self) -> None:
        """Hook called once at the start of each Lambda invocation."""

    def geocode(self, address: Optional[str], city: Optional[str] = None,
                state: Optional[str] = None) -> GeocodeResult:
        raise NotImplementedError


class NoGeocoder(Geocoder):
    """No provider configured: anything that needs geocoding is deferred."""

    name = "none"

    def geocode(self, address, city=None, state=None):
        return GeocodeResult(STATUS_DEFERRED)


class CityTableGeocoder(Geocoder):
    """Resolve 'city, state' against the internal cities table (no external calls).

    `rows_loader` returns dicts with city_name, lattitude/latitude, longitude and
    any of state_id / state_code / state_name. It must RAISE if the table cannot
    be read; returning [] means "the table is genuinely empty".
    Precision is the city centre, which is adequate for a straight-line estimate.

    Caching rules (issue #433 review, step 2):
      * A successful load is kept and refreshed every `refresh_s`.
      * A failed load is NOT kept. geocode() returns "error" (never cached by
        CoordinateCache) and the load is retried later:
          - at most once per request (begin_request), never once per organization;
          - the request after a first failure retries straight away, so one
            brief DB hiccup is fixed by the next call;
          - if it keeps failing, the wait grows 5 s, 10 s, 20 s ... up to
            `retry_max_s`, so a real outage costs at most one query per minute.
      * If a refresh fails, the previous good data keeps being used.
      * A refresh that returns 0 rows when we already had good data is treated
        as a failure too (e.g. the table is mid-reload: rows deleted, not yet
        re-inserted). We keep the old data, log a warning and retry later.
      * The refresh and retry timers use wall-clock time.time(): Lambda freezes
        the container between requests and time.monotonic() isn't guaranteed to
        keep counting while frozen, so "6 hours" could silently become longer.
    """

    name = "city_table"

    def __init__(self, rows_loader: Callable[[], Iterable[Dict[str, Any]]],
                 retry_max_s: Optional[float] = None, refresh_s: Optional[float] = None):
        self._rows_loader = rows_loader
        self._by_city_state: Optional[Dict[Tuple[str, str], GeoPoint]] = None
        self._by_city: Dict[str, Optional[GeoPoint]] = {}
        self.retry_max_s = float(os.environ.get("CITY_TABLE_RETRY_MAX_S",
                                                DEFAULT_CITY_TABLE_RETRY_MAX_S)
                                 if retry_max_s is None else retry_max_s)
        self.empty_recheck_s = float(os.environ.get("CITY_TABLE_EMPTY_RECHECK_S",
                                                    DEFAULT_CITY_TABLE_EMPTY_RECHECK_S))
        self.refresh_s = float(os.environ.get("CITY_TABLE_REFRESH_S",
                                              DEFAULT_CITY_TABLE_REFRESH_S)
                               if refresh_s is None else refresh_s)
        self._loaded_at = 0.0
        self._failures = 0              # consecutive failed loads
        self._next_attempt = 0.0        # time.time() before which we don't retry
        self._attempted_this_request = False

    def begin_request(self) -> None:
        """Called once per Lambda invocation: allow one load attempt in it."""
        self._attempted_this_request = False

    def _retry_delay(self) -> float:
        if self._failures <= 1:
            return 0.0                  # first failure: the next request may retry
        # Cap the exponent: 5 * 2**6 = 320 s is already above retry_max_s, and an
        # uncapped 2**n overflows float after ~1,025 failures in a row.
        return min(self.retry_max_s, 5.0 * 2 ** min(self._failures - 2, 6))

    @staticmethod
    def _key(value: Any) -> str:
        return re.sub(r"[\s_]+", " ", str(value)).strip().lower()

    def _load(self) -> None:
        """Make sure lookup data is available, or raise LookupUnavailable."""
        now = time.time()   # wall clock: these timers span Lambda freezes (see class doc)
        # A loaded-but-EMPTY table (e.g. dev before cities is populated) is
        # re-checked every minute, so distances appear soon after it's filled.
        max_age = (self.refresh_s if self._by_city_state
                   else min(self.refresh_s, self.empty_recheck_s))
        fresh = (self._by_city_state is not None
                 and now - self._loaded_at < max_age)
        if fresh:
            return
        if self._attempted_this_request or now < self._next_attempt:
            if self._by_city_state is not None:
                return                       # refresh failed recently: keep old data
            raise LookupUnavailable("cities table unavailable (waiting to retry)")
        self._attempted_this_request = True
        try:
            rows = list(self._rows_loader())
        except Exception as exc:  # noqa: BLE001
            self._failures += 1
            self._next_attempt = now + self._retry_delay()
            logger.warning("cities load failed (%d in a row, next retry in %.0f s): %s",
                           self._failures, self._retry_delay(), exc)
            if self._by_city_state is not None:
                logger.warning("cities refresh failed, keeping previous data: %s", exc)
                return
            raise LookupUnavailable(f"cities table unavailable: {exc}") from exc
        if not rows and self._by_city_state:
            # An empty refresh after a good, NON-empty load isn't a real answer (the
            # table is probably being reloaded). Treat it like a failure: keep the old
            # data. If the table was already empty on the first load there's nothing
            # to keep, so 0 rows is simply the current answer (no warning, no retries).
            self._failures += 1
            self._next_attempt = now + self._retry_delay()
            logger.warning("cities refresh returned 0 rows (%d in a row); keeping previous "
                           "data, next retry in %.0f s", self._failures, self._retry_delay())
            return
        self._index(rows)
        self._loaded_at = now
        self._failures = 0
        self._next_attempt = 0.0

    def _index(self, rows: Iterable[Dict[str, Any]]) -> None:
        by_city_state: Dict[Tuple[str, str], GeoPoint] = {}
        by_city: Dict[str, Optional[GeoPoint]] = {}
        for row in rows:
            lat = row.get("lattitude", row.get("latitude"))
            point = _make_point(lat, row.get("longitude"), "cities", approximate=True)
            city = row.get("city_name")
            if point is None or is_blank(city):
                continue
            city_key = self._key(city)
            for state_field in ("state_id", "state_code", "state_name"):
                state_val = row.get(state_field)
                if not is_blank(state_val):
                    by_city_state[(city_key, self._key(state_val))] = point
                    # 'US-CA' -> also index 'CA'
                    if state_field == "state_code" and "-" in str(state_val):
                        short = str(state_val).split("-", 1)[1]
                        by_city_state[(city_key, self._key(short))] = point
            # City alone is only trusted when the name is unambiguous.
            by_city[city_key] = point if city_key not in by_city else None
        self._by_city_state, self._by_city = by_city_state, by_city

    def _lookup(self, city: Any, state: Any) -> Optional[GeoPoint]:
        if is_blank(city):
            return None
        city_key = self._key(city)
        if not is_blank(state):
            state_key = self._key(state)
            hit = self._by_city_state.get((city_key, state_key))
            if hit:
                return hit
            # 'CA 94043' -> 'ca'
            first = state_key.split(" ")[0]
            hit = self._by_city_state.get((city_key, first))
            if hit:
                return hit
            return None   # a state was given and did not match - don't guess
        return self._by_city.get(city_key)

    def geocode(self, address, city=None, state=None):
        try:
            self._load()
        except LookupUnavailable:
            # Already logged once in _load; don't repeat it for every organization.
            return GeocodeResult(STATUS_ERROR)
        if not is_blank(city):
            point = self._lookup(city, state)
            if point:
                return GeocodeResult(STATUS_OK, point)
        if not is_blank(address):
            parts = [p.strip() for p in str(address).split(",") if p.strip()]
            # Try every adjacent (city, state) pair: '12 Main St, Fremont, CA 94536, USA'
            for i in range(len(parts)):
                state_part = parts[i + 1] if i + 1 < len(parts) else None
                point = self._lookup(parts[i], state_part)
                if point:
                    return GeocodeResult(STATUS_OK, point)
        # With an empty cities table every address is "not found", but that answer
        # will change as soon as the table is filled, so don't let it be cached.
        return GeocodeResult(STATUS_NOT_FOUND, cacheable=bool(self._by_city_state))


class ChainGeocoder(Geocoder):
    """Try providers in order; first 'ok' wins."""

    def begin_request(self) -> None:
        for provider in self.providers:
            provider.begin_request()

    def __init__(self, providers: Sequence[Geocoder]):
        self.providers = list(providers)
        self.name = "+".join(p.name for p in self.providers)
        self.external = any(p.external for p in self.providers)

    def geocode(self, address, city=None, state=None):
        statuses = []
        cacheable = True
        for provider in self.providers:
            result = provider.geocode(address, city, state)
            if result.status == STATUS_OK:
                return result
            statuses.append(result.status)
            cacheable = cacheable and result.cacheable
        for status in (STATUS_ERROR, STATUS_DEFERRED):
            if status in statuses:
                return GeocodeResult(status)
        return GeocodeResult(STATUS_NOT_FOUND, cacheable=cacheable)


# name -> factory(context) -> Geocoder. context carries e.g. the cities loader.
_GEOCODER_REGISTRY: Dict[str, Callable[[Dict[str, Any]], Geocoder]] = {
    "none": lambda ctx: NoGeocoder(),
    "city_table": lambda ctx: CityTableGeocoder(ctx["cities_loader"]),
}


def register_geocoder(name: str, factory: Callable[[Dict[str, Any]], Geocoder]) -> None:
    """Plug in a provider, e.g. once the team approves one:

        register_geocoder("aws_location", lambda ctx: AwsLocationGeocoder(...))
    then set GEOCODER_PROVIDER=city_table,aws_location
    """
    _GEOCODER_REGISTRY[name.strip().lower()] = factory


def build_geocoder(context: Dict[str, Any], provider_names: Optional[str] = None) -> Geocoder:
    """Build the geocoder named by GEOCODER_PROVIDER (comma-separated = fallback chain)."""
    names = provider_names or os.environ.get("GEOCODER_PROVIDER", "city_table")
    providers = []
    for name in (n.strip().lower() for n in names.split(",") if n.strip()):
        factory = _GEOCODER_REGISTRY.get(name)
        if factory is None:
            logger.warning("Unknown geocoder provider %r ignored", name)
            continue
        providers.append(factory(context))
    if not providers:
        return NoGeocoder()
    return providers[0] if len(providers) == 1 else ChainGeocoder(providers)


# --------------------------------------------------------------------------- #
# Coordinate cache
# --------------------------------------------------------------------------- #
class CoordinateCache:
    """Address -> GeocodeResult cache. Module-level, so it survives warm starts.

    ok and not_found results are cached; deferred and error are never cached
    so they are retried next time. not_found is kept no longer than the cities
    refresh interval (CITY_TABLE_REFRESH_S, 6 h by default), so a wrong
    "not found" can't outlive the data it came from.
    A persistent backend (DB table, DynamoDB...) can be attached later via
    `backend` with get(key) -> (lat, lon[, approximate]) | None and
    set(key, lat, lon, approximate).
    """

    def __init__(self, ttl_s: float = 7 * 24 * 3600, miss_ttl_s: Optional[float] = None,
                 max_entries: int = 5000, backend: Any = None):
        if miss_ttl_s is None:
            miss_ttl_s = float(os.environ.get("CITY_TABLE_REFRESH_S",
                                              DEFAULT_CITY_TABLE_REFRESH_S))
        self.ttl_s, self.miss_ttl_s, self.max_entries = ttl_s, miss_ttl_s, max_entries
        self.backend = backend
        self._store: Dict[str, Tuple[float, GeocodeResult]] = {}
        self.hits = self.misses = 0

    @staticmethod
    def key(address: Optional[str], city: Optional[str], state: Optional[str]) -> str:
        text = "|".join(str(p) for p in (address, city, state) if not is_blank(p))
        return re.sub(r"[^a-z0-9|]+", " ", text.lower()).strip()

    def get(self, key: str) -> Optional[GeocodeResult]:
        entry = self._store.get(key)
        if entry and entry[0] > time.time():
            self.hits += 1
            return entry[1]
        if entry:
            self._store.pop(key, None)
        if self.backend is not None:
            try:
                stored = self.backend.get(key)
            except Exception as exc:  # noqa: BLE001 - cache must never break the API
                logger.warning("coordinate cache backend get failed: %s", exc)
                stored = None
            if stored:
                approx = bool(stored[2]) if len(stored) > 2 else False
                result = GeocodeResult(STATUS_OK,
                                       GeoPoint(stored[0], stored[1], "cache", approx))
                self._put(key, result, self.ttl_s)
                self.hits += 1
                return result
        self.misses += 1
        return None

    def set(self, key: str, result: GeocodeResult) -> None:
        if not result.cacheable:
            return
        if result.status == STATUS_OK:
            self._put(key, result, self.ttl_s)
            if self.backend is not None:
                try:
                    self.backend.set(key, result.point.lat, result.point.lon,
                                     result.point.approximate)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("coordinate cache backend set failed: %s", exc)
        elif result.status == STATUS_NOT_FOUND:
            self._put(key, result, self.miss_ttl_s)

    def _put(self, key: str, result: GeocodeResult, ttl: float) -> None:
        if len(self._store) >= self.max_entries:
            self._store.pop(next(iter(self._store)))   # drop oldest
        self._store[key] = (time.time() + ttl, result)


_CACHE = CoordinateCache()


def get_cache() -> CoordinateCache:
    return _CACHE


# --------------------------------------------------------------------------- #
# geocode_address: the single entry point the issue asks for
# --------------------------------------------------------------------------- #
class GeocodeSession:
    """One invocation's geocoding: cache first, then provider, within a budget."""

    def __init__(self, geocoder: Geocoder, cache: Optional[CoordinateCache] = None,
                 max_calls: Optional[int] = None, time_budget_s: Optional[float] = None):
        self.geocoder = geocoder
        self.cache = cache or _CACHE
        self.max_calls = int(os.environ.get("GEOCODE_MAX_CALLS", DEFAULT_GEOCODE_BUDGET)
                             if max_calls is None else max_calls)
        budget = (os.environ.get("GEOCODE_TIME_BUDGET_S", DEFAULT_GEOCODE_TIME_BUDGET_S)
                  if time_budget_s is None else time_budget_s)
        self.deadline = time.monotonic() + float(budget)
        self.external_calls = 0
        geocoder.begin_request()

    def geocode_address(self, address: Optional[str], city: Optional[str] = None,
                        state: Optional[str] = None) -> GeocodeResult:
        if is_blank(address) and is_blank(city):
            return GeocodeResult(STATUS_UNKNOWN_LOCATION)

        key = self.cache.key(address, city, state)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        if self.geocoder.external:
            if self.external_calls >= self.max_calls or time.monotonic() > self.deadline:
                return GeocodeResult(STATUS_DEFERRED)
            self.external_calls += 1

        try:
            result = self.geocoder.geocode(address, city, state)
        except Exception as exc:  # noqa: BLE001 - a provider failure is a status, not a crash
            logger.warning("geocoding failed for %r: %s", address, exc)
            return GeocodeResult(STATUS_ERROR)

        if result.status not in DISTANCE_STATUSES:
            result = GeocodeResult(STATUS_ERROR)
        self.cache.set(key, result)
        return result


# --------------------------------------------------------------------------- #
# Beneficiary location
# --------------------------------------------------------------------------- #
@dataclass
class LocationCandidate:
    """One step of the beneficiary fallback chain.

    Either raw stored coordinates (`coordinates`) or an address to geocode.
    """
    source: str
    coordinates: Any = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    lookup_failed: bool = False   # the DB query for this step failed (-> "error")


def resolve_beneficiary_point(candidates: Sequence[LocationCandidate],
                              session: GeocodeSession) -> Tuple[Optional[GeoPoint], str]:
    """First usable point from the ordered candidates.

    Returns (point, status). Never falls back to a default such as 'United States'.
    When no point is found, the status says why, most serious first:
      error            a lookup failed (DB error, geocoder error)
      deferred         geocoding was skipped for lack of time/budget
      not_found        an address existed but could not be matched
      unknown_location there really is no location for this beneficiary
    """
    seen = set()
    for candidate in candidates:
        try:
            if candidate.lookup_failed:
                seen.add(STATUS_ERROR)
                continue
            if candidate.coordinates is not None:
                point = parse_coordinates(candidate.coordinates, candidate.source)
                if point:
                    return point, STATUS_OK
            if not is_blank(candidate.address) or not is_blank(candidate.city):
                result = session.geocode_address(candidate.address, candidate.city,
                                                  candidate.state)
                if result.status == STATUS_OK:
                    return GeoPoint(result.point.lat, result.point.lon, candidate.source,
                                    result.point.approximate), STATUS_OK
                seen.add(result.status)
        except Exception as exc:  # noqa: BLE001
            logger.warning("beneficiary location step %s failed: %s", candidate.source, exc)
            seen.add(STATUS_ERROR)
    for status in (STATUS_ERROR, STATUS_DEFERRED, STATUS_NOT_FOUND):
        if status in seen:
            return None, status
    return None, STATUS_UNKNOWN_LOCATION


# --------------------------------------------------------------------------- #
# Organizations
# --------------------------------------------------------------------------- #
def _distance_fields(distance: Optional[float], status: str,
                     method: str = DISTANCE_METHOD) -> Dict[str, Any]:
    return {
        "distance": distance,
        "distance_unit": DISTANCE_UNIT,
        "distance_method": method,
        "distance_status": status,
    }


def _clean_value(value: Any) -> Any:
    """NaN/NaT -> None so the JSON body contains null, never NaN."""
    if isinstance(value, float) and math.isnan(value):
        return None
    if value.__class__.__name__ in ("NaTType", "NAType"):
        return None
    return value


def organization_distance(record: Dict[str, Any], beneficiary: Optional[GeoPoint],
                          beneficiary_status: str, session: GeocodeSession) -> Dict[str, Any]:
    """Distance fields for one organization record. Never raises."""
    try:
        address = record.get(GEO_ADDRESS)
        if is_blank(address):
            address = record.get("location")
        city, state = record.get(GEO_CITY), record.get(GEO_STATE)

        # Order matters - see "distance_status" in the module docstring.
        if not is_blank(address) and ONLINE_PATTERN.match(str(address)):
            return _distance_fields(None, STATUS_ONLINE)
        # An org without an address has no location, whatever happened elsewhere.
        if is_blank(address) and is_blank(city):
            return _distance_fields(None, STATUS_UNKNOWN_LOCATION)
        if beneficiary is None:
            status = beneficiary_status if beneficiary_status != STATUS_OK else STATUS_UNKNOWN_LOCATION
            return _distance_fields(None, status)

        result = session.geocode_address(address, city, state)
        if result.status != STATUS_OK or result.point is None:
            return _distance_fields(None, result.status if result.status != STATUS_OK
                                    else STATUS_ERROR)

        miles = round(haversine_miles(beneficiary, result.point), DISTANCE_DECIMALS)
        approximate = beneficiary.approximate or result.point.approximate
        return _distance_fields(miles, STATUS_OK,
                                DISTANCE_METHOD_APPROX if approximate else DISTANCE_METHOD)
    except Exception as exc:  # noqa: BLE001
        logger.warning("distance calculation failed for %r: %s", record.get("name"), exc)
        return _distance_fields(None, STATUS_ERROR)


def add_distances(records: List[Dict[str, Any]], beneficiary: Optional[GeoPoint],
                  beneficiary_status: str, session: GeocodeSession) -> List[Dict[str, Any]]:
    """Return new records with the four distance fields; internal _geo_ keys removed."""
    enriched = []
    for record in records:
        fields = organization_distance(record, beneficiary, beneficiary_status, session)
        clean = {k: _clean_value(v) for k, v in record.items() if not k.startswith(GEO_PREFIX)}
        clean.update(fields)
        enriched.append(clean)
    return enriched


def without_distance(records: List[Dict[str, Any]], status: str = STATUS_ERROR) -> List[Dict[str, Any]]:
    """Fallback used if distance enrichment as a whole fails: keep every org."""
    out = []
    for record in records:
        clean = {k: _clean_value(v) for k, v in record.items() if not k.startswith(GEO_PREFIX)}
        clean.update(_distance_fields(None, status))
        out.append(clean)
    return out


def sort_by_distance(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Nearest first, unknown (null) distances last; original order kept for ties."""
    return sorted(records, key=lambda r: (r.get("distance") is None, r.get("distance") or 0.0))
