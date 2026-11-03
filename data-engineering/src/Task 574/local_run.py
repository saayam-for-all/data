"""Execute the real Lambda handler offline and generate reviewable evidence."""

import argparse
import csv
import hashlib
import html
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from Data_ArchiveRequestData import lambda_function
from Data_ArchiveRequestData.db_client import DatabaseClient
from local_fixture import LocalS3, create_fixture


def validation_markdown(report):
    """Render observed counts, including explicit scope and test limitations."""
    lines = ["# Task 574 local validation", "",
             f"Generated: {report['generated_at']}", "",
             "Synthetic data on SQLite; S3 replaced with a local file sink. "
             "The real lambda_handler and export SQL were executed. No AWS calls.", "",
             f"- Source requests selected: **{report['source_count']}**",
             f"- Exported requests: **{report['exported_count']}**",
             f"- Distinct exported IDs: **{report['distinct_request_count']}**",
             f"- Duplicate requests: **{report['duplicate_request_count']}**",
             f"- Source unchanged: **{report['source_unchanged']}**",
             f"- Source rows with null timestamps: **{report['source_null_timestamps']}**",
             f"- Null timestamps excluded by selection: **{report['excluded_null_timestamps']}**",
             "- All source columns, raw IDs and descriptions retained; six readable labels added.",
             "- All six lookups use LEFT JOIN; no user-table join or category-tree join.", "",
             "| Reference | Matched | Null retained | Unmatched retained | Matched but null label |",
             "|---|---:|---:|---:|---:|"]
    for name, counts in report["references"].items():
        lines.append(f"| {name} | {counts['matched']} | {counts['null']} | "
                     f"{counts['unmatched']} | {counts['missing_label']} |")
    lines += ["", f"CSV SHA-256: `{report['sha256']}`", "",
              "The null and unmatched lookup rows are deliberately invalid relative to the "
              "production FK/NOT NULL constraints. They demonstrate preservation under dirty input.", "",
              "Task 573 historical baseline (221 dev requests, 2026-10-24): unmatched = 0 for all "
              "nine references; beneficiary_id null = 8; lead_volunteer_id null = 218; all others = 0. "
              "Those are published schema counts, not results from this synthetic run.", "",
              "Production PostgreSQL/PostGIS, live S3, deployment, and retirement of the old Lambda "
              "have not been exercised. Keep the previous Lambda until deployment validation succeeds.", ""]
    return "\n".join(lines)


def write_html(destination, report, transcript):
    """Render actual results and CSV values for browser screenshots."""
    with (destination / "requests_enriched.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    visible = ("req_id", "req_cat_id", "req_category", "req_type_id", "req_type",
               "req_priority", "req_status", "req_desc")
    table = "<tr>" + "".join(f"<th>{name}</th>" for name in visible) + "</tr>"
    for row in rows:
        table += "<tr>" + "".join(f"<td>{html.escape(row[name]) or '<i>NULL / empty</i>'}</td>"
                                   for name in visible) + "</tr>"
    tests = (destination / "tests.txt").read_text(encoding="utf-8") if (destination / "tests.txt").exists() else "Run tools/run_checks.py to save the test output."
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>Task 574 — local execution evidence</title>
<style>body{{font:16px system-ui;margin:32px;color:#15243c;background:#f4f7fc}}
h1{{margin-bottom:8px}}section{{background:white;border:1px solid #cbd5e1;padding:24px;margin:24px 0;border-radius:10px}}
pre{{white-space:pre-wrap;font:14px Consolas,monospace;line-height:1.5}}table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border:1px solid #cad3df;padding:8px;text-align:left;vertical-align:top}}th{{background:#e9f1fb}}
td{{white-space:pre-wrap}}i{{color:#64748b}}.pass{{color:#176b40;font-weight:700}}</style>
<h1>Data_ArchiveRequestData · Task 574</h1>
<p>Evidence from an executed local run. Synthetic SQLite fixture and a local S3 substitute.</p>
<section id="execution"><h2>Execution and validation</h2>
<p class="pass">{report['validation'].upper()} · {report['source_count']} source rows → {report['exported_count']} exported · {report['duplicate_request_count']} duplicates</p>
<pre>{html.escape(transcript)}</pre><pre>{html.escape(validation_markdown(report))}</pre></section>
<section id="export"><h2>Exported CSV preview</h2><p>Selected columns; the CSV contains all {len(report['columns'])} columns.</p><table>{table}</table></section>
<section id="tests"><h2>Captured test output</h2><pre>{html.escape(tests)}</pre></section></html>"""
    (destination / "report.html").write_text(document, encoding="utf-8")


def main():
    """Generate all local artifacts without reading AWS or database credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "evidence")
    args = parser.parse_args()
    destination = args.output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="task574-") as temporary:
        database = Path(temporary) / "synthetic.sqlite3"
        create_fixture(database)
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        sink = LocalS3(destination / "requests_enriched.csv")
        env = {"ARCHIVE_S3_BUCKET": "local-synthetic-archive", "ARCHIVE_BATCH_SIZE": "3"}
        original_runner = lambda_function.run_archive

        def offline_runner(event):
            """Inject local adapters into the handler's normal orchestration path."""
            return original_runner(event, environ=env,
                                   database_factory=lambda schema: DatabaseClient.local(database),
                                   s3_factory=lambda: sink)

        # Fail immediately on any accidental networking in the offline path.
        with patch.object(lambda_function, "run_archive", side_effect=offline_runner), \
                patch("socket.socket.connect", side_effect=AssertionError("Offline demo attempted network access")):
            result = lambda_function.lambda_handler({}, None)
        result["source_unchanged"] = before == hashlib.sha256(database.read_bytes()).hexdigest()
        assert result["source_unchanged"]
        with closing(sqlite3.connect(database)) as connection:
            source_ids = {row[0] for row in connection.execute("SELECT req_id FROM requests")}
        with (destination / "requests_enriched.csv").open(encoding="utf-8", newline="") as file:
            exported_ids = [row["req_id"] for row in csv.DictReader(file)]
        assert set(exported_ids) == source_ids and len(exported_ids) == len(source_ids)
        result["exported_id_set_matches_source"] = True
        result["upload_backend"] = "local file sink (no S3 network calls)"
        (destination / "validation_summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (destination / "validation_summary.md").write_text(validation_markdown(result), encoding="utf-8")
        transcript = ("Command: python local_run.py\n"
                      "Handler: Data_ArchiveRequestData.lambda_function.lambda_handler({}, None)\n"
                      f"Validation: {result['validation']}\n"
                      f"Source: {result['source_count']} | Exported: {result['exported_count']} | "
                      f"Distinct: {result['distinct_request_count']} | Duplicates: {result['duplicate_request_count']}\n"
                      "Source file unchanged: True | Source/export ID sets equal: True\n"
                      f"Local CSV: requests_enriched.csv ({result['bytes']} bytes)\n"
                      f"SHA-256: {result['sha256']}\n"
                      "Network access blocked during handler execution.\n")
        (destination / "execution.txt").write_text(transcript, encoding="utf-8")
        write_html(destination, result, transcript)
        print(transcript)
        print(f"Evidence folder: {destination}")


if __name__ == "__main__":
    main()
