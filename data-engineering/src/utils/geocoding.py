"""Provider-agnostic geocoding with coordinate caching.

No geocoding provider is hard-coded here. The provider is chosen at runtime
from the ``GEOCODING_PROVIDER`` environment variable:

* ``none`` (default): no provider is configured yet. Cached coordinates are
  still reused; uncached addresses come back with status ``deferred``.
* a name registered with :func:`register_provider`.
* ``"package.module:factory"``: an import path to a zero-argument callable
  that returns a :class:`GeocodingProvider`. Once a provider is approved,
  it can be added without editing the Lambda code.

Every lookup goes through a coordinate cache: an in-memory LRU that
survives warm Lambda invocations, plus an optional PostgreSQL table
(``GEOCODE_CACHE_BACKEND=postgres``). Addresses that were successfully
geocoded or not found are cached. Errors and deferrals are not cached, so
they are retried on the next request.

Typical use::

    from utils.geocoding import geocode_address
    result = geocode_address("1600 Amphitheatre Pkwy, Mountain View, CA 94043")
    if result.status == "ok":
        print(result.coordinates.latitude, result.coordinates.longitude)
"""

from __future__ import annotations

import importlib
import logging
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from .geo import Coordinates, make_coordinates

logger = logging.getLogger(__name__)

GEOCODE_OK = "ok"
GEOCODE_NOT_FOUND = "not_found"
GEOCODE_DEFERRED = "deferred"
GEOCODE_ERROR = "error"
GEOCODE_NO_ADDRESS = "unknown_location"

DEFAULT_TIMEOUT_SECONDS = 3.0
DEFAULT_MAX_LOOKUPS_PER_REQUEST = 10
DEFAULT_TIME_BUDGET_SECONDS = 5.0
DEFAULT_NOT_FOUND_TTL = timedelta(days=30)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


# --------------------------------------------------------------------------- #
# Errors and results
# --------------------------------------------------------------------------- #
class GeocodingError(Exception):
    """Base class for provider errors that map to a specific status."""


class GeocodingUnavailableError(GeocodingError):
    """No provider is configured or approved yet. Maps to ``deferred``."""


class GeocodingRateLimitError(GeocodingError):
    """The provider's rate limit or quota was hit. Maps to ``deferred``."""


@dataclass(frozen=True)
class GeocodeResult:
    """Outcome of a single geocoding lookup."""

    status: str
    coordinates: Optional[Coordinates] = None
    provider: Optional[str] = None
    from_cache: bool = False
    message: Optional[str] = None

    @property
    def ok(self) -> bool:
        """True when coordinates are available."""
        return self.status == GEOCODE_OK and self.coordinates is not None


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
class GeocodingProvider(ABC):
    """Interface every geocoding provider adapter must implement.

    ``geocode`` must:
      * return :class:`Coordinates` when the address is found,
      * return ``None`` when the provider has no match,
      * raise :class:`GeocodingRateLimitError` on quota/rate limits,
      * raise any other exception (including timeouts) on failure.

    Adapters should use :func:`provider_timeout_seconds` for network timeouts.
    """

    name: str = "base"

    @abstractmethod
    def geocode(self, address: str) -> Optional[Coordinates]:
        """Convert a postal address into coordinates."""


class NullGeocodingProvider(GeocodingProvider):
    """Placeholder used until a provider is approved."""

    name = "none"

    def geocode(self, address: str) -> Optional[Coordinates]:
        """Always defer: there is no provider to call."""
        raise GeocodingUnavailableError(
            "No geocoding provider is configured (set GEOCODING_PROVIDER)."
        )


_PROVIDER_FACTORIES: dict[str, Callable[[], GeocodingProvider]] = {
    "none": NullGeocodingProvider,
}
_provider_lock = threading.Lock()
_default_provider: Optional[GeocodingProvider] = None


def register_provider(name: str, factory: Callable[[], GeocodingProvider]) -> None:
    """Register a provider factory under a name usable in GEOCODING_PROVIDER."""
    _PROVIDER_FACTORIES[name.strip().lower()] = factory


