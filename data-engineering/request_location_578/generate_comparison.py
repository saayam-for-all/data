
import csv
import struct
from pathlib import Path

from location_converter import convert_req_loc


def make_hex(longitude, latitude):
    return struct.pack(
        "<BIIdd", 1, 0x20000001, 4326,
        longitude, latitude
    ).hex()


cases = [
    ("New York", make_hex(-74.006, 40.7128),
     "POINT(-74.006 40.7128)"),
    ("Los Angeles", make_hex(-118.2437, 34.0522),
     "POINT(-118.2437 34.0522)"),
    ("London", make_hex(-0.1278, 51.5074),
     "POINT(-0.1278 51.5074)"),
    ("Null location", None, ""),
    ("Empty location", "", ""),
    ("Invalid hexadecimal", "INVALID_HEX", ""),
    ("Incomplete hexadecimal", "0101000020E61000", ""),
]

output_path = Path(__file__).parent / "comparison_results.csv"

with output_path.open("w", newline="", encoding="utf-8") as file:
    writer = csv.writer(file)
    writer.writerow([
        "test_case", "mock_input", "expected_output",
        "actual_output", "result"
    ])

    for name, value, expected in cases:
        actual = convert_req_loc(value)
        result = "PASS" if actual == expected else "FAIL"

        writer.writerow([
            name, value, expected, actual, result
        ])

        print(f"{name}: {result}")

print(f"\nComparison saved to: {output_path}")
