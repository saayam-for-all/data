
"""Generate local conversion evidence for Saayam issue #578."""

import csv
from pathlib import Path

from location_converter import convert_req_loc
from test_location_converter import make_point


CASES = [
    ("REQ-001", make_point(-74.006, 40.7128),
     "POINT(-74.006 40.7128)"),
    ("REQ-002", make_point(-118.2437, 34.0522, srid=False),
     "POINT(-118.2437 34.0522)"),
    ("REQ-003", None, ""),
    ("REQ-004", "INVALID_HEX", ""),
    ("REQ-005", make_point(77.209, 28.6139),
     "POINT(77.209 28.6139)"),
    ("REQ-006", make_point(-73.98565612345678, 40.74843398765432),
     "POINT(-73.98565612345678 40.74843398765432)"),
    ("REQ-007", make_point(0.0, 0.0), "POINT(0.0 0.0)"),
    ("REQ-008", make_point(151.2093, -33.8688, endian=">"),
     "POINT(151.2093 -33.8688)"),
]

evidence_dir = Path(__file__).resolve().parent / "evidence"
evidence_dir.mkdir(exist_ok=True)

comparison_path = evidence_dir / "comparison.csv"
export_path = evidence_dir / "converted_requests.csv"

with comparison_path.open("w", newline="", encoding="utf-8") as comparison_file, \
     export_path.open("w", newline="", encoding="utf-8") as export_file:

    comparison_writer = csv.writer(comparison_file)
    export_writer = csv.writer(export_file)

    comparison_writer.writerow(
        ["req_id", "mock_input", "expected_output", "actual_output", "result"]
    )
    export_writer.writerow(["req_id", "req_loc"])

    for req_id, mock_input, expected in CASES:
        actual = convert_req_loc(mock_input) or ""
        result = "PASS" if actual == expected else "FAIL"

        comparison_writer.writerow(
            [req_id, mock_input or "", expected, actual, result]
        )
        export_writer.writerow([req_id, actual])

        print(f"{req_id}: {result} | Expected={expected!r} | Actual={actual!r}")

        if result != "PASS":
            raise AssertionError(f"Conversion failed for {req_id}")

print(f"\nAll {len(CASES)} mock comparisons passed.")
print(f"Comparison report: {comparison_path}")
print(f"Exported CSV: {export_path}")
