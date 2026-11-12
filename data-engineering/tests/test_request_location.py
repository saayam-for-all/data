import math
import struct

import pytest

from src.utils.request_location import convert_req_loc


EXAMPLE_EWKB = "0101000020E6100000AAF1D24D628052C05E4BC8073D5B4440"


def _point_wkb(
    longitude,
    latitude,
    *,
    endian="<",
    type_word=1,
    srid=None,
    extra_coordinates=(),
):
    byte_order = 1 if endian == "<" else 0
    parts = [struct.pack(f"{endian}BI", byte_order, type_word)]
    if srid is not None:
        parts.append(struct.pack(f"{endian}I", srid))
    parts.append(
        struct.pack(
            f"{endian}{2 + len(extra_coordinates)}d",
            longitude,
            latitude,
            *extra_coordinates,
        )
    )
    return b"".join(parts)


def test_issue_example_converts_to_readable_point():
    assert convert_req_loc(EXAMPLE_EWKB) == "POINT(-74.006 40.7128)"


@pytest.mark.parametrize("prefix", ["", r"\x", "0x"])
def test_hex_prefixes_are_supported(prefix):
    assert convert_req_loc(prefix + EXAMPLE_EWKB) == "POINT(-74.006 40.7128)"


@pytest.mark.parametrize(
    "factory",
    [
        lambda value: value,
        bytearray,
        memoryview,
    ],
)
def test_binary_database_driver_values_are_supported(factory):
    raw = bytes.fromhex(EXAMPLE_EWKB)
    assert convert_req_loc(factory(raw)) == "POINT(-74.006 40.7128)"


def test_plain_little_endian_wkb_is_supported():
    raw = _point_wkb(151.2093, -33.8688)
    assert convert_req_loc(raw.hex()) == "POINT(151.2093 -33.8688)"


def test_plain_big_endian_wkb_is_supported():
    raw = _point_wkb(-0.1276, 51.5072, endian=">")
    assert convert_req_loc(raw.hex()) == "POINT(-0.1276 51.5072)"


def test_ewkb_srid_metadata_is_skipped():
    raw = _point_wkb(
        2.3522,
        48.8566,
        type_word=0x20000001,
        srid=4326,
    )
    assert convert_req_loc(raw.hex()) == "POINT(2.3522 48.8566)"


def test_z_and_m_dimensions_keep_longitude_latitude_order():
    z_point = _point_wkb(
        -122.4194,
        37.7749,
        type_word=0x80000001,
        extra_coordinates=(16.25,),
    )
    m_point = _point_wkb(
        139.6917,
        35.6895,
        type_word=2001,
        extra_coordinates=(123.0,),
    )

    assert convert_req_loc(z_point.hex()) == "POINT(-122.4194 37.7749)"
    assert convert_req_loc(m_point.hex()) == "POINT(139.6917 35.6895)"


def test_existing_point_text_is_normalized_for_safe_reprocessing():
    assert convert_req_loc(" point ( -74.006   40.712800 ) ") == (
        "POINT(-74.006 40.7128)"
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "not hexadecimal",
        "123",
        b"",
        object(),
    ],
)
def test_null_blank_and_malformed_inputs_return_empty_string(value):
    assert convert_req_loc(value) == ""


def test_truncated_and_trailing_binary_data_are_rejected():
    assert convert_req_loc(EXAMPLE_EWKB[:-2]) == ""
    assert convert_req_loc(EXAMPLE_EWKB + "00") == ""


def test_non_point_geometry_is_rejected():
    raw = _point_wkb(-74.006, 40.7128, type_word=2)
    assert convert_req_loc(raw.hex()) == ""


@pytest.mark.parametrize(
    ("longitude", "latitude"),
    [
        (math.nan, 40.0),
        (-74.0, math.inf),
        (180.000001, 0.0),
        (0.0, -90.000001),
    ],
)
def test_non_finite_and_out_of_range_coordinates_are_rejected(
    longitude,
    latitude,
):
    raw = _point_wkb(longitude, latitude)
    assert convert_req_loc(raw.hex()) == ""


def test_coordinate_precision_is_preserved():
    longitude = -73.98565612345679
    latitude = 40.74843398765432
    raw = _point_wkb(longitude, latitude, type_word=0x20000001, srid=4326)

    assert convert_req_loc(raw.hex()) == (
        "POINT(-73.98565612345679 40.74843398765432)"
    )
