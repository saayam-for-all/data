
import struct
import unittest

from location_converter import convert_location


class TestLocationConverter(unittest.TestCase):

    def test_standard_wkb(self):
        data = struct.pack("<BIdd", 1, 1, -73.5, 40.25).hex()
        self.assertEqual(convert_location(data), "POINT(-73.5 40.25)")

    def test_ewkb_with_srid(self):
        data = struct.pack("<BIIdd", 1, 0x20000001, 4326, -74.0, 40.5).hex()
        self.assertEqual(convert_location(data), "POINT(-74 40.5)")

    def test_big_endian(self):
        data = struct.pack(">BIdd", 0, 1, -73.5, 40.25).hex()
        self.assertEqual(convert_location(data), "POINT(-73.5 40.25)")

    def test_null_and_invalid(self):
        for value in (None, "", "INVALID", "1234"):
            with self.subTest(value=value):
                self.assertEqual(convert_location(value), "")

    def test_invalid_coordinates(self):
        data = struct.pack("<BIdd", 1, 1, 200.0, 95.0).hex()
        self.assertEqual(convert_location(data), "")

    def test_non_point_geometry(self):
        data = struct.pack("<BI", 1, 2).hex()
        self.assertEqual(convert_location(data), "")


if __name__ == "__main__":
    unittest.main()
