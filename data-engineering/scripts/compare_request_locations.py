"""Compare mock request locations with expected readable coordinates."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.request_location import convert_req_loc  # noqa: E402


FIXTURE_PATH = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "request_locations"
    / "cases.json"
)
EVIDENCE_DIR = PROJECT_ROOT / "docs" / "request_locations" / "evidence"


def _display(value: object) -> str:
    if value is None:
        return "<NULL>"
    if value == "":
        return "<EMPTY>"
    return str(value)


def main() -> int:
    cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    rows = []
    exported_rows = []

    for case in cases:
        actual = convert_req_loc(case["input"])
        passed = actual == case["expected"]
        rows.append(
            {
                "request_id": case["request_id"],
                "case_id": case["case_id"],
                "category": case["category"],
                "input": _display(case["input"]),
                "expected": case["expected"],
                "actual": actual,
                "result": "PASS" if passed else "FAIL",
            }
        )
        exported_rows.append(
            {
                "request_id": case["request_id"],
                "req_loc": actual,
            }
        )

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    comparison_path = EVIDENCE_DIR / "comparison.csv"
    export_path = EVIDENCE_DIR / "converted_requests.csv"

    with comparison_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=rows[0].keys(),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    with export_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("request_id", "req_loc"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(exported_rows)

    print(f"{'case_id':32} {'expected':48} {'actual':48} result")
    print("-" * 139)
    for row in rows:
        expected = row["expected"] or "<EMPTY>"
        actual = row["actual"] or "<EMPTY>"
        print(
            f"{row['case_id']:32} {expected:48} "
            f"{actual:48} {row['result']}"
        )

    passed_count = sum(row["result"] == "PASS" for row in rows)
    print()
    print(f"{passed_count}/{len(rows)} comparisons matched")
    print(
        f"{len(exported_rows)} input requests / "
        f"{len(exported_rows)} output requests retained"
    )
    print(f"Evidence: {comparison_path.relative_to(PROJECT_ROOT)}")
    print(f"Export preview: {export_path.relative_to(PROJECT_ROOT)}")
    return 0 if passed_count == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
