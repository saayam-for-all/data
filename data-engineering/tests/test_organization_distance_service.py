import importlib.util
import sys
from pathlib import Path


SRC_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "saayam-org-aggregator"
)

sys.path.insert(0, str(SRC_DIR))

spec = importlib.util.spec_from_file_location(
    "organization_distance_service",
    SRC_DIR / "organization_distance_service.py",
)

service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


def test_valid_distance():
    organizations = [
        {
            "name": "Organization A",
            "street": "123 Main St",
            "city_name": "Jersey City",
        }
    ]

    original = [organization.copy() for organization in organizations]

    def fake_geocoder(address):
        return (40.7300, -74.0600)

    results = service.enrich_organizations_with_distance(
        organizations,
        beneficiary_coordinates=(40.7200, -74.0500),
        geocoding_provider=fake_geocoder,
    )

    assert len(results) == 1
    assert isinstance(results[0]["distance"], (int, float))
    assert results[0]["distance"] > 0
    assert results[0]["distance_unit"] == "miles"
    assert results[0]["distance_status"] == "ok"

    # Original records must remain unchanged.
    assert organizations == original


def test_missing_organization_coordinates():
    organizations = [
        {
            "name": "Organization B",
            "city_name": "New York",
        }
    ]

    results = service.enrich_organizations_with_distance(
        organizations,
        beneficiary_coordinates=(40.7200, -74.0500),
    )

    assert results[0]["distance"] is None
    assert results[0]["distance_status"] == "unknown_location"


def test_multiple_organizations():
    organizations = [
        {"name": "Organization A", "city_name": "Jersey City"},
        {"name": "Organization B", "city_name": "New York"},
    ]

    def fake_geocoder(address):
        if "Jersey City" in address:
            return (40.7300, -74.0600)
        return (40.7128, -74.0060)

    results = service.enrich_organizations_with_distance(
        organizations,
        beneficiary_coordinates=(40.7200, -74.0500),
        geocoding_provider=fake_geocoder,
    )

    assert len(results) == 2
    assert all(result["distance"] is not None for result in results)
    assert all(result["distance_status"] == "ok" for result in results)

def test_sort_organizations_by_distance():
    organizations = [
        {"name": "Unknown", "distance": None},
        {"name": "Far", "distance": 25.5},
        {"name": "Same Location", "distance": 0},
        {"name": "Near", "distance": 4.8},
    ]

    result = service.sort_organizations_by_distance(
    organizations
)
    

    assert [org["name"] for org in result] == [
        "Same Location",
        "Near",
        "Far",
        "Unknown",
    ]

    # Original list must remain unchanged.
    assert organizations[0]["name"] == "Unknown"