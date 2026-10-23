from functools import lru_cache
import math
def build_organization_address(organization):
    """
    Build an organization address using available database
    or GenAI location fields.
    """
    if not isinstance(organization, dict):
        return None

    def clean(value):
        if value is None:
            return None

        if isinstance(value, float) and not math.isfinite(value):
            return None

        value = str(value).strip()

        if not value or value.lower() in ("nan", "none", "null"):
            return None

        return value

    city = clean((
    organization.get("location")
    if str(organization.get("city_name")).strip().lower()
    in ("nan", "none", "null", "")
    else organization.get("city_name")
),
    )

    parts = [
        clean(organization.get("street")),
        city,
        clean(organization.get("state_code")),
        clean(organization.get("zip_code")),
        clean(organization.get("country")),
    ]

    cleaned = [part for part in parts if part]

    return ", ".join(cleaned) if cleaned else None

def geocode_address(address, provider=None):
    """
    Resolve an address to (latitude, longitude).
    """
    if not address or provider is None:
        return None

    return provider(address)


@lru_cache(maxsize=1024)
def _cached_geocode(address, provider):
    return provider(address)


def geocode_address_cached(address, provider=None):
    """
    Geocode an address with an in-memory cache.
    Provider failures return None without crashing.
    """
    if not address or provider is None:
        return None

    normalized_address = " ".join(str(address).strip().split())

    if not normalized_address:
        return None

    try:
        return _cached_geocode(normalized_address, provider)
    except Exception:
        return None