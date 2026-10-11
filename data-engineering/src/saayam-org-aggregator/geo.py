"""Geocoding and distance utilities for saayam-org-aggregator.

Everything provider-specific lives behind ``GeocodingProvider``. No provider is
hard-coded: the approved one is registered with ``register_provider`` and
selected with the ``GEOCODING_PROVIDER`` environment variable. Until a provider
is configured, addresses that are not already cached resolve to ``deferred``
and the Organizations API still returns every organization.

Distances are straight-line (great-circle / haversine) miles. They are NOT
driving distance or travel time.
"""

import hashlib
import json
import logging
import math
import os
import re
import struct
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, Optional, Tuple

logger = logging.getLogger(__name__)

EARTH_RADIUS_MILES = 3958.7613
DISTANCE_UNIT = "miles"
DISTANCE_METHOD = "straight_line"

STATUS_OK = "ok"
STATUS_ONLINE = "online"
STATUS_UNKNOWN_LOCATION = "unknown_location"
STATUS_NOT_FOUND = "not_found"
STATUS_DEFERRED = "deferred"
STATUS_ERROR = "error"

Coordinates = Tuple[float, float]  # (latitude, longitude)


# ---------------------------------------------------------------------------
# Distance
# ---------------------------------------------------------------------------

def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles between two lat/lon points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(a)))


def calculate_distance(origin: Coordinates, destination: Coordinates):
    """Straight-line miles between two (lat, lon) tuples, rounded to 0.1."""
    miles = haversine_miles(origin[0], origin[1], destination[0], destination[1])
    return round(miles, 1)


def distance_fields(distance=None, status=STATUS_UNKNOWN_LOCATION):
    """The four distance fields every organization carries in the response.

    ``distance`` is only ever a number when ``status`` is ``ok``; unknown
    distance is always ``None`` (JSON null), never 0.
    """
    if status != STATUS_OK:
        distance = None
    return {
        "distance": distance,
        "distance_unit": DISTANCE_UNIT,
        "distance_method": DISTANCE_METHOD,
        "distance_status": status,
    }


# ---------------------------------------------------------------------------
# Coordinate parsing (requests.req_loc, user_locations.curr_loc, GenAI fields)
# ---------------------------------------------------------------------------

_NUM = r"[-+]?\d+(?:\.\d+)?"
_LAT_RE = re.compile(r"\b(?:latitude|lat)\b\s*[:=]\s*(" + _NUM + ")", re.I)
_LON_RE = re.compile(
    r"\b(?:longitude|long|lng|lon)\b\s*[:=]\s*(" + _NUM + ")", re.I
)
_POINT_RE = re.compile(
    r"^(?:SRID=\d+;)?\s*POINT\s*Z?\s*\(\s*(" + _NUM + r")\s+(" + _NUM + r")",
    re.I,
)
_PG_POINT_RE = re.compile(r"^\(\s*(" + _NUM + r")\s*,\s*(" + _NUM + r")\s*\)$")
_PAIR_RE = re.compile(r"^(" + _NUM + r")\s*,\s*(" + _NUM + r")$")
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


def _is_missing(value):
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def valid_coordinates(lat, lon) -> Optional[Coordinates]:
    """Return (lat, lon) floats if in range, else None.

    Exactly (0, 0) is treated as a placeholder, not a real location.
    """
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if math.isnan(lat) or math.isnan(lon):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if lat == 0 and lon == 0:
        return None
    return lat, lon


def _parse_wkb_point(raw: bytes) -> Optional[Coordinates]:
    """Parse a (E)WKB POINT, as PostGIS returns geography/geometry columns."""
    if len(raw) < 21:
        return None
    order = "<" if raw[0] == 1 else ">"
    geom_type = struct.unpack(order + "I", raw[1:5])[0]
    offset = 5
    if geom_type & 0x20000000:  # EWKB SRID flag
        offset += 4
    if (geom_type & 0x0FFFFFFF) % 1000 != 1:  # not a point
        return None
    if len(raw) < offset + 16:
        return None
    x, y = struct.unpack(order + "dd", raw[offset:offset + 16])
    return valid_coordinates(y, x)


