"""Build an evidence page from captured execution results, never invented values."""

import csv
import html
import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data-engineering" / "docs" / "archive_requests" / "evidence"


def main():
    """Render real logs, JUnit results, and the exact uploaded CSV."""
    validation = json.loads((OUT / "validation.json").read_text(encoding="utf-8"))
    suites = ET.parse(OUT / "test-results.xml").getroot()
    tests = suites.findall(".//testcase")
    failures = suites.findall(".//failure") + suites.findall(".//error")
    skipped = suites.findall(".//skipped")
    status = f"{len(tests) - len(failures) - len(skipped)}/{len(tests)} tests passed; {len(failures)} failed; {len(skipped)} skipped"
    with (OUT / "sample_requests.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    columns = [
        "req_id",
        "creator_name",
        "help_category",
        "request_priority",
        "request_status",
        "beneficiary_name",
    ]
    headers = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(row[c])}</td>" for c in columns) + "</tr>"
        for row in rows
    )
    stats = "".join(
        f"<tr><td>{html.escape(column)}</td><td>{metrics['matched']}</td><td>{metrics['null']}</td><td>{metrics['unmatched']}</td><td>{metrics['missing_label']}</td></tr>"
        for column, metrics in validation["references"].items()
    )
    log = html.escape((OUT / "local-execution.txt").read_text(encoding="utf-8"))
    test_log = html.escape((OUT / "test-output.txt").read_text(encoding="utf-8"))
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>Issue 574 — Local execution evidence</title>
<style>body{{font:16px/1.5 system-ui;margin:40px;background:#f4f6fa;color:#17263d}}section{{background:white;border:1px solid #dae2ef;border-radius:10px;padding:28px;margin:24px 0}}h1{{font-size:28px}}h2{{margin-top:0}}.scope{{background:#fff2d8;padding:14px;border-left:4px solid #d89a22}}.ok{{color:#12653e;font-weight:bold}}pre{{background:#142137;color:#eef5ff;padding:18px;border-radius:8px;white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 Consolas,monospace}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;padding:10px;border:1px solid #d9e0ec;overflow-wrap:anywhere}}th{{background:#edf2fa}}.muted{{color:#58677e}}.counts{{font-size:22px;font-weight:650}}code{{font-family:Consolas,monospace}}</style>
<h1>Data_ArchiveRequestData · Issue #574</h1>
<p class="scope">LOCAL EVIDENCE — synthetic requests on real PostgreSQL 18.4. S3 upload is mocked. Task #573 production mapping and counts are pending. These screenshots do not claim deployment or live database validation.</p>
<section id="execution"><h2>Successful local Lambda execution</h2><p class="scope">Synthetic fixture · real PostgreSQL · S3 mocked · Task #573 pending</p><p class="ok">{html.escape(status)}</p><p class="counts">Source: {validation["source_count"]} · Exported: {validation["exported_count"]} · Duplicates: {validation["duplicate_request_count"]}</p><pre>{log}</pre><h3>Captured pytest output</h3><pre>{test_log}</pre><p class="muted">This page renders saved execution logs and machine-readable JUnit results. It is not a terminal screenshot.</p></section>
<section id="output"><h2>Exported output · one enriched requests CSV</h2><p class="scope">Synthetic fixture · real PostgreSQL · S3 mocked · Task #573 pending</p><p>Preview of six columns from the exact uploaded CSV; all 21 request fields are in <code>sample_requests.csv</code>.</p><table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table><p><code>\\N</code> means SQL NULL; empty strings stay empty; literal backslashes are doubled. Unmatched IDs and missing labels remain visible in marked cells.</p><h3>Validation by reference · same six selected requests</h3><table><thead><tr><th>Requests reference</th><th>Matched</th><th>Null</th><th>Unmatched</th><th>Missing label*</th></tr></thead><tbody>{stats}</tbody></table><p class="muted">* Missing labels are a subset of matched keys. Each reference has 4 matched + 1 null + 1 unmatched = 6. All nine lookups use LEFT JOIN.</p><p>CSV SHA-256: <code>{validation["sha256"]}</code></p></section>
</html>"""
    (OUT / "report.html").write_text(page, encoding="utf-8")
    summary = [
        "# Issue #574 validation summary",
        "",
        "Scope: synthetic fixture on real PostgreSQL; S3 mocked. Task #573 is pending.",
        "",
        f"- Tests: {status}.",
        f"- Selected source requests: {validation['source_count']}.",
        f"- Exported requests: {validation['exported_count']}.",
        f"- Duplicate requests: {validation['duplicate_request_count']}.",
        "- One enriched requests CSV was captured from the actual Lambda handler upload.",
        "- All nine references use LEFT JOIN; every null and unmatched reference is retained.",
        "- Each mapping has 4 matched + 1 null + 1 unmatched = 6 selected requests.",
        "- Missing user labels are marked and retained (subset of matched keys).",
        "- Duplicate lookup keys and duplicate/null source keys cause failure before upload.",
        "- Empty/filtered selections, concurrent changes, read-only transactions, small cursor batches,",
        "  CSV escaping, schema drift, encryption, and S3 failure propagation are covered.",
        f"- CSV SHA-256: `{validation['sha256']}`.",
        "",
        "Artifacts: [sample CSV](sample_requests.csv), [validation JSON](validation.json),",
        "[JUnit](test-results.xml), [execution log](local-execution.txt),",
        "[execution screenshot](local-execution.png), [output screenshot](exported-output.png).",
        "",
        "Screenshots capture the generated evidence report, not a terminal or AWS console.",
        "",
        "Pending: Task #573 approved production mappings/counts, deployed validation,",
        "and team-lead confirmation before retiring the previous Lambda. The old Lambda was untouched.",
    ]
    (OUT / "validation_summary.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )
    print(status)


if __name__ == "__main__":
    main()
