"""Tests for converting request-location WKB/EWKB point values."""

import csv
import math
import struct
from pathlib import Path

import pytest

from src.utils.request_location import convert_req_loc

FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "request_location_cases.csv"
)


def make_point(
    longitude,
    latitude,
    *,
    endian="<",
    has_srid=False,
    dimensions=2,
    iso_dimensions=False,
):
    """Build a WKB point for exercising dimensional and byte-order variants."""
    byte_order = 1 if endian == "<" else 0
    type_word = {
        (2, True): 1,
        (3, True): 1001,
        (4, True): 3001,
        (2, False): 1,
        (3, False): 0x80000001,
        (4, False): 0xC0000001,
    }[(dimensions, iso_dimensions)]
    if has_srid:
        type_word |= 0x20000000

    result = bytearray([byte_order])
    result.extend(struct.pack(f"{endian}I", type_word))
    if has_srid:
        result.extend(struct.pack(f"{endian}I", 4326))
    coordinates = [longitude, latitude] + [10.0] * (dimensions - 2)
    result.extend(struct.pack(f"{endian}{'d' * dimensions}", *coordinates))
    return bytes(result)


def test_mock_input_comparison():
    """Every documented mock location matches its expected POINT value."""
    with FIXTURE_PATH.open(newline="", encoding="utf-8") as source:
        cases = list(csv.DictReader(source))

    assert cases
    assert all(
        convert_req_loc(case["req_loc"]) == case["expected"]
        for case in cases
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (make_point(-74.006, 40.7128), "POINT(-74.006 40.7128)"),
        (
            make_point(-74.006, 40.7128, endian=">", has_srid=True),
            "POINT(-74.006 40.7128)",
        ),
        (
            make_point(12.5, -4.25, dimensions=3),
            "POINT(12.5 -4.25)",
        ),
        (
            make_point(12.5, -4.25, dimensions=4),
            "POINT(12.5 -4.25)",
        ),
        (
            make_point(12.5, -4.25, dimensions=3, iso_dimensions=True),
            "POINT(12.5 -4.25)",
        ),
        (
            make_point(12.5, -4.25, dimensions=4, iso_dimensions=True),
            "POINT(12.5 -4.25)",
        ),
    ],
)
def test_raw_wkb_variants(raw, expected):
    assert convert_req_loc(raw) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "\\x",
        "0x",
        "not-hex",
        "0101",
        "020100000000000000000000000000000000000000",
        "010200000000000000000000000000000000000000",
        make_point(math.nan, 40.0),
        make_point(10.0, math.inf),
        make_point(10.0, 20.0) + b"\x00",
        123,
    ],
)
def test_null_or_invalid_values_return_none(value):
    assert convert_req_loc(value) is None


def test_hex_prefixes_are_supported():
    raw_hex = make_point(-74.006, 40.7128).hex()

    assert convert_req_loc(f"\\x{raw_hex}") == "POINT(-74.006 40.7128)"
    assert convert_req_loc(f"0x{raw_hex}") == "POINT(-74.006 40.7128)"
