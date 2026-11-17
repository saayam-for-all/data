
"""Local unit tests for request location conversion (Issue #578)."""

import math
import struct
import unittest

from location_converter import convert_req_loc


def make_point(longitude, latitude, endian="<", srid=True):
    """Generate a synthetic WKB/EWKB point."""
    byte_order = 1 if endian == "<" else 0
    geometry_type = 0x20000001 if srid else 1

    raw = struct.pack("B", byte_order)
    raw += struct.pack(endian + "I", geometry_type)

    if srid:
        raw += struct.pack(endian + "I", 4326)

    raw += struct.pack(endian + "dd", longitude, latitude)
    return raw.hex().upper()


class TestLocationConverter(unittest.TestCase):

    def test_little_endian_ewkb(self):
        value = make_point(-74.006, 40.7128)
        self.assertEqual(
            convert_req_loc(value),
            "POINT(-74.006 40.7128)",
        )

    def test_big_endian_ewkb(self):
        value = make_point(-74.006, 40.7128, endian=">")
        self.assertEqual(
            convert_req_loc(value),
            "POINT(-74.006 40.7128)",
        )

    def test_standard_wkb(self):
        value = make_point(-118.2437, 34.0522, srid=False)
        self.assertEqual(
            convert_req_loc(value),
            "POINT(-118.2437 34.0522)",
        )

    def test_high_precision(self):
        value = make_point(-73.98565612345678, 40.74843398765432)
        self.assertEqual(
            convert_req_loc(value),
            "POINT(-73.98565612345678 40.74843398765432)",
        )

    def test_null(self):
        self.assertIsNone(convert_req_loc(None))

    def test_empty(self):
        self.assertIsNone(convert_req_loc(""))

    def test_invalid_hex(self):
        self.assertIsNone(convert_req_loc("INVALID_HEX"))

    def test_truncated_geometry(self):
        self.assertIsNone(convert_req_loc("0101000020E61000"))

    def test_non_finite_coordinate(self):
        value = make_point(math.inf, 40.7128)
        self.assertIsNone(convert_req_loc(value))

    def test_hex_prefix(self):
        value = make_point(-74.006, 40.7128)
        self.assertEqual(
            convert_req_loc("0x" + value),
            "POINT(-74.006 40.7128)",
        )

    def test_non_point_geometry(self):
        # WKB LineString geometry type (2), not Point (1).
        raw = struct.pack("<BI", 1, 2)
        self.assertIsNone(convert_req_loc(raw.hex()))

    def test_invalid_byte_order(self):
        self.assertIsNone(convert_req_loc("02" + "00" * 20))


if __name__ == "__main__":
    unittest.main()
