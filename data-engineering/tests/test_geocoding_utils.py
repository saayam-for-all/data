
import importlib.util
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "saayam-org-aggregator"
    / "geocoding_utils.py"
)

spec = importlib.util.spec_from_file_location(
    "geocoding_utils", MODULE_PATH
)
geocoding_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(geocoding_utils)


def test_build_organization_address():
    organization = {
        "street": "123 Main Street",
        "city_name": "New York",
        "state_code": "NY",
        "zip_code": "10001",
    }

    result = geocoding_utils.build_organization_address(
        organization
    )

    assert result == "123 Main Street, New York, NY, 10001"


def test_missing_organization_address():
    assert geocoding_utils.build_organization_address({}) is None


def test_geocode_with_provider():
    def mock_provider(address):
        assert address == "New York"
        return (40.7128, -74.0060)

    result = geocoding_utils.geocode_address(
        "New York", provider=mock_provider
    )

    assert result == (40.7128, -74.0060)


def test_geocode_without_provider():
    assert geocoding_utils.geocode_address("New York") is None

def test_cached_geocoding_returns_coordinates():
    calls = []

    def provider(address):
        calls.append(address)
        return (37.7799, -121.9780)

    result = geocoding_utils.geocode_address_cached(
        "123 Main Street, San Ramon", provider
    )

    assert result == (37.7799, -121.9780)
    assert len(calls) == 1


def test_cached_geocoding_reuses_result():
    calls = []

    def provider(address):
        calls.append(address)
        return (37.7799, -121.9780)

    first = geocoding_utils.geocode_address_cached(
        "123 Main Street, San Ramon", provider
    )

    second = geocoding_utils.geocode_address_cached(
        "123   Main Street, San Ramon", provider
    )

    assert first == second
    assert len(calls) == 1


def test_cached_geocoding_without_provider():
    result = geocoding_utils.geocode_address_cached(
        "123 Main Street", None
    )

    assert result is None


def test_cached_geocoding_missing_address():
    def provider(address):
        raise AssertionError("Provider should not be called")

    assert geocoding_utils.geocode_address_cached(
        None, provider
    ) is None

    assert geocoding_utils.geocode_address_cached(
        "   ", provider
    ) is None

def test_cached_geocoding_provider_failure():
    def failing_provider(address):
        raise TimeoutError("Geocoding service timed out")

    result = geocoding_utils.geocode_address_cached(
        "123 Main Street, Jersey City",
        failing_provider,
    )

    assert result is None

def test_build_organization_address_ignores_nan():
    organization = {
        "street": float("nan"),
        "city_name": "Jersey City",
        "state_code": float("nan"),
        "zip_code": "07306",
        "country": None,
    }

    result = geocoding_utils.build_organization_address(
        organization
    )

    assert result == "Jersey City, 07306"
    assert "nan" not in result.lower()

def test_genai_organization_location_fallback():

    organization = {
        "organization_name": "Example Organization",
        "location": "Mountain View, CA 94043",
    }

    address = geocoding_utils.build_organization_address(organization)

    assert address == "Mountain View, CA 94043"

def test_genai_location_fallback_when_city_is_nan():
    organization = {
        "name": "AI Organization",
        "city_name": float("nan"),
        "location": "Mountain View",
        "state_code": "CA",
    }

    result = geocoding_utils.build_organization_address(
        organization
    )

    assert result == "Mountain View, CA"