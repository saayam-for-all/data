"""Compare expected and converted request locations from the mock CSV."""

import csv
from pathlib import Path

from src.utils.request_location import convert_req_loc

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = PROJECT_ROOT / "tests" / "fixtures" / "request_location_cases.csv"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "request_location_comparison.csv"


def main() -> None:
    """Write actual conversion results and fail if any mock differs."""
    with INPUT_PATH.open(newline="", encoding="utf-8") as source:
        cases = list(csv.DictReader(source))

    comparisons = []
    for case in cases:
        actual = convert_req_loc(case["req_loc"])
        comparisons.append({
            **case,
            "actual": actual or "",
            "matches": str(actual == case["expected"]).lower(),
        })

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=["case", "req_loc", "expected", "actual", "matches"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(comparisons)

    matched = sum(row["matches"] == "true" for row in comparisons)
    print(f"{matched}/{len(comparisons)} mock locations matched.")
    if matched != len(comparisons):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
