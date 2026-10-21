import sys
from pathlib import Path

import pandas as pd

TEST_DIR = Path(__file__).resolve().parent
AGGREGATOR_DIR = TEST_DIR.parent
REPO_ROOT = AGGREGATOR_DIR.parents[2]

sys.path.insert(0, str(AGGREGATOR_DIR))

import json

import helpers
import lambda_function

MOCK_DATA_DIR = REPO_ROOT / "data-analytics" / "mock-data-generation"


def load_mock_csv(filename):
    path = MOCK_DATA_DIR / filename

    assert path.exists(), f"Expected mock file does not exist: {path}"

    return pd.read_csv(path)


def mock_geocoder(address):
    mock_locations = {
        "Beneficiary Address": (
            37.7799,
            -121.9780,
        ),
        "Organization Address": (
            37.4220,
            -122.0841,
        ),
        "Same Address": (
            37.7799,
            -121.9780,
        ),
        "GenAI Organization Address": (
            37.5000,
            -122.0000,
        ),
    }

    return mock_locations.get(address)


def setup_function():
    helpers._coordinate_cache.clear()


# ---------------------------------------------------------
# Mock data checks
# ---------------------------------------------------------


def test_mock_data_directory_exists():
    assert MOCK_DATA_DIR.exists()


def test_users_mock_can_be_loaded():
    users = load_mock_csv("users.csv")

    assert not users.empty

    required_columns = {
        "user_id",
        "addr_ln1",
        "city_name",
        "state_id",
        "country_id",
        "zip_code",
    }

    assert required_columns.issubset(users.columns)


def test_user_locations_mock_can_be_loaded():
    user_locations = load_mock_csv("user_locations.csv")

    assert not user_locations.empty

    print(
        "\nuser_locations columns:",
        user_locations.columns.tolist(),
    )


def test_organizations_mock_can_be_loaded():
    organizations = load_mock_csv("organizations.csv")

    assert not organizations.empty

    required_columns = {
        "org_id",
        "org_name",
        "street",
        "city_name",
        "state_id",
        "zip_code",
        "org_type",
        "org_size",
        "org_rating",
        "is_collaborator",
    }

    assert required_columns.issubset(organizations.columns)


def test_cities_mock_can_be_loaded():
    cities = load_mock_csv("cities.csv")

    assert not cities.empty


def test_states_mock_can_be_loaded():
    states = load_mock_csv("states.csv")

    assert not states.empty


def test_countries_mock_can_be_loaded():
    countries = load_mock_csv("countries.csv")

    assert not countries.empty


def test_real_mock_organization_address():
    organizations = load_mock_csv("organizations.csv")

    row = organizations.iloc[0]

    address = helpers._join_parts(
        [
            row.get("street"),
            row.get("city_name"),
            row.get("state_id"),
            row.get("zip_code"),
        ]
    )

    assert address is not None
    assert str(row["street"]) in address
    assert str(row["city_name"]) in address


# ---------------------------------------------------------
# Coordinate parsing
# ---------------------------------------------------------


def test_parse_request_coordinates():
    coordinates = helpers.parse_coordinates("longitude:-121.9780,latitude:37.7799")

    assert coordinates == (
        37.7799,
        -121.9780,
    )


def test_parse_reversed_coordinate_string():
    coordinates = helpers.parse_coordinates("latitude:37.7799,longitude:-121.9780")

    assert coordinates == (
        37.7799,
        -121.9780,
    )


def test_parse_simple_coordinate_string():
    coordinates = helpers.parse_coordinates("37.7799,-121.9780")

    assert coordinates == (
        37.7799,
        -121.9780,
    )


def test_parse_coordinate_dictionary():
    coordinates = helpers.parse_coordinates(
        {
            "latitude": 37.7799,
            "longitude": -121.9780,
        }
    )

    assert coordinates == (
        37.7799,
        -121.9780,
    )