def _from_mapping(value: dict) -> Optional[Coordinates]:
    if value.get("type") == "Point" and isinstance(
        value.get("coordinates"), (list, tuple)
    ):
        coords = value["coordinates"]
        if len(coords) >= 2:
            return valid_coordinates(coords[1], coords[0])  # GeoJSON lon, lat
    lowered = {str(k).lower(): v for k, v in value.items()}
    lat = next(
        (lowered[k] for k in ("latitude", "lat") if k in lowered), None
    )
    lon = next(
        (lowered[k] for k in ("longitude", "lng", "lon", "long") if k in lowered),
        None,
    )
    if lat is None or lon is None:
        return None
    return valid_coordinates(lat, lon)


def parse_coordinates(value) -> Optional[Coordinates]:
    """Best-effort parse of a stored location into (lat, lon).

    Supported shapes:
      * "longitude:-121.9780,latitude:37.7799" (any order, lat/lng aliases)
      * dict / JSON {"latitude": .., "longitude": ..} or GeoJSON Point
      * WKT "POINT(lon lat)" / "SRID=4326;POINT(lon lat)"
      * PostGIS hex (E)WKB, bytes or memoryview
      * Postgres point "(x,y)" -> x is longitude
      * bare "lat, lon" pair
    Returns None for anything unparseable or out of range.
    """
    if _is_missing(value):
        return None
    try:
        if isinstance(value, dict):
            return _from_mapping(value)
        if isinstance(value, memoryview):
            value = value.tobytes()
        if isinstance(value, (bytes, bytearray)):
            return _parse_wkb_point(bytes(value))

        text = str(value).strip()

        if text.startswith("{"):
            try:
                return _from_mapping(json.loads(text))
            except (json.JSONDecodeError, AttributeError):
                pass

        lat_m, lon_m = _LAT_RE.search(text), _LON_RE.search(text)
        if lat_m and lon_m:
            return valid_coordinates(lat_m.group(1), lon_m.group(1))

        m = _POINT_RE.match(text)
        if m:
            return valid_coordinates(m.group(2), m.group(1))

        if _HEX_RE.match(text) and len(text) >= 42 and len(text) % 2 == 0:
            return _parse_wkb_point(bytes.fromhex(text))

        m = _PG_POINT_RE.match(text)
        if m:
            return valid_coordinates(m.group(2), m.group(1))

        m = _PAIR_RE.match(text)
        if m:
            return valid_coordinates(m.group(1), m.group(2))
    except (ValueError, struct.error) as e:
        logger.warning("Could not parse coordinates %r: %s", value, e)
    return None


# ---------------------------------------------------------------------------
# Address helpers
# ---------------------------------------------------------------------------

_ONLINE_WORDS = {
    "online", "virtual", "remote", "remotely", "web", "based", "internet",
    "only", "digital", "service", "services", "and", "or", "via",
}
_VAGUE_LOCATIONS = {
    "", "n/a", "na", "none", "null", "unknown", "not available", "various",
    "nationwide", "national", "global", "worldwide", "international",
    "united states", "united states of america", "usa", "us", "u.s.",
    "u.s.a.", "america", "india",
}


def normalize_address(address) -> Optional[str]:
    if _is_missing(address):
        return None
    text = re.sub(r"\s+", " ", str(address)).strip().strip(",").strip()
    text = re.sub(r"\s*,\s*", ", ", text)
    return text.lower() or None


