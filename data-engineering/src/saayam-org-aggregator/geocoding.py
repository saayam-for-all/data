"""Provider-agnostic geocoding with caching (issue #433).

The provider is chosen with the GEOCODER_PROVIDER environment variable.
Only "none" (default, returns "deferred") and "mock" (local testing) ship
here; a real provider is added by implementing GeocoderProvider and calling
register_provider().
"""

import logging
import os
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from threading import Lock
from typing import Callable, Optional, Protocol

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_NOT_FOUND = "not_found"
STATUS_DEFERRED = "deferred"
STATUS_ERROR = "error"
_VALID_STATUSES = {STATUS_OK, STATUS_NOT_FOUND, STATUS_DEFERRED, STATUS_ERROR}
# "error" and "deferred" are transient, so they are never cached.
_CACHEABLE_STATUSES = {STATUS_OK, STATUS_NOT_FOUND}

DEFAULT_PROVIDER = "none"
DEFAULT_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class GeocodeResult:
    """Outcome of one geocoding lookup."""

    status: str
    lat: Optional[float] = None
    lon: Optional[float] = None


class GeocoderProvider(Protocol):
    """Anything that turns an address into a GeocodeResult."""

    def geocode(self, address: str) -> GeocodeResult:
        ...


class DisabledGeocoder:
    """Default provider: no provider chosen yet, so every lookup is deferred."""

    def geocode(self, address: str) -> GeocodeResult:
        return GeocodeResult(STATUS_DEFERRED)


class MockGeocoder:
    """Local-testing provider backed by a small dict of known addresses."""

    KNOWN_ADDRESSES = {
        "2401 Crow Canyon Rd, San Ramon, California, 94583": (37.7799, -121.9780),
        "18000 Bollinger Canyon Rd, San Ramon, California, 94583": (37.7621, -121.9465),
        "39899 Balentine Dr, Newark, California, 94560, UNITED STATES": (37.5357, -122.0300),
        "1600 Amphitheatre Pkwy, Mountain View, CA 94043": (37.4220, -122.0841),
        "San Jose, CA": (37.3382, -121.8863),
    }

    def __init__(self, known: Optional[dict] = None) -> None:
        source = known if known is not None else self.KNOWN_ADDRESSES
        self._known = {normalize_address(k): v for k, v in source.items()}

    def geocode(self, address: str) -> GeocodeResult:
        coords = self._known.get(normalize_address(address))
        if coords is None:
            return GeocodeResult(STATUS_NOT_FOUND)
        return GeocodeResult(STATUS_OK, coords[0], coords[1])


class GeocodeCache(Protocol):
    """Cache interface; a DB-backed implementation can be plugged in later."""

    def get(self, key: str) -> Optional[GeocodeResult]:
        ...

    def set(self, key: str, result: GeocodeResult) -> None:
        ...


class InMemoryGeocodeCache:
    """Bounded LRU dict; lives at module level so it survives warm starts."""

    def __init__(self, max_entries: int = 5000) -> None:
        self._max_entries = max_entries
        self._data: "OrderedDict[str, GeocodeResult]" = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> Optional[GeocodeResult]:
        with self._lock:
            result = self._data.get(key)
            if result is not None:
                self._data.move_to_end(key)
            return result

    def set(self, key: str, result: GeocodeResult) -> None:
        with self._lock:
            self._data[key] = result
            self._data.move_to_end(key)
            while len(self._data) > self._max_entries:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_PROVIDER_FACTORIES: dict[str, Callable[[], GeocoderProvider]] = {
    "none": DisabledGeocoder,
    "mock": MockGeocoder,
}
_provider_instances: dict[str, GeocoderProvider] = {}
_cache: GeocodeCache = InMemoryGeocodeCache()
# Provider calls run here so they can be abandoned after the timeout.
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="geocoder")


def register_provider(name: str, factory: Callable[[], GeocoderProvider]) -> None:
    """Register (or replace) a provider selectable via GEOCODER_PROVIDER."""
    _PROVIDER_FACTORIES[name.lower()] = factory
    _provider_instances.pop(name.lower(), None)


def set_cache(cache: GeocodeCache) -> None:
    """Swap the cache implementation (e.g. for a persistent one)."""
    global _cache
    _cache = cache


def get_cache() -> GeocodeCache:
    """Return the active cache."""
    return _cache


def normalize_address(address: str) -> str:
    """Trim, lowercase and collapse whitespace so equal addresses share a key."""
    return re.sub(r"\s+", " ", str(address).strip().lower())


def _provider_name() -> str:
    return (os.environ.get("GEOCODER_PROVIDER") or DEFAULT_PROVIDER).strip().lower()


def _timeout_seconds() -> float:
    try:
        return float(os.environ.get("GEOCODER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _get_provider(name: str) -> Optional[GeocoderProvider]:
    if name not in _provider_instances:
        factory = _PROVIDER_FACTORIES.get(name)
        if factory is None:
            return None
        _provider_instances[name] = factory()
    return _provider_instances[name]


def _validated(result: object) -> GeocodeResult:
    """Coerce a provider's return value into a trustworthy GeocodeResult."""
    if not isinstance(result, GeocodeResult) or result.status not in _VALID_STATUSES:
        return GeocodeResult(STATUS_ERROR)
    if result.status != STATUS_OK:
        return GeocodeResult(result.status)
    try:
        lat, lon = float(result.lat), float(result.lon)
    except (TypeError, ValueError):
        return GeocodeResult(STATUS_ERROR)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return GeocodeResult(STATUS_ERROR)
    return GeocodeResult(STATUS_OK, lat, lon)


def geocode_address(address: Optional[str]) -> GeocodeResult:
    """Geocode an address via the configured provider, using the cache.

    Never raises: provider exceptions and timeouts become status "error".
    An empty address is "not_found".
    """
    if address is None or not str(address).strip():
        return GeocodeResult(STATUS_NOT_FOUND)

    name = _provider_name()
    key = f"{name}|{normalize_address(address)}"
    try:
        cached = _cache.get(key)
    except Exception:
        logger.exception("Geocode cache read failed")
        cached = None
    if cached is not None:
        return cached

    provider = _get_provider(name)
    if provider is None:
        logger.error("Unknown GEOCODER_PROVIDER %r", name)
        return GeocodeResult(STATUS_ERROR)

    future = _executor.submit(provider.geocode, str(address).strip())
    try:
        result = _validated(future.result(timeout=_timeout_seconds()))
    except FutureTimeoutError:
        future.cancel()
        logger.warning("Geocoder %r timed out", name)
        return GeocodeResult(STATUS_ERROR)
    except Exception:
        logger.exception("Geocoder %r failed", name)
        return GeocodeResult(STATUS_ERROR)

    if result.status in _CACHEABLE_STATUSES:
        try:
            _cache.set(key, result)
        except Exception:
            logger.exception("Geocode cache write failed")
    return result
