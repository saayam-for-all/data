import importlib.util
from pathlib import Path
import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "saayam-org-aggregator"
    / "distance_utils.py"
)


def load_distance_utils():
    spec = importlib.util.spec_from_file_location(
        "distance_utils", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
distance_utils = load_distance_utils()

def test_same_location_returns_zero_miles():
    distance_utils = load_distance_utils()

    result = distance_utils.calculate_distance(
        37.7799, -121.9780,
        37.7799, -121.9780
    )

    assert result == 0.0


def test_known_coordinates_return_expected_distance():
    distance_utils = load_distance_utils()

    result = distance_utils.calculate_distance(
        37.7799, -121.9780,
        37.4220, -122.0841
    )

    assert result == pytest.approx(25.4, abs=0.1)


def test_missing_coordinates_return_none():
    distance_utils = load_distance_utils()

    result = distance_utils.calculate_distance(
        None, None,
        37.4220, -122.0841
    )

    assert result is None

def test_build_distance_result_valid():
    result = distance_utils.build_distance_result(
        (37.7799, -121.9780),
        (37.4220, -122.0841),
    )

    assert result["distance"] is not None
    assert result["distance"] > 0
    assert result["distance_unit"] == "miles"
    assert result["distance_method"] == "straight_line"
    assert result["distance_status"] == "ok"


def test_build_distance_result_zero_distance():
    result = distance_utils.build_distance_result(
        (37.7799, -121.9780),
        (37.7799, -121.9780),
    )

    assert result["distance"] == 0
    assert result["distance_status"] == "ok"


def test_build_distance_result_missing_beneficiary():
    result = distance_utils.build_distance_result(
        None,
        (37.4220, -122.0841),
    )

    assert result["distance"] is None
    assert result["distance_status"] == "unknown_location"


def test_build_distance_result_missing_organization():
    result = distance_utils.build_distance_result(
        (37.7799, -121.9780),
        None,
    )

    assert result["distance"] is None
    assert result["distance_status"] == "unknown_location"