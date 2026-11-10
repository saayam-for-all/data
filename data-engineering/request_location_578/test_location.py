
import struct
from location_converter import convert_req_loc


def make_hex(longitude, latitude):
    return struct.pack(
        "<BIIdd", 1, 0x20000001, 4326,
        longitude, latitude
    ).hex()


test_cases = [
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

passed = 0

print("TASK #578 - LOCATION CONVERSION TESTS")
print("=" * 55)

for name, value, expected in test_cases:
    actual = convert_req_loc(value)
    status = "PASS" if actual == expected else "FAIL"

    if status == "PASS":
        passed += 1

    print(f"\nTest: {name}")
    print(f"Expected: {expected!r}")
    print(f"Actual:   {actual!r}")
    print(f"Result:   {status}")

print("\n" + "=" * 55)
print(f"TOTAL: {passed}/{len(test_cases)} TESTS PASSED")

if passed != len(test_cases):
    raise SystemExit(1)
