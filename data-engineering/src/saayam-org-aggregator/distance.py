"""Distance helpers for the org aggregator.

Pure logic (parsing, haversine, caching, status handling) lives here so it can be
tested without AWS/DB access. DB access takes an already-open connection.
"""
import math
import os
import re

DISTANCE_UNIT = "miles"
DISTANCE_METHOD = "straight_line"
EARTH_RADIUS_MILES = 3958.8
MAX_GEOCODES_PER_REQUEST = int(os.environ.get("MAX_GEOCODES_PER_REQUEST", "10"))

ONLINE_MARKERS = {"online", "remote", "virtual", "n/a-online"}


class GeocodeNotFound(Exception):
    """The address could not be matched to coordinates."""


class GeocoderUnavailable(Exception):
    """No geocoding provider is configured (or it is rate limited)."""


# --------------------------------------------------------------------------
# Geocoding (provider-agnostic)
# --------------------------------------------------------------------------
# Register an approved provider with register_geocoder("name", fn) and select it
# with the GEOCODER_PROVIDER env var. A provider is `fn(address) -> (lat, lon)`
# and raises GeocodeNotFound when there is no match.
_GEOCODERS = {}


def register_geocoder(name, fn):
    _GEOCODERS[name] = fn


def geocode_address(address):
    """Return (latitude, longitude) for an address using the configured provider."""
    provider = os.environ.get("GEOCODER_PROVIDER")
    fn = _GEOCODERS.get(provider)
    if fn is None:
        raise GeocoderUnavailable("no geocoding provider configured")
    return fn(address)


class CoordinateCache:
    """In-memory cache, optionally backed by a persistent store.

    `store` is any object with get(key) -> (lat, lon) | None and
    set(key, lat, lon). Store failures never propagate.
    """

    def __init__(self, store=None):
        self._mem = {}
        self._store = store

    @staticmethod
    def key(address):
        return re.sub(r"\s+", " ", address.strip().lower())

    def get(self, address):
        k = self.key(address)
        if k in self._mem:
            return self._mem[k]
        if self._store:
            try:
                hit = self._store.get(k)
            except Exception:
                self._store_failed()
                hit = None
            if hit:
                self._mem[k] = hit
                return hit
        return None

    def set(self, address, lat, lon):
        k = self.key(address)
        self._mem[k] = (lat, lon)
        if self._store:
            try:
                self._store.set(k, lat, lon)
            except Exception:
                self._store_failed()

    def _store_failed(self):
        # A failed statement aborts the Postgres transaction; reset it.
        rollback = getattr(self._store, "rollback", None)
        if rollback:
            rollback()


