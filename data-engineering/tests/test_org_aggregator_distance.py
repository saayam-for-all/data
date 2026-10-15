"""Tests for beneficiary-based distance enrichment in the org aggregator."""

import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest


AGGREGATOR_DIR = (
    Path(__file__).parents[1] / "src" / "saayam-org-aggregator"
)
sys.path.insert(0, str(AGGREGATOR_DIR))


def _install_aws_stubs():
    boto3 = types.ModuleType("boto3")

    class Boto3Error(Exception):
        pass

    boto3.exceptions = types.SimpleNamespace(Boto3Error=Boto3Error)
    boto3.client = lambda *_args, **_kwargs: types.SimpleNamespace(invoke=None)
    sys.modules["boto3"] = boto3

    powertools = types.ModuleType("aws_lambda_powertools")
    utilities = types.ModuleType("aws_lambda_powertools.utilities")
    parameters = types.ModuleType("aws_lambda_powertools.utilities.parameters")
    parameters.get_parameter = lambda *_args, **_kwargs: json.dumps({
        "DATABASE NAME": "test_schema",
        "HOST": "localhost",
        "USERNAME": "test",
        "PASSWORD": "test",
        "PORT": 5432,
    })
    utilities.parameters = parameters
    powertools.utilities = utilities
    sys.modules["aws_lambda_powertools"] = powertools
    sys.modules["aws_lambda_powertools.utilities"] = utilities
    sys.modules["aws_lambda_powertools.utilities.parameters"] = parameters

    pg8000 = types.ModuleType("pg8000")

    class DatabaseError(Exception):
        pass

    pg8000.DatabaseError = DatabaseError
    pg8000.connect = lambda *_args, **_kwargs: object()
    sys.modules["pg8000"] = pg8000


_install_aws_stubs()
distance = importlib.import_module("distance")
helpers = importlib.import_module("helpers")
lambda_function = importlib.import_module("lambda_function")


def setup_function():
    with distance._GEOCODE_CACHE_LOCK:
        distance._GEOCODE_CACHE.clear()
    distance.configure_geocoding_provider(None)


def test_parse_coordinates_supports_postgis_and_named_values():
    assert distance.parse_coordinates("SRID=4326;POINT(-121.978 37.7799)") == (
        37.7799,
        -121.978,
    )
    assert distance.parse_coordinates("longitude:-121.978,latitude:37.7799") == (
        37.7799,
        -121.978,
    )
    assert distance.parse_coordinates({"lat": 0, "lng": 0}) == (0.0, 0.0)
    assert distance.parse_coordinates("Suffolk, VA") is None


def test_haversine_distance_matches_issue_example():
    miles = distance.haversine_miles(
        (37.7799, -121.9780), (37.4220, -122.0841)
    )
    assert miles == pytest.approx(25.5, abs=0.2)


def test_geocoding_is_deferred_without_provider_and_caches_success():
    assert distance.geocode_address("10 Main St, Richmond, VA") == (
        None,
        "deferred",
    )
    calls = []

    def provider(address):
        calls.append(address)
        return 37.5, -77.4

    distance.configure_geocoding_provider(provider)
    assert distance.geocode_address("10 Main St, Richmond, VA") == (
        (37.5, -77.4),
        "ok",
    )
    assert distance.geocode_address(" 10 MAIN ST, RICHMOND, VA ") == (
        (37.5, -77.4),
        "ok",
    )
    assert calls == ["10 Main St, Richmond, VA"]


def test_geocoding_reports_provider_failure_and_unmatched_address():
    assert distance.geocode_address(
        "10 Main St, Richmond, VA", provider=lambda _address: None
    ) == (None, "not_found")
    assert distance.geocode_address(
        "20 Main St, Richmond, VA",
        provider=lambda _address: (_ for _ in ()).throw(RuntimeError("offline")),
    ) == (None, "error")
    assert distance.geocode_address(
        "30 Main St, Richmond, VA",
        provider=lambda _address: (_ for _ in ()).throw(TimeoutError()),
    ) == (None, "deferred")


def test_missing_organization_address_returns_unknown_distance():
    result = distance.add_distances(
        pd.DataFrame([{"name": "No address"}]),
        {"coordinates": (37.5, -77.4), "status": "ok"},
    )

    assert pd.isna(result.iloc[0]["distance"])
    assert result.iloc[0]["distance_status"] == "unknown_location"


