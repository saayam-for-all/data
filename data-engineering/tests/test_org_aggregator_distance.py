
import importlib.util
from pathlib import Path
import pandas as pd
import sys
from unittest.mock import patch


DISTANCE_FILE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "saayam-org-aggregator"
    / "distance.py"
)

spec = importlib.util.spec_from_file_location(
    "distance", DISTANCE_FILE
)
distance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(distance)


def test_same_location_returns_zero():
    result = distance.haversine_distance(
        30.0, -97.0, 30.0, -97.0
    )

    assert result == 0.0


def test_different_locations_return_positive_distance():
    result = distance.haversine_distance(
        30.0, -97.0, 31.0, -97.0
    )

    assert result > 0




def test_parse_request_coordinates():
    result = distance.parse_coordinates(
        "longitude:-121.9780,latitude:37.7799"
    )

    assert result == {
        "latitude": 37.7799,
        "longitude": -121.9780,
    }


def test_parse_coordinates_returns_none_for_missing_location():
    assert distance.parse_coordinates(None) is None
    assert distance.parse_coordinates("") is None


def test_parse_coordinates_returns_none_for_invalid_coordinates():
    assert distance.parse_coordinates(
        "longitude:200,latitude:37.7799"
    ) is None

def test_add_organization_distances_calculates_distance():
    organizations = pd.DataFrame([{
        "name": "Test Organization",
        "db_or_ai": "db",
        "latitude": 31.0,
        "longitude": -97.0,
    }])

    origin = {"latitude": 30.0, "longitude": -97.0}

    result = distance.add_organization_distances(
        organizations, origin
    )

    assert result.loc[0, "distance"] > 0
    assert result.loc[0, "distance_status"] == "ok"
    assert result.loc[0, "distance_unit"] == "miles"
    assert result.loc[0, "distance_method"] == "straight_line"


def test_add_organization_distances_keeps_missing_coordinates():
    organizations = pd.DataFrame([{
        "name": "Address Not Geocoded",
        "db_or_ai": "db",
        "latitude": None,
        "longitude": None,
    }])

    origin = {"latitude": 30.0, "longitude": -97.0}

    result = distance.add_organization_distances(
        organizations, origin
    )

    assert len(result) == 1
    assert pd.isna(result.loc[0, "distance"])
    assert result.loc[0, "distance_status"] == "deferred"


def test_add_organization_distances_without_origin():
    organizations = pd.DataFrame([{
        "name": "Unknown Origin",
        "db_or_ai": "db",
        "latitude": 31.0,
        "longitude": -97.0,
    }])

    result = distance.add_organization_distances(
        organizations, None
    )

    assert len(result) == 1
    assert pd.isna(result.loc[0, "distance"])
    assert result.loc[0, "distance_status"] == "unknown_location"

def test_geocode_address_uses_configured_lambda_and_caches_result(monkeypatch):
    import io
    import json
    import types

    calls = []

    class FakeLambdaClient:
        def invoke(self, **kwargs):
            calls.append(kwargs)
            return {
                "Payload": io.BytesIO(
                    json.dumps({
                        "latitude": 30.2672,
                        "longitude": -97.7431,
                    }).encode()
                )
            }

    fake_boto3 = types.SimpleNamespace(
        client=lambda service: FakeLambdaClient()
    )

    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setenv("GEOCODER_LAMBDA_NAME", "test-geocoder")
    monkeypatch.delenv("GEOCODE_CACHE_TABLE", raising=False)
    distance._GEOCODE_CACHE.clear()

    first = distance.geocode_address("Austin, TX")
    second = distance.geocode_address("Austin, TX")

    assert first == {"latitude": 30.2672, "longitude": -97.7431}
    assert second == first
    assert len(calls) == 1


def test_geocode_address_returns_none_when_geocoder_fails(monkeypatch):
    import types

    class FakeLambdaClient:
        def invoke(self, **kwargs):
            return {"FunctionError": "Unhandled"}

    fake_boto3 = types.SimpleNamespace(
        client=lambda service: FakeLambdaClient()
    )

    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setenv("GEOCODER_LAMBDA_NAME", "test-geocoder")
    monkeypatch.delenv("GEOCODE_CACHE_TABLE", raising=False)
    distance._GEOCODE_CACHE.clear()

    assert distance.geocode_address("Unknown address") is None


def test_add_organization_distances_geocodes_address(monkeypatch):
    organizations = pd.DataFrame([{
        "name": "Address Organization",
        "db_or_ai": "db",
        "street": "123 Main St",
        "location": "Austin",
        "state_id": "TX",
        "zip_code": "78701",
    }])

    monkeypatch.setattr(
        distance,
        "geocode_address",
        lambda address: {
            "latitude": 31.0,
            "longitude": -97.0,
        },
    )

    origin = {"latitude": 30.0, "longitude": -97.0}
    result = distance.add_organization_distances(organizations, origin)

    assert result.loc[0, "distance"] > 0
    assert result.loc[0, "distance_status"] == "ok"
