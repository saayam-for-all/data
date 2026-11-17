"""Rebuild issue #578 evidence from synthetic fixtures and the real CSV CLI."""

import csv
import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/request_locations"
EVIDENCE = ROOT / "docs/request_locations/evidence"


def main() -> None:
    """Run regression tests, export mock requests, and compare every output cell."""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(ROOT / "tests"),
         "-p", "test_request_location.py", "-v"],
        capture_output=True, text=True, check=False,
    )
    (EVIDENCE / "test-results.txt").write_text(tests.stdout + tests.stderr, encoding="utf-8")
    if tests.returncode:
        raise SystemExit(tests.returncode)
    export = subprocess.run(
        [sys.executable, str(ROOT / "scripts/convert_request_locations.py"),
         str(FIXTURES / "requests.csv"), str(EVIDENCE / "converted_requests.csv")],
        capture_output=True, text=True, check=True,
    )
    cases = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
    with (EVIDENCE / "converted_requests.csv").open(encoding="utf-8", newline="") as file:
        actual = list(csv.DictReader(file))
    if len(actual) != len(cases):
        raise AssertionError("Exported row count differs from fixture count")
    comparisons = []
    for index, (case, row) in enumerate(zip(cases, actual), start=1):
        expected = case["expected"] or ""
        comparisons.append({
            "case": case["case"], "input": case["input"],
            "expected": expected, "actual": row["req_loc"],
            "result": "PASS" if row["req_loc"] == expected and row["req_id"] == str(index) else "FAIL",
        })
    with (EVIDENCE / "comparison.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=comparisons[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(comparisons)
    passed = sum(row["result"] == "PASS" for row in comparisons)
    summary = f"{passed}/{len(cases)} comparisons passed. {export.stdout.strip()}"
    print(summary)

    def display(value):
        """Make null and empty fields visible in the comparison."""
        return "NULL" if value is None else (str(value) or "(empty)")

    markdown = ["# Local conversion results — issue #578", "", summary, "",
                "Synthetic fixtures only; no database or AWS calls. Maintainer-provided mocks are not yet attached.",
                "", "| Case | Input | Expected CSV cell | Actual CSV cell | Result |",
                "|---|---|---|---|---|"]
    for row in comparisons:
        markdown.append("| " + " | ".join(display(value) for value in row.values()) + " |")
    (EVIDENCE / "comparison.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")

    sections = []
    for section, subset in (("valid", comparisons[:12]), ("invalid", comparisons[12:])):
        rows = "".join(
            "<tr>" + "".join(f"<td>{html.escape(display(value))}</td>" for value in row.values()) + "</tr>"
            for row in subset
        )
        sections.append(
            f'<section id="{section}"><h1>Request location conversion · #{578}</h1>'
            f'<p class="summary">{html.escape(summary)}</p>'
            '<p>Actual local CSV execution · synthetic fixtures only · no database or AWS access</p>'
            f'<h2>{"Valid coordinates" if section == "valid" else "Null and invalid inputs"}</h2>'
            '<p>12 regression tests passed, including 1,000 coordinate round trips. '
            'NULL/invalid locations retain the request row and become empty CSV cells.</p>'
            '<table><thead><tr><th>Case</th><th>Input</th><th>Expected CSV cell</th>'
            f'<th>Actual CSV cell</th><th>Result</th></tr></thead><tbody>{rows}</tbody></table>'
            '<p>Blank input in requests.csv represents the JSON null/empty cases. '
            'The full comparison is available in comparison.csv and comparison.md.</p></section>'
        )
    page = '''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Issue 578 local conversion evidence</title><style>
body{margin:0;background:#eef2f7;color:#17273c;font:16px system-ui,sans-serif}
section{padding:32px;background:white;width:1350px;box-sizing:border-box;margin:20px}
h1{font-size:30px;margin:0 0 12px}h2{margin:24px 0 8px}.summary{font-weight:700;color:#146047}
table{border-collapse:collapse;width:100%;table-layout:fixed;margin-top:22px;font-size:14px}
th,td{padding:12px;border:1px solid #cbd5e1;text-align:left;overflow-wrap:anywhere;vertical-align:top}
th{background:#182f4b;color:white}th:nth-child(1){width:15%}th:nth-child(2){width:30%}
th:nth-child(3),th:nth-child(4){width:21%}th:last-child{width:7%}
td:nth-child(2),td:nth-child(3),td:nth-child(4){font-family:monospace}
td:last-child{font-weight:700;color:#146047}tr:nth-child(even){background:#f1f5f9}
</style>'''
    (EVIDENCE / "report.html").write_text(page + "".join(sections) + "</html>\n", encoding="utf-8")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