def test_distance_enrichment_keeps_records_and_valid_zero():
    organizations = pd.DataFrame([
        {
            "name": "Nearby",
            "latitude": 37.5,
            "longitude": -77.4,
            "rating": 4.8,
            "is_collaborator": True,
        },
        {"name": "Address only", "street": "20 Main St", "city_name": "Richmond"},
    ])

    result = distance.add_distances(
        organizations,
        {"coordinates": (37.5, -77.4), "status": "ok"},
    )

    assert len(result) == 2
    assert result.iloc[0]["distance"] == 0.0
    assert result.iloc[0]["distance_status"] == "ok"
    assert result.iloc[0]["rating"] == 4.8
    assert result.iloc[0]["is_collaborator"]
    assert pd.isna(result.iloc[1]["distance"])
    assert result.iloc[1]["distance_status"] == "deferred"


def test_merge_preserves_display_fields_and_private_address_inputs():
    db = pd.DataFrame([{
        "org_id": "ORG-1",
        "org_name": "Food Bank",
        "org_type": "nonprofit",
        "is_collaborator": True,
        "org_size": "large",
        "org_rating": 4.8,
        "city_name": "Richmond",
        "street": "10 Main St",
    }])
    merged = helpers.merge_organizations(db, pd.DataFrame())

    assert merged.iloc[0]["name"] == "Food Bank"
    assert merged.iloc[0]["organization_type"] == "nonprofit"
    assert merged.iloc[0]["collaborator"]
    assert merged.iloc[0]["size"] == "large"
    assert merged.iloc[0]["rating"] == 4.8
    assert merged.iloc[0]["location"] == "Richmond"
    assert merged.iloc[0]["street"] == "10 Main St"
    assert "org_id" not in merged.columns


def test_request_context_is_scoped_to_request_and_beneficiary():
    expected = {
        "req_id": "REQ-1",
        "beneficiary_id": "USER-1",
        "category": "Food",
    }
    with patch.object(helpers, "_location_expression", return_value="r.req_loc AS req_loc"), \
         patch.object(helpers, "_first_row", return_value=expected) as query:
        result = helpers.get_request_context("REQ-1", "USER-1")

    sql, params = query.call_args.args
    assert result == expected
    assert "r.req_id = %s AND r.beneficiary_id = %s" in sql
    assert params == ("REQ-1", "USER-1")


def test_database_organization_lookup_uses_category_tables_and_parameters():
    columns = {
        "organizations": {"org_id", "org_name", "cat_id", "city_name", "street"},
        "org_skills": {"org_id", "cat_id"},
        "help_categories": {"cat_id", "cat_name"},
        "cities": set(),
        "states": set(),
        "countries": set(),
    }
    organizations = pd.DataFrame([{
        "org_id": "ORG-1",
        "org_name": "Food Bank",
        "street": "10 Main St",
        "city_name": "Richmond",
    }])
    with patch.object(helpers, "_table_columns", side_effect=lambda name: columns[name]), \
         patch.object(helpers.pd, "read_sql", return_value=organizations) as query:
        result = helpers.get_orgs_from_db("Richmond", "Food")

    sql, _connection = query.call_args.args[:2]
    assert "JOIN test_schema.org_skills" in sql
    assert "JOIN test_schema.help_categories" in sql
    assert "hc.cat_name = %s" in sql
    assert query.call_args.kwargs["params"] == ("Food", "Richmond")
    assert result.iloc[0]["street"] == "10 Main St"


def test_request_coordinates_take_precedence_over_current_location():
    with patch.object(helpers, "_get_beneficiary_profile", return_value={
        "city_name": "Richmond",
        "addr_ln1": "10 Main St",
    }), patch.object(helpers, "_table_columns") as columns:
        result = helpers.get_beneficiary_location(
            "USER-1", "longitude:-77.4,latitude:37.5"
        )

    assert result["coordinates"] == (37.5, -77.4)
    assert result["city"] == "Richmond"
    columns.assert_not_called()


