"""
Proves verify_archive.py actually catches the failures issue #586 cares
about, rather than just passing on clean data by coincidence. Takes the
good archive output from local_export.py, applies one mutation at a time to
a scratch copy, and confirms the specific check that mutation should break
is the one that reports FAIL (and that nothing else does).

Run after local_schema.sql / load_mock_data.py / local_export.py against the
same local Postgres container (see README.md in this folder).
"""
import csv
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(__file__)
GOOD_S3_ROOT = os.path.join(HERE, "local_s3")
SCRATCH_ROOT = os.path.join(HERE, "mutated_s3")
GOOD_FILE = os.path.join(GOOD_S3_ROOT, "requests", "last_updated_year=2026", "last_updated_month=11",
                         "last_updated_day=12", "run_id=1", "requests.csv")
MUTATED_FILE = os.path.join(SCRATCH_ROOT, "requests", "last_updated_year=2026", "last_updated_month=11",
                            "last_updated_day=12", "run_id=1", "requests.csv")

VERIFY = [sys.executable, os.path.join(HERE, "..", "verify_archive.py"),
          "--run-id", "1", "--known-broken-ids", "REQ-BROKENREF"]
ENV = {**os.environ, "PGHOST": "localhost", "PGPORT": "55432", "PGUSER": "postgres",
       "PGPASSWORD": "postgres", "PGDATABASE": "saayam"}


def reset_scratch():
    if os.path.exists(SCRATCH_ROOT):
        shutil.rmtree(SCRATCH_ROOT)
    shutil.copytree(GOOD_S3_ROOT, SCRATCH_ROOT)


def run_verify():
    result = subprocess.run(VERIFY + ["--s3-root", SCRATCH_ROOT], env=ENV, capture_output=True, text=True)
    return result.stdout


def expect(name, output, expected_failing_check, other_checks_should_pass=True):
    lines = [l for l in output.splitlines() if l.strip().startswith(("PASS", "FAIL"))]
    failing = [l for l in lines if l.startswith("FAIL")]
    target_failed = any(expected_failing_check in l for l in failing)
    print(f"{'OK ' if target_failed else 'BUG'}  {name}: expected '{expected_failing_check}' to FAIL -> "
          f"{'did' if target_failed else 'did NOT'}. Failing checks: {[l.split(None,1)[0] for l in failing]} "
          f"{[l for l in failing]}")
    return target_failed


def mutate_delete_row(rows, header):
    return [rows[0]] + rows[2:]  # keep the header (rows[0]), drop the first data row (rows[1])


def mutate_duplicate_row(rows, header):
    return rows + [rows[1]]


def mutate_change_field(rows, header):
    idx = header.index("req_subj")
    out = list(rows)
    out[1] = list(out[1])
    out[1][idx] = out[1][idx] + " TAMPERED"
    return out


def mutate_change_fk(rows, header):
    idx = header.index("req_status_id")
    out = list(rows)
    out[1] = list(out[1])
    out[1][idx] = "999999"  # id that doesn't exist in request_statuses
    return out


def mutate_shift_row(rows, header):
    # Swap two rows' req_id values -- content "moves" to the wrong row without
    # changing the overall row count or the set of column values present.
    idx = header.index("req_id")
    out = [list(r) for r in rows]
    out[1][idx], out[2][idx] = out[2][idx], out[1][idx]
    return out


MUTATIONS = [
    ("deleted row", mutate_delete_row, "1. row counts"),
    ("duplicated row", mutate_duplicate_row, "2. no duplicate"),
    ("changed field (req_subj)", mutate_change_field, "4. every field matches"),
    ("changed FK (req_status_id -> nonexistent)", mutate_change_fk, "4. every field matches"),
    ("shifted row (req_id swapped between two rows)", mutate_shift_row, "4. every field matches"),
]


def main():
    print("Baseline (unmutated) run:")
    reset_scratch()
    print(run_verify())
    print("=" * 100)

    for name, mutate_fn, expected_check in MUTATIONS:
        reset_scratch()
        with open(MUTATED_FILE, newline="", encoding="utf-8") as f:
            reader = list(csv.reader(f))
        header, rows = reader[0], reader
        mutated = mutate_fn(rows, header)
        with open(MUTATED_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f, lineterminator="\n").writerows(mutated)

        output = run_verify()
        expect(name, output, expected_check)
        print("=" * 100)


if __name__ == "__main__":
    main()
