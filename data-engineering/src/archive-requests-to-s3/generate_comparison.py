
import csv
import struct
from pathlib import Path

from location_converter import convert_location


def make_wkb(longitude, latitude, endian="<", srid=None):
    byte_order = 1 if endian == "<" else 0
    geometry_type = 0x20000001 if srid is not None else 1

    if srid is None:
        return struct.pack(
            endian + "BIdd",
            byte_order, geometry_type, longitude, latitude
        ).hex()

    return struct.pack(
        endian + "BIIdd",
        byte_order, geometry_type, srid, longitude, latitude
    ).hex()


def main():
    # Synthetic fixtures; maintainer-provided examples are pending.
    cases = [
        ("REQ-001", make_wkb(-73.5, 40.25), "POINT(-73.5 40.25)"),
        ("REQ-002", make_wkb(-74.0, 40.5, srid=4326), "POINT(-74 40.5)"),
        ("REQ-003", make_wkb(77.25, 28.5, endian=">"), "POINT(77.25 28.5)"),
        ("REQ-004", make_wkb(0.0, 0.0), "POINT(0 0)"),
        ("REQ-005", make_wkb(180.0, 90.0), "POINT(180 90)"),
        ("REQ-006", make_wkb(-180.0, -90.0), "POINT(-180 -90)"),
        ("REQ-007", None, ""),
        ("REQ-008", "", ""),
        ("REQ-009", "INVALID", ""),
        ("REQ-010", "1234", ""),
        ("REQ-011", make_wkb(200.0, 95.0), ""),
        ("REQ-012", struct.pack("<BI", 1, 2).hex(), ""),
    ]

    evidence_dir = Path(__file__).resolve().parent / "evidence"
    evidence_dir.mkdir(exist_ok=True)

    output_file = evidence_dir / "comparison.csv"

    passed = 0

    with output_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            "request_id", "mock_input", "expected_output",
            "actual_output", "result"
        ])

        for request_id, mock_input, expected in cases:
            actual = convert_location(mock_input)
            result = "PASS" if actual == expected else "FAIL"

            if result == "PASS":
                passed += 1

            writer.writerow([
                request_id, mock_input, expected, actual, result
            ])

            print(f"{request_id}: {result} | {actual!r}")

    print(f"\nResults: {passed}/{len(cases)} passed")
    print(f"Comparison saved to: {output_file}")

    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