def test_user_location_is_used_when_request_has_no_coordinates():
    with patch.object(helpers, "_get_beneficiary_profile", return_value={
        "city_name": "Richmond",
    }), patch.object(helpers, "_table_columns", return_value={
        "user_id", "curr_loc", "updated_at"
    }), patch.object(helpers, "_location_expression", return_value="ul.curr_loc AS curr_loc"), \
         patch.object(helpers, "_first_row", return_value={
             "curr_loc": "SRID=4326;POINT(-77.4 37.5)"
         }) as query:
        result = helpers.get_beneficiary_location("USER-1", "Richmond, VA")

    assert result["coordinates"] == (37.5, -77.4)
    assert result["status"] == "ok"
    assert query.call_args.args[1] == ("USER-1",)


def test_profile_address_fallback_does_not_invent_coordinates():
    with patch.object(helpers, "_get_beneficiary_profile", return_value={
        "addr_ln1": "10 Main St",
        "city_name": "Richmond",
        "state_name": "Virginia",
    }), patch.object(helpers, "_table_columns", return_value=set()), \
         patch.object(helpers, "geocode_address", return_value=(None, "deferred")):
        result = helpers.get_beneficiary_location("USER-1")

    assert result["coordinates"] is None
    assert result["status"] == "deferred"
    assert result["address"] == "10 Main St, Richmond, Virginia"


def test_lambda_returns_database_organizations_when_genai_fails():
    db_organizations = pd.DataFrame([
        {
            "org_name": "Nearby Org",
            "city_name": "Richmond",
            "latitude": 37.5,
            "longitude": -77.4,
            "rating": 4.8,
        }
    ])
    request = {
        "req_id": "REQ-1",
        "beneficiary_id": "USER-1",
        "req_subj": "Food",
        "req_desc": "Need groceries",
        "category": "Food",
        "req_loc": None,
    }
    with patch.object(lambda_function, "get_request_context", return_value=request), \
         patch.object(lambda_function, "get_beneficiary_location", return_value={
             "coordinates": (37.5, -77.4),
             "status": "ok",
             "address": "Richmond, Virginia",
             "city": "Richmond",
         }), patch.object(lambda_function, "get_orgs_from_db", return_value=db_organizations), \
         patch.object(lambda_function, "get_ai_orgs", side_effect=RuntimeError("offline")):
        response = lambda_function.lambda_handler({
            "request_id": "REQ-1",
            "beneficiary_id": "USER-1",
        }, None)

    records = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert records[0]["name"] == "Nearby Org"
    assert records[0]["distance"] == 0.0
    assert records[0]["distance_status"] == "ok"
    assert records[0]["rating"] == 4.8


def test_lambda_handles_genai_organizations_with_and_without_locations():
    ai_organizations = pd.DataFrame([
        {
            "organization_name": "Located GenAI Org",
            "latitude": 37.5,
            "longitude": -77.4,
        },
        {"organization_name": "Unlocated GenAI Org"},
    ])
    request = {
        "req_id": "REQ-1",
        "beneficiary_id": "USER-1",
        "req_subj": "Food",
        "req_desc": "Need groceries",
        "category": "Food",
        "req_loc": None,
    }
    with patch.object(lambda_function, "get_request_context", return_value=request), \
         patch.object(lambda_function, "get_beneficiary_location", return_value={
             "coordinates": (37.5, -77.4),
             "status": "ok",
             "address": "Richmond, Virginia",
             "city": "Richmond",
         }), patch.object(lambda_function, "get_orgs_from_db", return_value=pd.DataFrame()), \
         patch.object(lambda_function, "get_ai_orgs", return_value=ai_organizations):
        response = lambda_function.lambda_handler({
            "request_id": "REQ-1",
            "beneficiary_id": "USER-1",
        }, None)

    records = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert records[0]["name"] == "Located GenAI Org"
    assert records[0]["db_or_ai"] == "ai"
    assert records[0]["distance"] == 0.0
    assert records[0]["distance_status"] == "ok"
    assert records[1]["name"] == "Unlocated GenAI Org"
    assert records[1]["distance"] is None
    assert records[1]["distance_status"] == "unknown_location"


def test_lambda_keeps_existing_location_category_search():
    organizations = pd.DataFrame([{"name": "Local Org", "location": "Richmond"}])
    with patch.object(lambda_function, "get_orgs_from_db", return_value=organizations), \
         patch.object(lambda_function, "get_ai_orgs", return_value=pd.DataFrame()):
        response = lambda_function.lambda_handler({
            "location": "Richmond",
            "category": "Food",
        }, None)

    records = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert records[0]["name"] == "Local Org"
    assert records[0]["distance"] is None
    assert records[0]["distance_status"] == "unknown_location"
