import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.utils.request_location import hex_to_wkt

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "request_locations", "cases.json")
OUT = os.path.join(
    ROOT, "docs", "request_locations", "evidence", "comparison.csv"
)

with open(FIXTURE) as f:
    cases = json.load(f)

rows = []
for c in cases:
    actual = hex_to_wkt(c["input"])
    result = "PASS" if actual == c["expected"] else "FAIL"
    rows.append([c["case"], c["input"] or "", c["expected"], actual, result])

with open(OUT, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["case", "input", "expected", "actual", "result"])
    writer.writerows(rows)

print(f"{'case':<24} {'expected':<26} {'actual':<26} result")
for case, _, expected, actual, result in rows:
    print(f"{case:<24} {expected or '(empty)':<26} {actual or '(empty)':<26} {result}")

passed = sum(1 for r in rows if r[4] == "PASS")
print(f"\n{passed}/{len(rows)} comparisons passed")