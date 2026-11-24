"""Run the Task 2 archive Lambda against a local database, then verify it (issue #586).

Contributors have no database or S3 access, and the source database is read
only, so a request with a broken reference cannot be created there. This
harness builds a local copy of the schema (local_schema.sql), seeds the lookup
tables from database/lookup_tables and a set of requests chosen to exercise
every check, then calls the real lambda_handler with:

  * a psycopg2 connection to the local database whose session time zone is
    deliberately not UTC (America/Phoenix), and
  * an S3 client mocked in-process by moto, so the Lambda's own upload code runs.

The sequence of runs:

  run 1  window (09:00, 10:00]
  run 2  window (10:00, 11:00]
  run 3  window (10:00, 11:00] again             re-run, check 6
         -- a request is created at 11:30 and REQ-V-001 is edited at 11:45
  run 4  window (11:00, 12:00]                    created-between-runs, check 3

and then runs verify_request_archive.py against the result. Two scenarios run
by default, each on a freshly built database:

  as_built          the Lambda exactly as on the branch
  window_key_fix    the S3 key is derived from the window instead of the run
                    time, to show what checks 2 and 6 report once that is fixed

It also checks two things only a local run can show: that the default
watermark_end is UTC when the process time zone is not, and that two runs in
the same second write the same key.

Usage, from data-engineering/ (needs a PostgreSQL you can write to, for example
`docker run --rm -p 5433:5432 -e POSTGRES_PASSWORD=pw postgres:16`):

    pip install -r scripts/archive_verification/requirements-dev.txt
    python scripts/archive_verification/run_local_harness.py \\
        --dsn postgresql://postgres:pw@localhost:5433/postgres \\
        --report-dir scripts/archive_verification/reports
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
DATA_ENGINEERING = HERE.parents[1]
REPO_ROOT = HERE.parents[2]
sys.path.insert(0, str(DATA_ENGINEERING))
sys.path.insert(0, str(HERE))

import psycopg2  # noqa: E402

import verify_request_archive as verifier  # noqa: E402

SCHEMA = "virginia_dev_saayam_rdbms"
BUCKET = "saayam-request-archive-local"
REGION = "us-east-1"
SESSION_TIMEZONE = "America/Phoenix"  # anything but UTC

LOOKUP_FILES = {  # repo CSV -> table name the Lambda reads
    "request_for.csv": "request_for",
    "request_isleadvol.csv": "request_isleadvol",
    "help_categories.csv": "help_categories",
    "request_type.csv": "request_types",
    "request_priority.csv": "request_priorities",
    "request_status.csv": "request_statuses",
}

DAY = "2026-11-09"
W0 = (f"{DAY} 09:00:00", f"{DAY} 10:00:00")
W1 = (f"{DAY} 10:00:00", f"{DAY} 11:00:00")
W2 = (f"{DAY} 11:00:00", f"{DAY} 12:00:00")

REQUEST_COLUMNS = [
    "req_id", "creator_id", "req_for_id", "req_islead_id", "req_cat_id", "req_type_id",
    "req_priority_id", "req_status_id", "req_loc", "iscalamity", "req_subj", "req_desc",
    "req_doc_link", "audio_req_desc", "submission_date", "serviced_date", "last_updated_at",
    "to_public", "beneficiary_id", "lead_volunteer_id", "deletion_reason",
]


def request(req_id: str, updated: str, refs: Tuple[Any, Any, Any, Any, Any, Any],
            desc: str = "Seeded for #586", serviced: Optional[str] = f"{DAY} 08:30:00") -> Dict[str, Any]:
    """One request row. refs = (for, islead, category, type, priority, status)."""
    req_for, islead, cat, req_type, priority, status = refs
    return {
        "req_id": req_id, "creator_id": "SID-00-000-000-001", "req_for_id": req_for,
        "req_islead_id": islead, "req_cat_id": cat, "req_type_id": req_type,
        "req_priority_id": priority, "req_status_id": status, "req_loc": "Suffolk, VA",
        "iscalamity": False, "req_subj": f"Subject {req_id}", "req_desc": desc,
        "req_doc_link": None, "audio_req_desc": None, "submission_date": f"{DAY} 08:00:00",
        "serviced_date": serviced, "last_updated_at": updated, "to_public": True,
        "beneficiary_id": "SID-00-000-000-002", "lead_volunteer_id": None, "deletion_reason": None,
    }


GOOD = (0, 1, "1.1", 1, 2, 1)

# Present before the first run.
INITIAL_REQUESTS = [
    request("REQ-V-000", f"{DAY} 09:30:00", GOOD),
    request("REQ-V-007", f"{DAY} 10:00:00", GOOD, desc="On the W0/W1 boundary: belongs to W0 only"),
    request("REQ-V-001", f"{DAY} 10:05:00", GOOD),
    request("REQ-V-002", f"{DAY} 10:10:00", (0, 1, "CAT-MISSING", 1, 2, 1),
            desc="Category points at nothing (issue's check 5 case)"),
    request("REQ-V-003", f"{DAY} 10:15:00", (0, 1, None, 1, 2, 1), desc="Category is null"),
    request("REQ-V-004", f"{DAY} 10:20:00", (None,) * 6, desc="Every reference is null"),
    request("REQ-V-005", f"{DAY} 10:25:00", (9, 9, "NO-SUCH-CAT", 9, 9, 99),
            desc="Every reference points at nothing"),
    request("REQ-V-008", f"{DAY} 10:35:12.345678", (1, 0, "5.1.2", 0, 3, 6),
            desc='Comma, "quotes", a\nnewline and café: CSV quoting'),
    request("REQ-V-009", f"{DAY} 10:40:00", GOOD, serviced=None, desc="Not serviced yet"),
    request("REQ-V-006", f"{DAY} 11:00:00", GOOD, desc="On the W1/W2 boundary: belongs to W1 only"),
    request("REQ-V-012", f"{DAY} 12:30:00", GOOD, desc="After every window: must not be archived"),
]

# Created or changed between run 3 and run 4.
CREATED_BETWEEN_RUNS = request("REQ-V-010", f"{DAY} 11:30:00", GOOD, desc="Created between two runs")
ON_W2_END = request("REQ-V-011", f"{DAY} 12:00:00", GOOD, desc="On the W2 end: inclusive")
EDIT = ("REQ-V-001", f"{DAY} 11:45:00", 3)  # req_id, new last_updated_at, new status (RESOLVED)


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
def build_database(dsn: str) -> None:
    """Create the schema and seed lookups and the initial requests."""
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute((HERE / "local_schema.sql").read_text(encoding="utf-8"))
        for file_name, table in LOOKUP_FILES.items():
            with open(REPO_ROOT / "database" / "lookup_tables" / file_name, encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                header = next(reader)
                for row in reader:
                    values = [None if v == "NULL" else v for v in row]
                    cur.execute(f"INSERT INTO {SCHEMA}.{table} ({', '.join(header)}) "
                                f"VALUES ({', '.join(['%s'] * len(header))})", values)
        for row in INITIAL_REQUESTS:
            insert_request(cur, row)


def insert_request(cur: Any, row: Dict[str, Any]) -> None:
    cur.execute(f"INSERT INTO {SCHEMA}.requests ({', '.join(REQUEST_COLUMNS)}) "
                f"VALUES ({', '.join(['%s'] * len(REQUEST_COLUMNS))})",
                [row[c] for c in REQUEST_COLUMNS])


def change_source_between_runs(dsn: str) -> None:
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        insert_request(cur, CREATED_BETWEEN_RUNS)
        insert_request(cur, ON_W2_END)
        req_id, updated, status = EDIT
        cur.execute(f"UPDATE {SCHEMA}.requests SET last_updated_at = %s, req_status_id = %s "
                    f"WHERE req_id = %s", (updated, status, req_id))


def lambda_connection(dsn: str) -> Any:
    """The connection handed to the Lambda: session time zone deliberately not UTC."""
    return psycopg2.connect(dsn, options=f"-c TimeZone={SESSION_TIMEZONE}")


# --------------------------------------------------------------------------- #
# Lambda runs
# --------------------------------------------------------------------------- #
class FrozenClock:
    """Replaces lambda_function.datetime so two runs can share one instant."""

    def __init__(self, instant: datetime):
        self.instant = instant

    def now(self, tz: Any = None) -> datetime:
        return self.instant if tz else self.instant.replace(tzinfo=None)


def invoke(lambda_module: Any, dsn: str, s3: Any, window: Tuple[str, str],
           prefix: str = "requests_enriched", dry_run: bool = False) -> Tuple[Dict[str, Any], float]:
    """Call the real lambda_handler for one window and return (body, seconds)."""
    conn = lambda_connection(dsn)
    event = {"bucket": BUCKET, "region": REGION, "schema": SCHEMA, "prefix": prefix,
             "watermark_start": window[0], "dry_run": dry_run}
    if window[1] is not None:
        event["watermark_end"] = window[1]
    started = time.perf_counter()
    try:
        response = lambda_module.lambda_handler(event, None, connection=conn, s3_client=s3)
    finally:
        seconds = time.perf_counter() - started
        conn.rollback()
        conn.close()
    body = json.loads(response["body"])
    if response["statusCode"] != 200:
        raise RuntimeError(f"Lambda returned {response['statusCode']}: {body}")
    return body, seconds


def patch_window_keys(lambda_module: Any, window: Tuple[str, str]) -> None:
    """Proposed fix: derive the key from the window, so a re-run overwrites."""
    def build_key(_run_ts: datetime, prefix: str = "requests_enriched") -> str:
        start, end = (datetime.fromisoformat(w).strftime("%Y%m%dT%H%M%S") for w in window)
        return f"{prefix}/window_start={start}Z/window_end={end}Z/requests_enriched.csv"
    lambda_module.build_s3_key = build_key


def run_scenario(name: str, dsn: str, report_dir: Path, fix_keys: bool) -> Dict[str, Any]:
    """Build the database, run the Lambda four times, verify, and report."""
    import boto3
    from moto import mock_aws

    from src.data_archive_request_data import lambda_function

    original_build_key = lambda_function.build_s3_key
    build_database(dsn)
    timings: Dict[str, float] = {}
    runs: List[Dict[str, str]] = []

    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET)

        def archive(label: str, window: Tuple[str, str]) -> None:
            if fix_keys:
                patch_window_keys(lambda_function, window)
            body, seconds = invoke(lambda_function, dsn, s3, window)
            timings[label] = seconds
            runs.append({"key": body["export"]["key"],
                         "watermark_start": body["validation_summary"]["watermark_start"],
                         "watermark_end": body["validation_summary"]["watermark_end"],
                         "label": label})
            time.sleep(1.1)  # run_ts has one-second resolution; see the collision check

        try:
            archive("run 1 (09:00, 10:00]", W0)
            archive("run 2 (10:00, 11:00]", W1)
            archive("run 3 (10:00, 11:00] re-run", W1)
            change_source_between_runs(dsn)
            archive("run 4 (11:00, 12:00]", W2)
        finally:
            lambda_function.build_s3_key = original_build_key

        folder = report_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "manifest.json").write_text(json.dumps({"runs": runs}, indent=2), encoding="utf-8")
        for item in runs:  # keep the archived files next to the report
            target = folder / "archive" / item["key"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(s3.get_object(Bucket=BUCKET, Key=item["key"])["Body"].read())

        source_conn = psycopg2.connect(dsn)
        source_conn.set_session(readonly=True)
        try:
            print(f"\n######## scenario: {name}")
            results, seconds = verifier.verify(
                verifier.load_manifest(str(folder / "manifest.json")),
                verifier.S3Store(BUCKET, client=s3),
                verifier.SourceReader(source_conn, SCHEMA),
                list_prefix="requests_enriched/",
                report_dir=str(folder),
                context={"scenario": name, "database": "local PostgreSQL (rebuilt schema)",
                         "archive": f"s3://{BUCKET} (moto)", "lambda_session_timezone": SESSION_TIMEZONE},
            )
        finally:
            source_conn.close()

    return {"scenario": name, "results": [vars(r) for r in results],
            "verification_seconds": round(seconds, 3),
            "lambda_seconds": {k: round(v, 3) for k, v in timings.items()}, "runs": runs}


# --------------------------------------------------------------------------- #
# Checks only a local run can make
# --------------------------------------------------------------------------- #
def check_default_watermark_is_utc(dsn: str) -> Dict[str, Any]:
    """With the process clock in America/Phoenix, the default watermark_end must still be UTC."""
    from src.data_archive_request_data import lambda_function

    build_database(dsn)
    previous = os.environ.get("TZ")
    os.environ["TZ"] = SESSION_TIMEZONE
    time.tzset()
    try:
        body, _ = invoke(lambda_function, dsn, None, (W0[0], None), dry_run=True)
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        local_now = datetime.now()
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()
    end = datetime.fromisoformat(body["validation_summary"]["watermark_end"])
    drift = abs((utc_now - end).total_seconds())
    return {"check": "Default watermark_end is UTC when the process time zone is not",
            "status": "PASS" if drift < 120 else "FAIL",
            "expected": f"about {utc_now:%Y-%m-%d %H:%M} (UTC)",
            "actual": f"{end} (local clock read {local_now:%Y-%m-%d %H:%M})",
            "details": f"difference from UTC now: {drift:.0f} s"}


def check_same_second_collision(dsn: str) -> Dict[str, Any]:
    """Two different windows archived in the same second: does the second overwrite the first?"""
    import boto3
    from moto import mock_aws

    from src.data_archive_request_data import lambda_function

    build_database(dsn)
    original = lambda_function.datetime
    lambda_function.datetime = FrozenClock(datetime(2026, 11, 24, 13, 0, 0, tzinfo=timezone.utc))
    try:
        with mock_aws():
            s3 = boto3.client("s3", region_name=REGION)
            s3.create_bucket(Bucket=BUCKET)
            first, _ = invoke(lambda_function, dsn, s3, W0, prefix="collision")
            second, _ = invoke(lambda_function, dsn, s3, W1, prefix="collision")
            keys = [o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET, Prefix="collision/").get("Contents", [])]
    finally:
        lambda_function.datetime = original
    same = first["export"]["key"] == second["export"]["key"]
    return {"check": "Two windows archived in the same second keep separate files",
            "status": "FAIL" if same else "PASS",
            "expected": "2 objects (one per window)",
            "actual": f"{len(keys)} object(s); both runs wrote {first['export']['key']}" if same
            else f"{len(keys)} objects",
            "details": "run_ts has one-second resolution and ignores the window, so the second "
                       "window's file replaced the first one's: the first window's rows are lost "
                       "from S3 although both runs returned 200." if same else ""}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dsn", required=True, help="writable local PostgreSQL; the schema is dropped and rebuilt")
    parser.add_argument("--report-dir", default=str(HERE / "reports"))
    parser.add_argument("--scenario", choices=["as_built", "window_key_fix", "all"], default="all")
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    started = time.perf_counter()
    summary: Dict[str, Any] = {"generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "scenarios": [], "local_only_checks": []}

    if args.scenario in ("as_built", "all"):
        summary["scenarios"].append(run_scenario("as_built", args.dsn, report_dir, fix_keys=False))
    if args.scenario in ("window_key_fix", "all"):
        summary["scenarios"].append(run_scenario("window_key_fix", args.dsn, report_dir, fix_keys=True))

    print("\n######## local-only checks")
    for check in (check_default_watermark_is_utc, check_same_second_collision):
        result = check(args.dsn)
        summary["local_only_checks"].append(result)
        print(f"[{result['status']}] {result['check']}\n  Expected: {result['expected']}\n"
              f"  Actual:   {result['actual']}" + (f"\n    - {result['details']}" if result["details"] else ""))

    summary["harness_seconds"] = round(time.perf_counter() - started, 3)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "harness_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nHarness finished in {summary['harness_seconds']:.2f} s; reports in {report_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