class DbCoordinateStore:
    """Persistent cache in `<schema>.org_geocode_cache` (created on first use)."""

    def __init__(self, conn, schema):
        self._conn = conn
        self._table = f"{schema}.org_geocode_cache"
        self._ready = False

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    def _ensure(self):
        if self._ready:
            return
        cur = self._conn.cursor()
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {self._table} ("
            "address_key TEXT PRIMARY KEY, latitude DOUBLE PRECISION NOT NULL, "
            "longitude DOUBLE PRECISION NOT NULL, updated_at TIMESTAMPTZ DEFAULT now())"
        )
        self._conn.commit()
        self._ready = True

    def get(self, key):
        self._ensure()
        cur = self._conn.cursor()
        cur.execute(f"SELECT latitude, longitude FROM {self._table} WHERE address_key = %s", (key,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else None

    def set(self, key, lat, lon):
        self._ensure()
        cur = self._conn.cursor()
        cur.execute(
            f"INSERT INTO {self._table} (address_key, latitude, longitude) VALUES (%s, %s, %s) "
            "ON CONFLICT (address_key) DO NOTHING",
            (key, lat, lon),
        )
        self._conn.commit()


# --------------------------------------------------------------------------
# Coordinates
# --------------------------------------------------------------------------
_LABELLED = re.compile(
    r"longitude\s*:\s*(-?\d+(?:\.\d+)?)\s*,\s*latitude\s*:\s*(-?\d+(?:\.\d+)?)", re.I
)
_POINT = re.compile(r"POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)", re.I)


def _valid(lat, lon):
    return -90 <= lat <= 90 and -180 <= lon <= 180


def parse_coordinates(text):
    """Parse 'longitude:-121.9,latitude:37.7' or '[SRID=4326;]POINT(lon lat)'.

    Returns (lat, lon) or None. Free-text such as 'Suffolk, VA' returns None.
    """
    if not text or not isinstance(text, str):
        return None
    m = _LABELLED.search(text)
    if m:
        lon, lat = float(m.group(1)), float(m.group(2))
    else:
        m = _POINT.search(text)
        if not m:
            return None
        lon, lat = float(m.group(1)), float(m.group(2))
    return (lat, lon) if _valid(lat, lon) else None


def haversine_miles(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(h)))


# --------------------------------------------------------------------------
# Beneficiary location
# --------------------------------------------------------------------------
def build_address(*parts):
    """Join non-empty address parts; returns None if nothing usable."""
    cleaned = [str(p).strip() for p in parts if p is not None and str(p).strip()
               and str(p).strip().lower() not in ("nan", "none", "null")]
    return ", ".join(cleaned) or None


def get_beneficiary_coordinates(conn, schema, request_id, cache=None):
    """Resolve beneficiary coordinates: req_loc -> user_locations -> profile address.

    Returns (lat, lon) or None. Never falls back to a default location.
    """
    if not request_id:
        return None
    cur = conn.cursor()

    cur.execute(f"SELECT req_loc, beneficiary_id FROM {schema}.requests WHERE req_id = %s", (request_id,))
    row = cur.fetchone()
    if not row:
        return None
    req_loc, beneficiary_id = row

    coords = parse_coordinates(req_loc)
    if coords or not beneficiary_id:
        return coords

    cur.execute(
        f"SELECT ST_AsText(curr_loc) FROM {schema}.user_locations WHERE user_id = %s",
        (beneficiary_id,),
    )
    row = cur.fetchone()
    coords = parse_coordinates(row[0]) if row else None
    if coords:
        return coords

    cur.execute(
        f"SELECT u.addr_ln1, u.city_name, s.state_name, u.zip_code, c.country_name "
        f"FROM {schema}.users u "
        f"LEFT JOIN {schema}.states s ON s.state_id = u.state_id "
        f"LEFT JOIN {schema}.countries c ON c.country_id = u.country_id "
        f"WHERE u.user_id = %s",
        (beneficiary_id,),
    )
    row = cur.fetchone()
    address = build_address(*row) if row else None
    if not address:
        return None
    return _resolve(address, cache or CoordinateCache())[0]


# --------------------------------------------------------------------------
# Per-organization distance
# --------------------------------------------------------------------------
def _resolve(address, cache):
    """Return ((lat, lon) | None, status). Uses cache before geocoding."""
    hit = cache.get(address)
    if hit:
        return hit, "ok"
    try:
        lat, lon = geocode_address(address)
    except GeocodeNotFound:
        return None, "not_found"
    except GeocoderUnavailable:
        return None, "deferred"
    except Exception:
        return None, "error"
    cache.set(address, lat, lon)
    return (lat, lon), "ok"


def _blank(status, distance=None):
    return {
        "distance": distance,
        "distance_unit": DISTANCE_UNIT,
        "distance_method": DISTANCE_METHOD,
        "distance_status": status,
    }


def compute_org_distance(beneficiary, address, cache, budget):
    """Distance fields for one org. `budget` is a one-element list counting
    remaining uncached geocode calls for this request. Never raises."""
    try:
        if not address or not str(address).strip():
            return _blank("unknown_location")
        if str(address).strip().lower() in ONLINE_MARKERS:
            return _blank("online")
        if beneficiary is None:
            return _blank("unknown_location")

        coords = cache.get(address)
        if coords is None:
            if budget[0] <= 0:
                return _blank("deferred")
            budget[0] -= 1
            coords, status = _resolve(address, cache)
            if coords is None:
                return _blank(status)

        return _blank("ok", round(haversine_miles(beneficiary, coords), 1))
    except Exception:
        return _blank("error")


def add_distances(orgs, beneficiary, cache, address_of):
    """Return a list of org dicts with distance fields added.

    `address_of(org_dict)` returns the geocodable address string (or None).
    """
    budget = [MAX_GEOCODES_PER_REQUEST]
    out = []
    for org in orgs:
        org = dict(org)
        try:
            addr = address_of(org)
        except Exception:
            addr = None
        org.update(compute_org_distance(beneficiary, addr, cache, budget))
        out.append(org)
    return out


def sort_by_distance(orgs):
    """Nearest first; unknown (None) last. Stable for ties."""
    return sorted(orgs, key=lambda o: (o.get("distance") is None, o.get("distance") or 0))