def test_invalid_coordinates_return_none():
    assert helpers.parse_coordinates("not coordinates") is None


# ---------------------------------------------------------
# Distance calculation
# ---------------------------------------------------------


def test_straight_line_distance():
    distance = helpers.calculate_distance_miles(
        37.7799,
        -121.9780,
        37.4220,
        -122.0841,
    )

    assert round(distance, 1) == 25.4


def test_same_location_distance_is_zero():
    distance = helpers.calculate_distance_miles(
        37.7799,
        -121.9780,
        37.7799,
        -121.9780,
    )

    assert distance == 0


# ---------------------------------------------------------
# Beneficiary location priority
# ---------------------------------------------------------


def test_request_location_is_first_priority(
    monkeypatch,
):
    def fail_if_called(*args, **kwargs):
        raise AssertionError(
            "user_locations should not be checked when req_loc has coordinates"
        )

    monkeypatch.setattr(
        helpers,
        "get_user_location_coordinates",
        fail_if_called,
    )

    coordinates, status = helpers.get_beneficiary_coordinates(
        request_location=("longitude:-121.9780,latitude:37.7799"),
        beneficiary_id=123,
        geocoder=mock_geocoder,
    )

    assert coordinates == (
        37.7799,
        -121.9780,
    )

    assert status == "ok"


def test_user_location_is_second_priority(
    monkeypatch,
):
    monkeypatch.setattr(
        helpers,
        "get_user_location_coordinates",
        lambda beneficiary_id, geocoder=None: (
            (
                37.7799,
                -121.9780,
            ),
            "ok",
        ),
    )

    coordinates, status = helpers.get_beneficiary_coordinates(
        request_location=None,
        beneficiary_id=123,
        geocoder=mock_geocoder,
    )

    assert coordinates == (
        37.7799,
        -121.9780,
    )

    assert status == "ok"


def test_profile_address_is_third_priority(
    monkeypatch,
):
    monkeypatch.setattr(
        helpers,
        "get_user_location_coordinates",
        lambda beneficiary_id, geocoder=None: (
            None,
            "unknown_location",
        ),
    )

    monkeypatch.setattr(
        helpers,
        "get_beneficiary_location",
        lambda beneficiary_id: (
            "Beneficiary Address",
            "Test City",
        ),
    )

    coordinates, status = helpers.get_beneficiary_coordinates(
        request_location=None,
        beneficiary_id=123,
        geocoder=mock_geocoder,
    )

    assert coordinates == (
        37.7799,
        -121.9780,
    )

    assert status == "ok"


def test_missing_beneficiary_location(
    monkeypatch,
):
    monkeypatch.setattr(
        helpers,
        "get_user_location_coordinates",
        lambda beneficiary_id, geocoder=None: (
            None,
            "unknown_location",
        ),
    )

    monkeypatch.setattr(
        helpers,
        "get_beneficiary_location",
        lambda beneficiary_id: (
            None,
            None,
        ),
    )

    coordinates, status = helpers.get_beneficiary_coordinates(
        request_location=None,
        beneficiary_id=123,
        geocoder=mock_geocoder,
    )

    assert coordinates is None
    assert status == "unknown_location"


# ---------------------------------------------------------
# Organization distance
# ---------------------------------------------------------


def test_organization_distance():
    organizations = pd.DataFrame(
        [
            {
                "name": "Test Organization",
                "_distance_address": ("Organization Address"),
            }
        ]
    )

    result = helpers.add_distance_information(
        organizations,
        (
            37.7799,
            -121.9780,
        ),
        "ok",
        geocoder=mock_geocoder,
    )

    row = result.iloc[0]

    assert row["distance"] == 25.4
    assert row["distance_unit"] == "miles"

    assert row["distance_method"] == "straight_line"

    assert row["distance_status"] == "ok"


