import json
import os

import pytest

from src.utils.request_location import hex_to_wkt

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "request_locations", "cases.json"
)

with open(FIXTURE) as f:
    CASES = json.load(f)


@pytest.mark.parametrize("case", CASES, ids=[c["case"] for c in CASES])
def test_fixture_case(case):
    """Actual output must equal the expected output in cases.json."""
    assert hex_to_wkt(case["input"]) == case["expected"]


def test_longitude_comes_before_latitude():
    result = hex_to_wkt("0101000020E6100000AAF1D24D628052C05E4BC8073D5B4440")
    assert result == "POINT(-74.006 40.7128)"


def test_non_string_input_does_not_raise():
    assert hex_to_wkt(12345) == ""
    assert hex_to_wkt(b"0101") == ""