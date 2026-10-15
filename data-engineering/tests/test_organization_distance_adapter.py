import sys
from pathlib import Path
from unittest import result
from unittest.mock import Mock, patch

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1]
        / "src" / "saayam-org-aggregator"),
)

from organization_distance_adapter import (
    add_organization_distances,
    get_beneficiary_coordinates,
)


def test_beneficiary_location():
    cursor = Mock()

    request = {
        "req_id": "REQ001",
        "req_user_id": "USER001",
        "req_for_id": 0,
        "req_loc": "longitude:-121.9780,latitude:37.7799",
    }

    with patch(
        "organization_distance_adapter.get_request_details",
        return_value=request,
    ):
        result = get_beneficiary_coordinates(
            cursor, "test_schema", "REQ001"
        )

    assert result["coordinates"] == (37.7799, -121.9780)


def test_distance_enrichment():
    organizations = [
        {
            "name": "Test Organization",
            "city_name": "Mountain View",
            "state_code": "CA",
        }
    ]

    provider = lambda address: (37.4220, -122.0841)

    result = add_organization_distances(
        organizations,
        (37.7799, -121.9780),
        provider,
    )

    assert result[0]["distance"] == 25.4
    assert result[0]["distance_status"] == "ok"
    assert result[0]["distance_unit"] == "miles"
    assert "distance" not in organizations[0]


def test_missing_beneficiary_location():
    organizations = [{"name": "Test Organization"}]

    result = add_organization_distances(
        organizations,
        None,
    )

    assert result[0]["distance"] is None
    assert result[0]["distance_status"] == "unknown_location"


def test_geocoding_failure():
    organizations = [
        {"name": "Test Organization", "city_name": "Mountain View"}
    ]

    def failing_provider(address):
        raise RuntimeError("Geocoding unavailable")

    result = add_organization_distances(
        organizations,
        (37.7799, -121.9780),
        failing_provider,
    )

    assert result[0]["distance"] is None
    assert result[0]["distance_status"] != "ok"

def test_complete_request_distance_workflow():
    from organization_distance_adapter import enrich_request_organizations

    organizations = [
        {
            "name": "Test Organization",
            "city_name": "Mountain View",
            "state_code": "CA",
        }
    ]

    beneficiary_location = {
        "coordinates": (37.7799, -121.9780),
        "address": None,
    }

    provider = lambda address: (37.4220, -122.0841)

    with patch(
        "organization_distance_adapter.get_beneficiary_coordinates",
        return_value=beneficiary_location,
    ):
        result = enrich_request_organizations(
            cursor=None,
            schema="test_schema",
            request_id="REQ001",
            organizations=organizations,
            geocoding_provider=provider,
        )

    assert len(result) == 1
    assert result[0]["distance"] == 25.4
    assert result[0]["distance_unit"] == "miles"
    assert result[0]["distance_method"] == "straight_line"
    assert result[0]["distance_status"] == "ok"
    assert "distance" not in organizations[0]

def test_dataframe_distance_enrichment():
    import pandas as pd
    from organization_distance_adapter import enrich_organization_dataframe

    original = pd.DataFrame([
        {
            "name": "Test Organization",
            "city_name": "Mountain View",
            "state_code": "CA",
        }
    ])

    provider = lambda address: (37.4220, -122.0841)

    result = enrich_organization_dataframe(
        original,
        (37.7799, -121.9780),
        geocoding_provider=provider,
    )

    assert result.iloc[0]["distance"] == 25.4
    assert result.iloc[0]["distance_status"] == "ok"
    assert result.iloc[0]["distance_unit"] == "miles"
    assert "distance" not in original.columns
    assert result.iloc[0]["name"] == "Test Organization"

def test_merge_database_and_genai_organizations():
    import pandas as pd
    from organization_distance_adapter import merge_organizations_with_distances

    db = pd.DataFrame([{
        "org_name": "Database Organization",
        "city_name": "Mountain View",
        "state_code": "CA",
        "street": "1600 Amphitheatre Pkwy",
        "zip_code": "94043",
        "phone": "1234567890",
        "email": "db@example.com",
        "web_url": "https://example.com",
        "mission": "Shelter",
        "source": "database",
    }])

    ai = pd.DataFrame([{
        "organization_name": "AI Organization",
        "location": "Mountain View",
        "contact": "9876543210",
        "email": "ai@example.com",
        "web_url": "https://example.org",
        "mission": "Shelter",
        "source": "GenAI",
    }])

    provider = lambda address: (37.4220, -122.0841)

    result = merge_organizations_with_distances(
        db,
        ai,
        (37.7799, -121.9780),
        geocoding_provider=provider,
    )

    assert len(result) == 2
    assert result.iloc[0]["distance"] == 25.4
    assert result.iloc[0]["distance_status"] == "ok"
    assert result.iloc[0]["db_or_ai"] == "db"
    assert result.iloc[1]["db_or_ai"] == "ai"

    expected_columns = [
    "name", "location", "contact", "email",
    "web_url", "mission", "source", "db_or_ai",
    "distance", "distance_unit",
    "distance_method", "distance_status",
]

    assert list(result.columns[:12]) == expected_columns

# Verify that original organization details are preserved.
    assert result.iloc[0]["state_code"] == "CA"
    assert result.iloc[0]["street"] == "1600 Amphitheatre Pkwy"
    assert result.iloc[0]["zip_code"] == "94043"

    assert "distance" not in db.columns
    assert "distance" not in ai.columns

def test_merge_organizations_with_missing_addresses():
    import pandas as pd
    from organization_distance_adapter import merge_organizations_with_distances

    db = pd.DataFrame([{
        "org_name": "Organization Without Address",
        "street": None,
        "city_name": None,
        "state_code": None,
        "zip_code": None,
    }])

    ai = pd.DataFrame([{
        "organization_name": "AI Organization Without Location",
        "location": None,
    }])

    geocoding_calls = []

    def provider(address):
        geocoding_calls.append(address)
        return (37.4220, -122.0841)

    result = merge_organizations_with_distances(
        db,
        ai,
        (37.7799, -121.9780),
        geocoding_provider=provider,
    )

    assert len(result) == 2
    assert result["distance"].isna().all()
    assert (result["distance_status"] == "unknown_location").all()
    assert geocoding_calls == []

def test_final_aggregation_preserves_organizations_on_location_failure():
    import pandas as pd
    from organization_distance_adapter import (
        aggregate_request_organizations_with_distances,
    )

    db = pd.DataFrame([{
        "org_name": "Database Organization",
        "city_name": "New York",
    }])

    ai = pd.DataFrame([{
        "organization_name": "AI Organization",
        "location": "Boston",
    }])

    with patch(
        "organization_distance_adapter.get_beneficiary_coordinates",
        side_effect=RuntimeError("Database unavailable"),
    ):
        result = aggregate_request_organizations_with_distances(
            cursor=Mock(),
            schema="test_schema",
            request_id="REQ001",
            db_organizations=db,
            genai_organizations=ai,
        )

    assert len(result) == 2
    assert set(result["name"]) == {
        "Database Organization",
        "AI Organization",
    }
    assert result["distance"].isna().all()
    assert (result["distance_status"] == "unknown_location").all()