def provider_timeout_seconds() -> float:
    """Network timeout that provider adapters should apply to each call."""
    return _env_float("GEOCODING_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)


def get_provider(name: Optional[str] = None) -> GeocodingProvider:
    """Build the provider named explicitly or by GEOCODING_PROVIDER.

    Falls back to :class:`NullGeocodingProvider` (with a warning) when the
    name is unknown or the factory fails, so geocoding problems never break
    the caller.
    """
    key = (name or os.getenv("GEOCODING_PROVIDER") or "none").strip()
    try:
        if ":" in key:
            module_name, attr = key.split(":", 1)
            factory = getattr(importlib.import_module(module_name), attr)
        else:
            factory = _PROVIDER_FACTORIES.get(key.lower())
            if factory is None:
                logger.warning("Unknown GEOCODING_PROVIDER %r; geocoding disabled.", key)
                return NullGeocodingProvider()
        provider = factory()
        if not isinstance(provider, GeocodingProvider):
            raise TypeError(f"{key!r} did not return a GeocodingProvider")
        return provider
    except Exception:  # noqa: BLE001 - never let provider setup break the API
        logger.exception("Could not initialise geocoding provider %r; geocoding disabled.", key)
        return NullGeocodingProvider()


def get_default_provider() -> GeocodingProvider:
    """Return the process-wide provider, creating it on first use."""
    global _default_provider
    with _provider_lock:
        if _default_provider is None:
            _default_provider = get_provider()
        return _default_provider


def set_default_provider(provider: Optional[GeocodingProvider]) -> None:
    """Override (or reset with None) the process-wide provider."""
    global _default_provider
    with _provider_lock:
        _default_provider = provider


# --------------------------------------------------------------------------- #
# Coordinate cache
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CacheEntry:
    """A cached geocoding outcome (``ok`` or ``not_found``)."""

    status: str
    coordinates: Optional[Coordinates] = None
    provider: Optional[str] = None
    cached_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CoordinateCache(ABC):
    """Storage for geocoding results keyed by normalized address."""

    @abstractmethod
    def get(self, key: str) -> Optional[CacheEntry]:
        """Return the cached entry for ``key`` or None."""

    @abstractmethod
    def set(self, key: str, address: str, entry: CacheEntry) -> None:
        """Store ``entry`` for ``key``."""


def _is_expired(entry: CacheEntry, not_found_ttl: timedelta) -> bool:
    if entry.status != GEOCODE_NOT_FOUND:
        return False
    cached_at = entry.cached_at
    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - cached_at > not_found_ttl


class InMemoryCoordinateCache(CoordinateCache):
    """Thread-safe LRU cache that lives for the life of the Lambda container."""

    def __init__(self, max_entries: int = 5000, not_found_ttl: timedelta = DEFAULT_NOT_FOUND_TTL):
        self._entries: "OrderedDict[str, CacheEntry]" = OrderedDict()
        self._max_entries = max_entries
        self._not_found_ttl = not_found_ttl
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[CacheEntry]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if _is_expired(entry, self._not_found_ttl):
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return entry

    def set(self, key: str, address: str, entry: CacheEntry) -> None:
        with self._lock:
            self._entries[key] = entry
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        """Remove every entry (used by tests)."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


class PostgresCoordinateCache(CoordinateCache):
    """Coordinate cache stored in a PostgreSQL table shared by all containers.

    The table is created by
    ``infrastructure/db/geocode_cache/001_geocode_cache.sql``. Every failure
    is logged and swallowed. A failed write (for example, a read-only DB
    user) turns off further writes for this container instead of failing
    requests.

    Args:
        connection: a DB-API connection, or a zero-argument callable that
            returns one (psycopg2 and pg8000 both work).
        table: optionally schema-qualified table name.
    """

    def __init__(
        self,
        connection: Any,
        table: str = "geocode_cache",
        not_found_ttl: timedelta = DEFAULT_NOT_FOUND_TTL,
    ):
        if not _IDENTIFIER.match(table):
            raise ValueError(f"Invalid cache table name: {table!r}")
        self._connection = connection
        self._table = table
        self._not_found_ttl = not_found_ttl
        self._writes_enabled = True
        self._lock = threading.Lock()

    def _conn(self) -> Any:
        return self._connection() if callable(self._connection) else self._connection

    def get(self, key: str) -> Optional[CacheEntry]:
        with self._lock:
            conn = None
            try:
                conn = self._conn()
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT status, latitude, longitude, provider, updated_at "
                    f"FROM {self._table} WHERE address_key = %s",
                    (key,),
                )
                row = cursor.fetchone()
                cursor.close()
                _safe_commit(conn)
            except Exception:  # noqa: BLE001
                logger.warning("Geocode cache read failed", exc_info=True)
                _safe_rollback(conn)
                return None
        if not row:
            return None
        status, lat, lon, provider, updated_at = row
        coords = make_coordinates(lat, lon) if status == GEOCODE_OK else None
        if status == GEOCODE_OK and coords is None:
            return None
        entry = CacheEntry(
            status=status,
            coordinates=coords,
            provider=provider,
            cached_at=updated_at or datetime.now(timezone.utc),
        )
        return None if _is_expired(entry, self._not_found_ttl) else entry

    def set(self, key: str, address: str, entry: CacheEntry) -> None:
        if not self._writes_enabled:
            return
        lat = entry.coordinates.latitude if entry.coordinates else None
        lon = entry.coordinates.longitude if entry.coordinates else None
        with self._lock:
            conn = None
            try:
                conn = self._conn()
                cursor = conn.cursor()
                cursor.execute(
                    f"""
                    INSERT INTO {self._table}
                        (address_key, address, latitude, longitude, status, provider, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, now(), now())
                    ON CONFLICT (address_key) DO UPDATE SET
                        address = EXCLUDED.address,
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude,
                        status = EXCLUDED.status,
                        provider = EXCLUDED.provider,
                        updated_at = now()
                    """,
                    (key, address[:1000], lat, lon, entry.status, entry.provider),
                )
                cursor.close()
                conn.commit()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Geocode cache write failed; disabling writes for this container",
                    exc_info=True,
                )
                self._writes_enabled = False
                _safe_rollback(conn)


class TieredCoordinateCache(CoordinateCache):
    """In-memory cache in front of an optional persistent cache."""

    def __init__(self, memory: CoordinateCache, persistent: Optional[CoordinateCache] = None):
        self.memory = memory
        self.persistent = persistent

    def get(self, key: str) -> Optional[CacheEntry]:
        entry = self.memory.get(key)
        if entry is not None or self.persistent is None:
            return entry
        entry = self.persistent.get(key)
        if entry is not None:
            self.memory.set(key, "", entry)
        return entry

    def set(self, key: str, address: str, entry: CacheEntry) -> None:
        self.memory.set(key, address, entry)
        if self.persistent is not None:
            self.persistent.set(key, address, entry)


# Shared across warm invocations of the same Lambda container.
_MEMORY_CACHE = InMemoryCoordinateCache()
_default_cache: CoordinateCache = TieredCoordinateCache(_MEMORY_CACHE)


def get_default_cache() -> CoordinateCache:
    """Return the process-wide coordinate cache."""
    return _default_cache


def set_default_cache(cache: Optional[CoordinateCache]) -> None:
    """Override (or reset with None) the process-wide coordinate cache."""
    global _default_cache
    _default_cache = cache if cache is not None else TieredCoordinateCache(_MEMORY_CACHE)


def build_cache_from_env(connection: Any = None, default_table: str = "geocode_cache") -> CoordinateCache:
    """Build the cache selected by GEOCODE_CACHE_BACKEND.

    * ``memory`` (default): in-memory only.
    * ``postgres``: in-memory in front of the table named by
      GEOCODE_CACHE_TABLE (default ``default_table``) on ``connection``.
    """
    backend = (os.getenv("GEOCODE_CACHE_BACKEND") or "memory").strip().lower()
    if backend == "postgres" and connection is not None:
        try:
            table = os.getenv("GEOCODE_CACHE_TABLE") or default_table
            return TieredCoordinateCache(_MEMORY_CACHE, PostgresCoordinateCache(connection, table))
        except Exception:  # noqa: BLE001
            logger.exception("Could not configure the Postgres geocode cache; using memory only.")
    elif backend not in ("memory", "postgres"):
        logger.warning("Unknown GEOCODE_CACHE_BACKEND %r; using memory only.", backend)
    return TieredCoordinateCache(_MEMORY_CACHE)


# --------------------------------------------------------------------------- #
# Per-request lookup budget
# --------------------------------------------------------------------------- #
class LookupBudget:
    """Caps live provider calls in one API request.

    Calls past the cap or the time budget are reported as ``deferred``, so a
    slow or rate-limited provider cannot push the Organizations API past the
    API Gateway timeout. Cached results never use up the budget.
    """

    def __init__(
        self,
        max_lookups: Optional[int] = DEFAULT_MAX_LOOKUPS_PER_REQUEST,
        max_seconds: Optional[float] = DEFAULT_TIME_BUDGET_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_lookups = max_lookups
        self.max_seconds = max_seconds
        self._clock = clock
        self._started = clock()
        self.used = 0
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "LookupBudget":
        """Read GEOCODING_MAX_LOOKUPS_PER_REQUEST / GEOCODING_TIME_BUDGET_SECONDS."""
        return cls(
            max_lookups=_env_int("GEOCODING_MAX_LOOKUPS_PER_REQUEST", DEFAULT_MAX_LOOKUPS_PER_REQUEST),
            max_seconds=_env_float("GEOCODING_TIME_BUDGET_SECONDS", DEFAULT_TIME_BUDGET_SECONDS),
        )

    def try_acquire(self) -> bool:
        """Reserve one live lookup. Returns False when the budget is spent."""
        with self._lock:
            if self.max_lookups is not None and self.used >= self.max_lookups:
                return False
            if self.max_seconds is not None and self._clock() - self._started >= self.max_seconds:
                return False
            self.used += 1
            return True


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
_WHITESPACE = re.compile(r"\s+")
_SPACE_BEFORE_COMMA = re.compile(r"\s*,\s*")
_REPEATED_COMMAS = re.compile(r",(\s*,)+")


def normalize_address(address: str) -> str:
    """Normalize an address into a stable cache key."""
    text = (address or "").strip().lower()
    text = text.replace(".", " ").replace("#", " ")
    text = _WHITESPACE.sub(" ", text)
    text = _SPACE_BEFORE_COMMA.sub(", ", text)
    text = _REPEATED_COMMAS.sub(",", text)
    return text.strip(" ,")


def geocode_address(
    address: Optional[str],
    *,
    provider: Optional[GeocodingProvider] = None,
    cache: Optional[CoordinateCache] = None,
    budget: Optional[LookupBudget] = None,
) -> GeocodeResult:
    """Convert an address to coordinates, checking the cache first.

    Never raises. Statuses:
      * ``ok``: coordinates found (cached or live)
      * ``not_found``: the provider had no match (cached to avoid repeats)
      * ``deferred``: no provider configured, rate-limited, or the
        per-request lookup budget is spent
      * ``error``: the provider failed or timed out
      * ``unknown_location``: the address was empty
    """
    if not address or not str(address).strip():
        return GeocodeResult(GEOCODE_NO_ADDRESS, message="empty address")

    address = str(address).strip()
    key = normalize_address(address)
    cache = cache if cache is not None else get_default_cache()

    try:
        cached = cache.get(key)
    except Exception:  # noqa: BLE001
        logger.warning("Geocode cache lookup failed", exc_info=True)
        cached = None
    if cached is not None:
        return GeocodeResult(cached.status, cached.coordinates, cached.provider, from_cache=True)

    if budget is not None and not budget.try_acquire():
        return GeocodeResult(GEOCODE_DEFERRED, message="geocoding budget for this request is spent")

    provider = provider if provider is not None else get_default_provider()
    provider_name = getattr(provider, "name", type(provider).__name__)
    try:
        raw = provider.geocode(address)
    except (GeocodingUnavailableError, GeocodingRateLimitError) as error:
        return GeocodeResult(GEOCODE_DEFERRED, provider=provider_name, message=str(error))
    except Exception as error:  # noqa: BLE001 - includes timeouts
        logger.warning("Geocoding failed via %s: %s", provider_name, error)
        return GeocodeResult(GEOCODE_ERROR, provider=provider_name, message=str(error))

    if raw is None:
        _cache_set(cache, key, address, CacheEntry(GEOCODE_NOT_FOUND, None, provider_name))
        return GeocodeResult(GEOCODE_NOT_FOUND, provider=provider_name)

    coords = make_coordinates(getattr(raw, "latitude", None), getattr(raw, "longitude", None))
    if coords is None:
        logger.warning("Provider %s returned invalid coordinates: %r", provider_name, raw)
        return GeocodeResult(GEOCODE_ERROR, provider=provider_name, message="invalid coordinates")

    _cache_set(cache, key, address, CacheEntry(GEOCODE_OK, coords, provider_name))
    return GeocodeResult(GEOCODE_OK, coords, provider_name)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _cache_set(cache: CoordinateCache, key: str, address: str, entry: CacheEntry) -> None:
    try:
        cache.set(key, address, entry)
    except Exception:  # noqa: BLE001
        logger.warning("Geocode cache write failed", exc_info=True)


def _safe_commit(conn: Any) -> None:
    try:
        if conn is not None:
            conn.commit()
    except Exception:  # noqa: BLE001
        pass


def _safe_rollback(conn: Any) -> None:
    try:
        if conn is not None:
            conn.rollback()
    except Exception:  # noqa: BLE001
        pass


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default
