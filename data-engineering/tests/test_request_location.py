"""Local-only regression checks for issue #578; standard library only."""

import csv
import importlib.util
import json
import math
import random
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.request_location import (
    convert_request_locations,
    location_to_point,
)

FIXTURES = ROOT / "tests/fixtures/request_locations"
CASES = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))


def make_point(x, y, order="<", srid=4326, geometry_type=1):
    """Pack synthetic WKB independently from the production decoder."""
    header = struct.pack(order + "BI", order == "<", geometry_type)
    if srid is not None:
        header = struct.pack(order + "BI", order == "<", geometry_type | 0x20000000)
        header += struct.pack(order + "I", srid)
    return header + struct.pack(order + "dd", x, y)


class RequestLocationTests(unittest.TestCase):
    """Verify geometry, precision, safe failure, and the actual CSV export path."""

    def test_mock_expected_outputs(self):
        """All checked-in complete synthetic examples match literal expectations."""
        for case in CASES:
            with self.subTest(case=case["case"]):
                self.assertEqual(location_to_point(case["input"]), case["expected"])

    def test_database_binary_buffers(self):
        """Driver-returned binary values retain their coordinates in both orders."""
        for order in ("<", ">"):
            for srid in (None, 4326):
                for container in (bytes, bytearray, memoryview):
                    with self.subTest(order=order, srid=srid, container=container):
                        value = container(make_point(-74.006, 40.7128, order, srid))
                        self.assertEqual(location_to_point(value), "POINT(-74.006 40.7128)")

    def test_random_coordinates_round_trip_without_axis_swap_or_precision_loss(self):
        """Round-trip 1,000 arbitrary geographic points across both encodings."""
        rng = random.Random(578)
        for index in range(1000):
            x, y = rng.uniform(-180, 180), rng.uniform(-90, 90)
            result = location_to_point(make_point(
                x, y, "<" if index % 2 else ">", 4326 if index % 3 else None,
            ))
            self.assertIsNotNone(result)
            actual_x, actual_y = map(float, result[6:-1].split())
            self.assertEqual((actual_x, actual_y), (x, y))

    def test_rejects_non_point_and_extra_dimensions(self):
        """Do not treat a line, Z/M point, or unsupported SRID as an XY point."""
        for kind in (0, 2, 3, 4, 7, 1001, 2001, 3001, 0x80000001, 0x40000001):
            self.assertIsNone(location_to_point(make_point(1, 2, geometry_type=kind)))
        for srid in (0, 3857, 4269):
            self.assertIsNone(location_to_point(make_point(1, 2, srid=srid)))

    def test_corrupt_binary_never_interrupts_conversion(self):
        """Reject missing/extra bytes, invalid headers and arbitrary data safely."""
        point = make_point(10, 20)
        for size in range(len(point)):
            self.assertIsNone(location_to_point(point[:size]))
        self.assertIsNone(location_to_point(point + b"\x00"))
        self.assertIsNone(location_to_point(b"\x02" + point[1:]))
        rng = random.Random(1)
        for size in range(100):
            self.assertIsNone(location_to_point(rng.randbytes(size)))

    def test_invalid_types_and_text(self):
        """Unexpected cells and malformed text become null without throwing."""
        for value in (42, False, float("nan"), {}, [], object(), "0", "\\N",
                      "POINT EMPTY", "POINT(1,2)", "POINT Z(1 2 3)",
                      "POINT(NaN 1)", "POINT(1e999 1)", "a" * 10000):
            with self.subTest(value=repr(value)):
                self.assertIsNone(location_to_point(value))

    def test_non_finite_and_geographic_boundaries(self):
        """Coordinates are geographic, finite, and inclusive at the limits."""
        for x, y in ((math.nan, 1), (1, math.nan), (math.inf, 1), (1, -math.inf),
                     (180.00001, 0), (-180.00001, 0), (0, 90.00001), (0, -90.00001)):
            self.assertIsNone(location_to_point(make_point(x, y)))
        self.assertEqual(location_to_point(make_point(-180, 90)), "POINT(-180 90)")

    def test_existing_wkt_is_safe_to_reprocess(self):
        """Reprocessing valid exported values is idempotent, including signed zero."""
        for case in CASES:
            expected = case["expected"]
            if expected is not None:
                self.assertEqual(location_to_point(expected), expected)
        self.assertEqual(location_to_point(" point ( +1e-9 -0.0 ) "),
                         "POINT(0.000000001 -0)")
        tiny = float.fromhex("0x0.0000000000001p-1022")
        result = location_to_point(make_point(tiny, -tiny))
        self.assertEqual(location_to_point(result), result)
        self.assertEqual(tuple(map(float, result[6:-1].split())), (tiny, -tiny))

    def test_row_conversion_preserves_rows_columns_and_inputs(self):
        """Invalid locations do not lose requests or change unrelated values."""
        original = [{"req_id": i, "req_loc": c["input"], "req_desc": "café\n,\""}
                    for i, c in enumerate(CASES)]
        snapshot = [dict(row) for row in original]
        result = list(convert_request_locations(iter(original)))
        self.assertEqual(len(result), len(CASES))
        self.assertEqual(original, snapshot)
        for index, row in enumerate(result):
            self.assertEqual(row, {**original[index], "req_loc": CASES[index]["expected"]})
        self.assertEqual(list(convert_request_locations([{"req_id": 99}])), [{"req_id": 99}])

    def test_row_conversion_is_streaming(self):
        """Do not consume the entire result set before yielding the first request."""
        def rows():
            """Fail if the converter reads ahead."""
            yield {"req_id": 1, "req_loc": make_point(1, 2)}
            raise AssertionError("Read ahead")

        self.assertEqual(next(convert_request_locations(rows()))["req_loc"], "POINT(1 2)")

    def test_csv_command_preserves_all_records_and_other_fields(self):
        """Exercise the executable exporter and re-read its CSV, including escaping."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.csv"
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/convert_request_locations.py"),
                 str(FIXTURES / "requests.csv"), str(output)],
                capture_output=True, text=True, check=True,
            )
            with (FIXTURES / "requests.csv").open(encoding="utf-8", newline="") as source:
                before = list(csv.DictReader(source))
            with output.open(encoding="utf-8", newline="") as converted:
                after = list(csv.DictReader(converted))
            self.assertEqual(len(after), len(before))
            self.assertIn(f"Exported {len(before)} rows", result.stdout)
            for index, row in enumerate(after):
                self.assertEqual(row, {**before[index], "req_loc": CASES[index]["expected"] or ""})

    def test_csv_rejects_in_place_and_missing_column_before_writing(self):
        """Bad invocation cannot truncate the input or an existing destination."""
        spec = importlib.util.spec_from_file_location(
            "convert_locations_cli", ROOT / "scripts/convert_request_locations.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "source.csv", Path(directory) / "output.csv"
            source.write_text("req_id\n1\n", encoding="utf-8")
            output.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different"):
                module.convert_csv(source, source)
            self.assertEqual(source.read_text(), "req_id\n1\n")
            with self.assertRaisesRegex(ValueError, "req_loc"):
                module.convert_csv(source, output)
            self.assertEqual(output.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
