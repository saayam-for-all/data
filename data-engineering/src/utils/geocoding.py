"""Provider-neutral geocoding cache."""
from importlib import import_module
import os
import logging
from threading import Lock
from typing import Any, Callable, Dict, Optional, Tuple

from utils.geo import parse_coordinates

Coordinates = Tuple[float, float]
GeocodingProvider = Callable[[str], Any]

_cache: Dict[str, Coordinates] = {}
_cache_lock = Lock()


def geocode_cached(
    address: Optional[str],
    provider: Optional[GeocodingProvider] = None,
) -> Optional[Coordinates]:
    """Return cached coordinates or geocode an address with a provider."""
    if not address or not address.strip():
        return None

    cache_key = " ".join(address.lower().split())

    with _cache_lock:
        if cache_key in _cache:
            return _cache[cache_key]

    # No provider is configured yet, so don't make an external request.
    if provider is None:
        return None

    try:
        result = provider(address)
        coordinates = parse_coordinates(result)
    except Exception:
        logging.getLogger(__name__).warning(
            "Geocoding provider failed; distance will be unavailable",
            exc_info=True,
        )
        return None

    # Also accept a provider result shaped as (latitude, longitude).
    if coordinates is None and isinstance(result, (tuple, list)) and len(result) == 2:
        coordinates = parse_coordinates(
            {"latitude": result[0], "longitude": result[1]}
        )

    if coordinates is not None:
        with _cache_lock:
            _cache[cache_key] = coordinates

    return coordinates

def load_geocoding_provider():
    """Load a callable geocoder from GEOCODING_ADAPTER, if configured."""
    adapter_path = os.getenv("GEOCODING_ADAPTER", "").strip()

    if not adapter_path:
        return None

    if ":" not in adapter_path:
        raise ValueError(
            "GEOCODING_ADAPTER must use the format "
            "'module_name:factory_name'"
        )

    module_name, factory_name = adapter_path.split(":", 1)
    factory = getattr(import_module(module_name), factory_name)
    provider = factory()

    if not callable(provider):
        raise TypeError(
            "The configured geocoding factory must return a callable "
            "that accepts an address and returns coordinates"
        )

    return provider