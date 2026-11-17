#!/usr/bin/env python3
"""
Verify an archive file against the source database. Issue #586.

Pulls the exported object from S3, pulls the source rows and every lookup
table separately, builds what the file should contain, and diffs.

It deliberately does not reuse the Lambda's query. Rebuilding the expectation
from the raw tables is the only way a wrong join, a shifted column or a
mismatched label can be caught; re-running the exporter's own SQL would just
agree with itself.

Everything it does is read only. Needs psql on PATH and the usual PG*
environment variables, so run `source ~/saayam.env` first.

    python3 verify_archive.py                      # newest successful run
    python3 verify_archive.py --key backup/...     # a specific object
"""

import argparse
import csv
import re
import gzip
import io
import json
import os
import subprocess
import sys

SCHEMA = os.environ.get("ARCHIVE_SCHEMA", "virginia_dev_saayam_rdbms")
BUCKET = os.environ.get("BUCKET", "saayam-virginia-archive")

PASS, FAIL = [], []


BOOLS = {"t": "true", "true": "true", "f": "false", "false": "false"}


FRACTION = re.compile(r"^(.*\d{2}:\d{2}:\d{2})\.(\d+)$")


def norm(v):
    """Compare values, not representations.

    psql writes booleans as t/f where Python's csv writer writes True/False,
    and psql strips trailing zeros from fractional seconds where Python pads
    them to six digits. Both pairs mean the same thing.
    """
    v = (v or "").strip()
    low = v.lower()
    if low in BOOLS:
        return BOOLS[low]
    m = FRACTION.match(v)
    if m:
        frac = m.group(2).rstrip("0")
        return m.group(1) + ("." + frac if frac else "")
    return v


def check(ok, label, detail=""):
    (PASS if ok else FAIL).append(label)
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{(': ' + detail) if detail else ''}")


def psql_csv(sql):
    """Run a query and return (header, rows). Read only, no temp files."""
    out = subprocess.run(
        ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-c",
         f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true)"],
        capture_output=True, text=True)
    if out.returncode:
        sys.exit("psql failed:\n" + out.stderr.strip())
    r = list(csv.reader(io.StringIO(out.stdout)))
    return (r[0], r[1:]) if r else ([], [])


def load_config():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "..", "..", "src", "requests_backup_export", "config.json"),
              os.path.join(here, "config.json")):
        if os.path.exists(p):
            return json.load(open(p))
    sys.exit("cannot find config.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", help="S3 key to verify. Default: newest successful run.")
    args = ap.parse_args()

    cfg = load_config()
    table, ts_col, key_col = cfg["table"], cfg["timestamp_column"], cfg["key_column"]
    geom = set(cfg["geometry_columns"])
    joins = cfg["joins"]

    # 1. Find the run and its exact window. The filename only carries seconds,
    #    so the run log is the authoritative source for the bounds.
    where = f"AND s3_key = '{args.key}'" if args.key else ""
    hdr, rows = psql_csv(
        f"SELECT s3_key, range_from, range_to, source_rows, rows_written "
        f"FROM {SCHEMA}.archive_run_log "
        f"WHERE status = 'success' AND s3_key IS NOT NULL {where} "
        f"ORDER BY run_id DESC LIMIT 1")
    if not rows:
        sys.exit("no successful run found in archive_run_log")
    s3_key, lo, hi, logged_source, logged_written = rows[0]

    print(f"\nverifying  s3://{BUCKET}/{s3_key}")
    print(f"window     ({lo}, {hi}]")
    print(f"run log    source_rows={logged_source} rows_written={logged_written}\n")

    # 2. Fetch the object.
    obj = subprocess.run(["aws", "s3", "cp", f"s3://{BUCKET}/{s3_key}", "-"],
                         capture_output=True)
    if obj.returncode:
        sys.exit("could not download the object:\n" + obj.stderr.decode().strip())
    raw = gzip.decompress(obj.stdout) if s3_key.endswith(".gz") else obj.stdout
    f = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    fhdr, frows = f[0], f[1:]
    file_by_id = {}
    dupes = []
    ki = fhdr.index(key_col)
    for r in frows:
        if r[ki] in file_by_id:
            dupes.append(r[ki])
        file_by_id[r[ki]] = dict(zip(fhdr, r))

    # 3. Rebuild the expectation from the raw tables, independently.
    src_cols = [c for c in fhdr if c not in {j["as"] for j in joins}]
    select = ", ".join(
        (f"ST_AsText(r.{c}) AS {c}" if c in geom else f"r.{c}") for c in src_cols)
    _, srows = psql_csv(
        f"SELECT {select} FROM {SCHEMA}.{table} r "
        f"WHERE r.{ts_col} > '{lo}'::timestamp AND r.{ts_col} <= '{hi}'::timestamp")
    src_by_id = {r[src_cols.index(key_col)]: dict(zip(src_cols, r)) for r in srows}

    lookups = {}
    for j in joins:
        _, lr = psql_csv(f"SELECT {j['key']}::text, {j['label']}::text FROM {SCHEMA}.{j['table']}")
        lookups[j["column"]] = dict(lr)

    print("checks")
    check(len(frows) == len(srows), "row count matches the source",
          f"file={len(frows)} source={len(srows)}")
    check(str(len(frows)) == str(logged_written), "row count matches the run log",
          f"file={len(frows)} log={logged_written}")
    check(not dupes, "no duplicate request ids in the file",
          f"{len(dupes)} duplicated" if dupes else "")

    missing = set(src_by_id) - set(file_by_id)
    extra = set(file_by_id) - set(src_by_id)
    check(not missing, "every source row is present in the file",
          f"{len(missing)} missing, e.g. {sorted(missing)[:3]}" if missing else "")
    check(not extra, "the file invents no rows",
          f"{len(extra)} not in source, e.g. {sorted(extra)[:3]}" if extra else "")

    # 4. Field by field, every row, not a sample.
    bad_fields, bad_labels = [], []
    for rid, srow in src_by_id.items():
        frow = file_by_id.get(rid)
        if not frow:
            continue
        for c in src_cols:
            if norm(frow.get(c)) != norm(srow.get(c)):
                bad_fields.append((rid, c, srow.get(c), frow.get(c)))
        for j in joins:
            want = lookups[j["column"]].get(srow.get(j["column"]) or "", "")
            if norm(frow.get(j["as"])) != norm(want):
                bad_labels.append((rid, j["as"], want, frow.get(j["as"])))

    check(not bad_fields, "every source field matches, all rows and columns",
          f"{len(bad_fields)} mismatches, e.g. {bad_fields[:2]}" if bad_fields else
          f"{len(src_by_id) * len(src_cols)} values compared")
    check(not bad_labels, "every joined label matches its lookup table",
          f"{len(bad_labels)} wrong, e.g. {bad_labels[:2]}" if bad_labels else
          f"{len(src_by_id) * len(joins)} labels compared")

    # 5. A LEFT JOIN must not drop a row whose reference is null or broken.
    for j in joins:
        nulls = sum(1 for s in src_by_id.values() if not s.get(j["column"]))
        unmatched = sum(1 for s in src_by_id.values()
                        if s.get(j["column"]) and s[j["column"]] not in lookups[j["column"]])
        if nulls or unmatched:
            print(f"    note: {j['column']} has {nulls} null and {unmatched} "
                  f"unmatched values, all still present in the file")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("failed: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