def address_key(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_online_location(text) -> bool:
    """True when a location string only says the org is online/virtual."""
    if _is_missing(text):
        return False
    tokens = re.findall(r"[a-z]+", str(text).lower())
    return (
        bool(tokens)
        and set(tokens) <= _ONLINE_WORDS
        and bool(set(tokens) & {"online", "virtual", "remote", "remotely",
                                "internet", "web", "digital"})
    )


def is_too_vague(text) -> bool:
    """True for strings that are not a real place (e.g. 'United States').

    Geocoding these would return a country centroid and a misleading
    distance, so they are treated as unknown locations instead.
    """
    norm = normalize_address(text)
    return norm is None or norm in _VAGUE_LOCATIONS


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------

class GeocodingError(Exception):
    """Provider failed (network error, bad response, auth, ...)."""


class GeocodingTimeoutError(GeocodingError):
    """Provider did not answer in time."""


class GeocodingRateLimitError(GeocodingError):
    """Provider quota / rate limit hit; try again later."""


class GeocodingProvider:
    """Interface the approved geocoding provider must implement.

    ``geocode`` returns ``(latitude, longitude)`` or ``None`` when the
    address cannot be matched. It raises ``GeocodingRateLimitError`` for
    quota problems, ``GeocodingTimeoutError`` for timeouts and
    ``GeocodingError`` for anything else.
    """

    name = "base"

    def geocode(self, address: str) -> Optional[Coordinates]:
        raise NotImplementedError


_PROVIDER_FACTORIES: Dict[str, Callable[[], GeocodingProvider]] = {}
_provider_instance: Optional[GeocodingProvider] = None
_provider_loaded = False


def register_provider(name: str, factory: Callable[[], GeocodingProvider]):
    """Register a provider factory under ``name`` (e.g. in a provider module).

    Example once the provider is approved::

        class ApprovedProvider(GeocodingProvider):
            name = "approved"
            def geocode(self, address):
                ...  # call the API, return (lat, lon) or None

        register_provider("approved", ApprovedProvider)

    and set the Lambda environment variable GEOCODING_PROVIDER=approved.
    """
    global _provider_loaded
    _PROVIDER_FACTORIES[name.lower()] = factory
    _provider_loaded = False


def get_provider() -> Optional[GeocodingProvider]:
    """Return the configured provider, or None if none is configured."""
    global _provider_instance, _provider_loaded
    if _provider_loaded:
        return _provider_instance
    _provider_loaded = True
    name = os.environ.get("GEOCODING_PROVIDER", "").strip().lower()
    if not name:
        _provider_instance = None
    elif name not in _PROVIDER_FACTORIES:
        logger.warning("GEOCODING_PROVIDER=%r is not registered", name)
        _provider_instance = None
    else:
        _provider_instance = _PROVIDER_FACTORIES[name]()
    return _provider_instance


# ---------------------------------------------------------------------------
# Cache (in-memory per warm container + optional DB table)
# ---------------------------------------------------------------------------

@dataclass
class GeocodeResult:
    status: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    provider: Optional[str] = None
    cached: bool = False

    @property
    def coordinates(self) -> Optional[Coordinates]:
        if self.status == STATUS_OK and self.latitude is not None:
            return self.latitude, self.longitude
        return None


class GeocodeCache:
    """Address -> coordinates cache.

    Only ``ok`` and ``not_found`` results are stored. ``deferred`` and
    ``error`` are transient and retried next time. ``not_found`` entries
    expire after ``negative_ttl_days`` so fixed addresses get retried.

    The DB layer is optional: if the table is missing or the DB user cannot
    write to it, the cache falls back to memory only and logs once.
    """

    def __init__(self, conn=None, schema=None, table="geocode_cache",
                 negative_ttl_days=30):
        self._memory: Dict[str, Tuple[GeocodeResult, float]] = {}
        self._conn = conn
        self._table = f"{schema}.{table}" if schema else table
        self._db_read = conn is not None
        self._db_write = conn is not None
        self._negative_ttl = negative_ttl_days * 86400

    def _disable(self, what, error):
        try:
            self._conn.rollback()
        except Exception:  # pragma: no cover - best effort
            pass
        logger.warning("Geocode cache DB %s disabled: %s", what, error)

    def get_many(self, keys: Iterable[str]) -> Dict[str, GeocodeResult]:
        now = time.time()
        found, missing = {}, []
        for key in set(keys):
            hit = self._memory.get(key)
            if hit and not (
                hit[0].status == STATUS_NOT_FOUND
                and now - hit[1] > self._negative_ttl
            ):
                found[key] = hit[0]
            else:
                missing.append(key)

        if missing and self._db_read:
            try:
                cur = self._conn.cursor()
                cur.execute(
                    f"""
                    SELECT address_key, latitude, longitude, status, provider,
                           EXTRACT(EPOCH FROM updated_at)
                    FROM {self._table}
                    WHERE address_key = ANY(%s)
                    """,
                    (missing,),
                )
                for key, lat, lon, status, provider, updated in cur.fetchall():
                    updated = float(updated or now)
                    if status == STATUS_NOT_FOUND and now - updated > self._negative_ttl:
                        continue
                    result = GeocodeResult(
                        status=status,
                        latitude=float(lat) if lat is not None else None,
                        longitude=float(lon) if lon is not None else None,
                        provider=provider,
                        cached=True,
                    )
                    self._memory[key] = (result, updated)
                    found[key] = result
            except Exception as e:
                self._db_read = self._db_write = False
                self._disable("read", e)

        for key in found:
            found[key] = GeocodeResult(**{**found[key].__dict__, "cached": True})
        return found

    def put(self, key: str, normalized_address: str, result: GeocodeResult):
        if result.status not in (STATUS_OK, STATUS_NOT_FOUND):
            return
        self._memory[key] = (result, time.time())
        if not self._db_write:
            return
        try:
            cur = self._conn.cursor()
            cur.execute(
                f"""
                INSERT INTO {self._table}
                    (address_key, normalized_address, latitude, longitude,
                     status, provider, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (address_key) DO UPDATE SET
                    latitude = EXCLUDED.latitude,
                    longitude = EXCLUDED.longitude,
                    status = EXCLUDED.status,
                    provider = EXCLUDED.provider,
                    updated_at = now()
                """,
                (key, normalized_address, result.latitude, result.longitude,
                 result.status, result.provider),
            )
            self._conn.commit()
        except Exception as e:
            self._db_write = False
            self._disable("write", e)


# ---------------------------------------------------------------------------
# Geocoder (one per Lambda invocation; cache is shared across invocations)
# ---------------------------------------------------------------------------

class Geocoder:
    """Cache-first geocoding with a per-invocation call budget.

    ``max_calls`` bounds provider calls per request so a long organization
    list cannot blow up latency or cost; addresses beyond the budget come
    back ``deferred`` and get geocoded on a later page load. After a rate
    limit error, every further lookup in the invocation is ``deferred``.
    """

    def __init__(self, provider=None, cache=None, max_calls=None):
        self.provider = provider
        self.cache = cache or GeocodeCache()
        if max_calls is None:
            max_calls = int(os.environ.get("GEOCODING_MAX_CALLS_PER_REQUEST", "10"))
        self.max_calls = max_calls
        self.calls = 0
        self._rate_limited = False

    def prefetch(self, addresses: Iterable[str]):
        keys = [address_key(n) for n in map(normalize_address, addresses) if n]
        if keys:
            self.cache.get_many(keys)

    def geocode(self, address) -> GeocodeResult:
        normalized = normalize_address(address)
        if normalized is None or is_too_vague(normalized):
            return GeocodeResult(STATUS_UNKNOWN_LOCATION)

        key = address_key(normalized)
        hit = self.cache.get_many([key]).get(key)
        if hit:
            return hit

        if self.provider is None:
            return GeocodeResult(STATUS_DEFERRED)
        if self._rate_limited or self.calls >= self.max_calls:
            return GeocodeResult(STATUS_DEFERRED)

        self.calls += 1
        try:
            coords = self.provider.geocode(str(address).strip())
        except GeocodingRateLimitError as e:
            self._rate_limited = True
            logger.warning("Geocoding rate limited: %s", e)
            return GeocodeResult(STATUS_DEFERRED)
        except Exception as e:  # timeouts, network, provider bugs
            logger.warning("Geocoding failed for %r: %s", normalized, e)
            return GeocodeResult(STATUS_ERROR)

        coords = valid_coordinates(*coords) if coords else None
        if coords:
            result = GeocodeResult(
                STATUS_OK, coords[0], coords[1], self.provider.name
            )
        else:
            result = GeocodeResult(STATUS_NOT_FOUND, provider=self.provider.name)
        self.cache.put(key, normalized, result)
        return result


_default_geocoder: Optional[Geocoder] = None


def geocode_address(address) -> GeocodeResult:
    """Reusable entry point: address -> GeocodeResult (lat/lon + status)."""
    global _default_geocoder
    if _default_geocoder is None:
        _default_geocoder = Geocoder(provider=get_provider())
    return _default_geocoder.geocode(address)