def test_organization_same_location():
    organizations = pd.DataFrame(
        [
            {
                "name": "Same Location Org",
                "_distance_address": ("Same Address"),
            }
        ]
    )

    result = helpers.add_distance_information(
        organizations,
        (
            37.7799,
            -121.9780,
        ),
        "ok",
        geocoder=mock_geocoder,
    )

    assert result.iloc[0]["distance"] == 0.0

    assert result.iloc[0]["distance_status"] == "ok"


def test_organization_missing_address():
    organizations = pd.DataFrame(
        [
            {
                "name": "Missing Address Org",
                "_distance_address": None,
            }
        ]
    )

    result = helpers.add_distance_information(
        organizations,
        (
            37.7799,
            -121.9780,
        ),
        "ok",
        geocoder=mock_geocoder,
    )

    assert pd.isna(result.iloc[0]["distance"])

    assert result.iloc[0]["distance_status"] == "unknown_location"


def test_online_organization():
    organizations = pd.DataFrame(
        [
            {
                "name": "Online Organization",
                "_distance_address": "Online",
            }
        ]
    )

    result = helpers.add_distance_information(
        organizations,
        (
            37.7799,
            -121.9780,
        ),
        "ok",
        geocoder=mock_geocoder,
    )

    assert pd.isna(result.iloc[0]["distance"])

    assert result.iloc[0]["distance_status"] == "online"


def test_unknown_beneficiary_location():
    organizations = pd.DataFrame(
        [
            {
                "name": "Organization",
                "_distance_address": ("Organization Address"),
            }
        ]
    )

    result = helpers.add_distance_information(
        organizations,
        None,
        "unknown_location",
        geocoder=mock_geocoder,
    )

    assert pd.isna(result.iloc[0]["distance"])

    assert result.iloc[0]["distance_status"] == "unknown_location"


# ---------------------------------------------------------
# Geocoding behavior
# ---------------------------------------------------------


def test_invalid_address_returns_not_found():
    organizations = pd.DataFrame(
        [
            {
                "name": "Invalid Address Org",
                "_distance_address": ("Invalid Address"),
            }
        ]
    )

    result = helpers.add_distance_information(
        organizations,
        (
            37.7799,
            -121.9780,
        ),
        "ok",
        geocoder=mock_geocoder,
    )

    assert pd.isna(result.iloc[0]["distance"])

    assert result.iloc[0]["distance_status"] == "not_found"


def test_geocoder_failure_returns_error():
    def failing_geocoder(address):
        raise RuntimeError("Mock geocoder failure")

    organizations = pd.DataFrame(
        [
            {
                "name": "Organization",
                "_distance_address": ("Some Address"),
            }
        ]
    )

    result = helpers.add_distance_information(
        organizations,
        (
            37.7799,
            -121.9780,
        ),
        "ok",
        geocoder=failing_geocoder,
    )

    assert pd.isna(result.iloc[0]["distance"])

    assert result.iloc[0]["distance_status"] == "error"


def test_geocoding_cache():
    calls = {
        "count": 0,
    }

    def counting_geocoder(address):
        calls["count"] += 1

        return (
            37.4220,
            -122.0841,
        )

    first, first_status = helpers.geocode_address(
        "Cached Address",
        geocoder=counting_geocoder,
    )

    second, second_status = helpers.geocode_address(
        "Cached Address",
        geocoder=counting_geocoder,
    )

    assert first == second

    assert first_status == "ok"
    assert second_status == "ok"

    assert calls["count"] == 1


def test_no_provider_returns_deferred():
    coordinates, status = helpers.geocode_address("123 Example Street")

    assert coordinates is None
    assert status == "deferred"


# ---------------------------------------------------------
# GenAI organization handling
# ---------------------------------------------------------


def test_genai_organization_location():
    db_organizations = pd.DataFrame()

    ai_organizations = pd.DataFrame(
        [
            {
                "organization_name": ("GenAI Organization"),
                "location": ("GenAI Organization Address"),
                "contact": "1234567890",
                "email": "test@example.com",
                "web_url": ("https://example.com"),
                "mission": "Education",
                "source": "ai",
                "is_collaborator": False,
                "_distance_address": ("GenAI Organization Address"),
            }
        ]
    )

    combined = helpers.merge_organizations(
        db_organizations,
        ai_organizations,
    )

    result = helpers.add_distance_information(
        combined,
        (
            37.7799,
            -121.9780,
        ),
        "ok",
        geocoder=mock_geocoder,
    )

    assert len(result) == 1

    assert result.iloc[0]["distance"] is not None

    assert result.iloc[0]["distance_status"] == "ok"


def test_genai_missing_location():
    db_organizations = pd.DataFrame()

    ai_organizations = pd.DataFrame(
        [
            {
                "organization_name": ("GenAI Organization"),
                "location": None,
                "source": "ai",
                "is_collaborator": False,
                "_distance_address": None,
            }
        ]
    )

    combined = helpers.merge_organizations(
        db_organizations,
        ai_organizations,
    )

    result = helpers.add_distance_information(
        combined,
        (
            37.7799,
            -121.9780,
        ),
        "ok",
        geocoder=mock_geocoder,
    )

    assert pd.isna(result.iloc[0]["distance"])

    assert result.iloc[0]["distance_status"] == "unknown_location"


# ---------------------------------------------------------
# Distance sorting
# ---------------------------------------------------------


def test_distance_sorting():
    organizations = pd.DataFrame(
        [
            {
                "name": "Unknown",
                "distance": None,
            },
            {
                "name": "Far",
                "distance": 20.0,
            },
            {
                "name": "Same",
                "distance": 0.0,
            },
            {
                "name": "Near",
                "distance": 5.0,
            },
        ]
    )

    result = helpers.sort_organizations_by_distance(organizations)

    assert result.iloc[0]["name"] == "Same"
    assert result.iloc[1]["name"] == "Near"
    assert result.iloc[2]["name"] == "Far"
    assert result.iloc[3]["name"] == "Unknown"


def test_lambda_response_includes_distance_fields(
    monkeypatch,
):
    monkeypatch.setattr(
        lambda_function,
        "get_req_info",
        lambda request_id, beneficiary_id: {
            "subject": "Food assistance",
            "description": "Need food support",
            "category": "Food",
            "req_loc": ("longitude:-121.9780,latitude:37.7799"),
        },
    )

    monkeypatch.setattr(
        lambda_function,
        "get_beneficiary_location",
        lambda beneficiary_id: (
            "Beneficiary Address",
            "Test City",
        ),
    )

    monkeypatch.setattr(
        lambda_function,
        "get_beneficiary_coordinates",
        lambda request_location, beneficiary_id: (
            (37.7799, -121.9780),
            "ok",
        ),
    )

    monkeypatch.setattr(
        lambda_function,
        "get_orgs_from_db",
        lambda location, category: pd.DataFrame(
            [
                {
                    "org_name": "Test Organization",
                    "location": "Organization Address",
                    "source": "db",
                    "_distance_address": "37.4220,-122.0841",
                }
            ]
        ),
    )

    monkeypatch.setattr(
        lambda_function,
        "get_ai_orgs",
        lambda *args, **kwargs: pd.DataFrame(),
    )

    event = {
        "body": json.dumps(
            {
                "request_id": "REQ-1",
                "beneficiary_id": "USER-1",
            }
        )
    }

    response = lambda_function.lambda_handler(
        event,
        None,
    )

    assert response["statusCode"] == 200

    body = json.loads(response["body"])

    assert len(body) == 1

    organization = body[0]

    assert "distance" in organization
    assert "distance_unit" in organization
    assert "distance_method" in organization
    assert "distance_status" in organization

    assert organization["distance"] == 25.4
    assert organization["distance_unit"] == "miles"
    assert organization["distance_method"] == "straight_line"
    assert organization["distance_status"] == "ok"
