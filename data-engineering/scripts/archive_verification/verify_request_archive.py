"""Verify the requests archive in S3 against the source database (issue #586).

Runs seven checks and prints PASS, FAIL or SKIP for each:

  1. Row counts      every file holds exactly the source rows of its window
  2. No duplicates   no request version appears twice, within or across files
  3. No gaps         windows are contiguous and every source row in them was archived
  4. Joins resolve   status, type, priority, category, ... carry readable values
  5. Broken refs     requests with a null or missing referenced row are still archived
  6. Re-runs safe    running one window twice leaves one object with identical bytes
  7. UTC             timestamps and the watermark do not depend on the session time zone

SKIP means the input could not exercise the check (for example, no request in
the windows has a broken reference); it is never counted as a pass.

The script is independent of the Lambda it verifies: it does not import the
Lambda's mappings or queries, so a mistake there cannot also hide here. It only
reads. The database session is opened read only, and S3 is only listed and read.

Which window each file covers is not recorded in the file or its S3 key, so the
runs are given in a manifest (JSON), taken from the Lambda's responses:

    {"runs": [{"key": "requests_enriched/.../requests_enriched.csv",
               "watermark_start": "2026-11-09 10:00:00",
               "watermark_end": "2026-11-09 11:00:00"}]}

Usage, from data-engineering/:

    python scripts/archive_verification/verify_request_archive.py \\
        --dsn "$DATABASE_URL" --manifest runs.json \\
        --bucket <archive-bucket> --region us-east-1 \\
        --report-dir scripts/archive_verification/reports

Use --archive-dir instead of --bucket to read files already downloaded from S3
(the keys in the manifest are then paths relative to that folder).
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

DEFAULT_SCHEMA = "virginia_dev_saayam_rdbms"
REQUESTS_TABLE = "requests"
PRIMARY_KEY = "req_id"
WATERMARK_COLUMN = "last_updated_at"
TIMESTAMP_COLUMNS = ("submission_date", "serviced_date", "last_updated_at")
DEFAULT_OTHER_TIMEZONES = ("America/Phoenix", "Asia/Kolkata")
MAX_DETAIL_ITEMS = 10


@dataclass(frozen=True)
class Reference:
    """One id column of requests and the lookup table that resolves it.

    Defined here rather than imported from the Lambda, so the verifier states
    independently what each archived column should contain.
    """

    id_column: str
    readable_column: str
    lookup_table: str
    lookup_key: str
    lookup_value: str


REFERENCES: Tuple[Reference, ...] = (
    Reference("req_for_id", "req_for", "request_for", "req_for_id", "req_for"),
    Reference("req_islead_id", "req_islead", "request_isleadvol", "req_islead_id", "req_islead"),
    Reference("req_cat_id", "req_category", "help_categories", "cat_id", "cat_name"),
    Reference("req_type_id", "req_type", "request_types", "req_type_id", "req_type"),
    Reference("req_priority_id", "req_priority", "request_priorities", "req_priority_id", "req_priority"),
    Reference("req_status_id", "req_status", "request_statuses", "req_status_id", "req_status"),
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RUN_TS = re.compile(r"run_ts=(\d{8}T\d{6})Z")


# --------------------------------------------------------------------------- #
# Data passed between the readers and the checks
# --------------------------------------------------------------------------- #
@dataclass
class Run:
    """One archive run: the object it wrote and the window it covered."""

    key: str
    watermark_start: datetime
    watermark_end: datetime

    @property
    def window(self) -> Tuple[datetime, datetime]:
        return (self.watermark_start, self.watermark_end)


@dataclass
class ArchiveFile:
    """One archived CSV, parsed."""

    key: str
    raw: bytes
    columns: List[str]
    rows: List[Dict[str, str]]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()


@dataclass
class SourceWindow:
    """Source rows of one window, read at verification time."""

    rows: Dict[str, Dict[str, Any]]  # req_id -> row
    counts_by_timezone: Dict[str, int] = field(default_factory=dict)


@dataclass
class Evidence:
    """Everything the checks need, gathered before any check runs."""

    runs: List[Run]
    files: Dict[str, ArchiveFile]  # key -> file
    windows: Dict[Tuple[datetime, datetime], SourceWindow]
    current_versions: Dict[str, Optional[datetime]]  # req_id -> last_updated_at now
    lookups: Dict[str, Dict[str, str]]  # id_column -> {id: readable}
    timestamp_types: Dict[str, str]  # column -> data_type
    stored_keys: Optional[List[str]] = None  # every object under the prefix


@dataclass
class Result:
    """The outcome of one check, with what was compared and how."""

    number: int
    check: str
    status: str
    expected: str
    actual: str
    details: List[str] = field(default_factory=list)
    method: str = ""


def parse_timestamp(value: Any) -> datetime:
    """Parse a watermark as a naive timestamp, the type of the source column.

    A value carrying an offset is converted to UTC first, so '...Z' and
    '...+00:00' compare equal to the naive UTC value.
    """
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def render(value: Any) -> str:
    """Render a source value the way it should appear in the CSV."""
    return "" if value is None else str(value)


def _limit(items: Iterable[str]) -> List[str]:
    items = list(items)
    if len(items) > MAX_DETAIL_ITEMS:
        return items[:MAX_DETAIL_ITEMS] + [f"... and {len(items) - MAX_DETAIL_ITEMS} more"]
    return items


def _fmt(value: datetime) -> str:
    return value.isoformat(sep=" ")


def short_key(key: str) -> str:
    """The part of a key that tells runs apart (run_ts=... or window_...), else the key."""
    parts = [p for p in key.split("/") if p.startswith(("run_ts=", "window_start=", "window_end="))]
    return "/".join(parts) if parts else key


# --------------------------------------------------------------------------- #
# The seven checks. Pure functions of the evidence, so they can be tested
# without a database or S3.
# --------------------------------------------------------------------------- #
def check_row_counts(evidence: Evidence) -> Result:
    """1. Each file holds exactly the source rows of its window.

    The source keeps changing after an export: a request updated later moves out
    of the window it was archived in. Such a row is explained, not missing.
    """
    problems: List[str] = []
    notes: List[str] = []
    expected_total = actual_total = 0

    seen_runs = set()
    for run in evidence.runs:
        if (run.key, run.window) in seen_runs:
            continue  # the same object listed twice (a re-run that overwrote it)
        seen_runs.add((run.key, run.window))
        archive = evidence.files[run.key]
        source = evidence.windows[run.window].rows
        file_ids = [row[PRIMARY_KEY] for row in archive.rows]

        missing = sorted(set(source) - set(file_ids))
        explained, unexplained = [], []
        for request_id in sorted(set(file_ids) - set(source)):
            current = evidence.current_versions.get(request_id)
            if current is not None and current > run.watermark_end:
                explained.append(request_id)
            else:
                unexplained.append(request_id)

        expected = len(source) + len(explained)
        expected_total += expected
        actual_total += len(file_ids)
        label = f"{short_key(run.key)} ({_fmt(run.watermark_start)} .. {_fmt(run.watermark_end)}]"

        if missing or unexplained or expected != len(file_ids):
            problems.append(
                f"{label}: expected {expected} rows, file has {len(file_ids)}; "
                f"missing from file {missing[:MAX_DETAIL_ITEMS]}; "
                f"in file but not in source window {unexplained[:MAX_DETAIL_ITEMS]}"
            )
        if explained:
            notes.append(f"{label}: {len(explained)} row(s) updated after the export "
                         f"and now outside the window: {explained[:MAX_DETAIL_ITEMS]}")

    return Result(
        1, "Row counts match the source window",
        PASS if not problems else FAIL,
        f"{expected_total} rows across {len(seen_runs)} file(s)",
        f"{actual_total} rows",
        _limit(problems + notes),
        "SELECT req_id, last_updated_at FROM <schema>.requests "
        "WHERE last_updated_at > :start AND last_updated_at <= :end  -- per run; "
        "compared by req_id with the file's rows",
    )


def check_duplicates(evidence: Evidence, strict: bool = False) -> Result:
    """2. No request version appears twice, within one file or across files.

    The same req_id with a different last_updated_at is a later version of the
    request, archived again because the window follows last_updated_at. That is
    reported separately, and fails only with strict=True.
    """
    seen: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    versions: Dict[str, Set[str]] = defaultdict(set)

    for key, archive in evidence.files.items():
        for row in archive.rows:
            seen[(row[PRIMARY_KEY], row.get(WATERMARK_COLUMN, ""))].append(key)
            versions[row[PRIMARY_KEY]].add(row.get(WATERMARK_COLUMN, ""))

    duplicated = {version: keys for version, keys in seen.items() if len(keys) > 1}
    by_files: Dict[Tuple[str, ...], List[str]] = defaultdict(list)
    for (request_id, _updated), keys in sorted(duplicated.items()):
        by_files[tuple(short_key(k) for k in keys)].append(request_id)
    duplicates = [
        f"{len(ids)} request version(s) in {len(files)} files {list(files)}: {ids[:MAX_DETAIL_ITEMS]}"
        for files, ids in by_files.items()
    ]
    reexported = sorted(rid for rid, stamps in versions.items() if len(stamps) > 1)
    failed = bool(duplicates) or (strict and bool(reexported))

    details = list(duplicates)
    if reexported:
        details.append(
            f"{len(reexported)} request(s) archived again after an update "
            f"({'counted as failures, --strict-unique-requests' if strict else 'allowed: different versions'}): "
            f"{reexported[:MAX_DETAIL_ITEMS]}"
        )

    return Result(
        2, "No duplicate requests across files",
        FAIL if failed else PASS,
        "each (req_id, last_updated_at) in exactly one file",
        f"{len(duplicated)} duplicated version(s); {len(reexported)} request(s) re-archived after an update",
        _limit(details),
        "Read every file in the manifest; group rows by (req_id, last_updated_at)",
    )


def check_no_gaps(evidence: Evidence) -> Result:
    """3. Windows are contiguous and every source row inside them was archived."""
    windows = sorted({run.window for run in evidence.runs})
    if len(windows) < 2:
        return Result(3, "No gaps between runs", SKIP,
                      "at least two consecutive windows", f"{len(windows)} distinct window(s)",
                      ["Need two or more runs with different windows to test the boundary."],
                      "n/a")

    problems = []
    for previous, current in zip(windows, windows[1:]):
        if current[0] > previous[1]:
            problems.append(f"gap: nothing covers {_fmt(previous[1])} .. {_fmt(current[0])}")
        elif current[0] < previous[1]:
            problems.append(f"overlap: {_fmt(current[0])} .. {_fmt(previous[1])} covered twice")

    archived: Dict[Tuple[datetime, datetime], Set[Tuple[str, str]]] = defaultdict(set)
    for run in evidence.runs:
        for row in evidence.files[run.key].rows:
            archived[run.window].add((row[PRIMARY_KEY], row.get(WATERMARK_COLUMN, "")))

    missing = []
    checked = 0
    for window in windows:
        for request_id, row in evidence.windows[window].rows.items():
            checked += 1
            if (request_id, render(row[WATERMARK_COLUMN])) not in archived[window]:
                missing.append(f"{request_id} (last_updated_at {render(row[WATERMARK_COLUMN])}) "
                               f"not in the file for ({_fmt(window[0])} .. {_fmt(window[1])}]")
    problems.extend(missing)

    return Result(
        3, "No gaps between runs",
        PASS if not problems else FAIL,
        "contiguous windows; every source row in them archived in its own window",
        f"{len(windows)} windows, {checked} source rows checked, {len(problems)} problem(s)",
        _limit(problems),
        "Sort the manifest windows; each start must equal the previous end. Then every "
        "row from the per-window source query must be in that window's file at the same last_updated_at",
    )


def check_joins_resolve(evidence: Evidence) -> Result:
    """4. Each resolvable id carries its readable value from the lookup table."""
    problems = []
    resolved = 0
    columns = {ref.id_column for ref in REFERENCES} | {ref.readable_column for ref in REFERENCES}

    for key, archive in evidence.files.items():
        absent = sorted(columns - set(archive.columns))
        if absent:
            problems.append(f"{key}: missing columns {absent}")
            continue
        for row in archive.rows:
            for ref in REFERENCES:
                reference_id = row[ref.id_column]
                value = row[ref.readable_column]
                lookup = evidence.lookups.get(ref.id_column, {})
                if reference_id == "" or reference_id not in lookup:
                    continue  # null or broken: check 5
                resolved += 1
                if value != lookup[reference_id]:
                    problems.append(f"{row[PRIMARY_KEY]}.{ref.readable_column}: expected "
                                    f"{lookup[reference_id]!r}, got {value!r}")
                elif value == reference_id:
                    problems.append(f"{row[PRIMARY_KEY]}.{ref.readable_column}: still the id {value!r}")

    if not problems and resolved == 0:
        return Result(4, "Joins resolve to readable values", SKIP,
                      "at least one resolvable reference", "0 resolvable references in the files",
                      [], "n/a")

    return Result(
        4, "Joins resolve to readable values",
        PASS if not problems else FAIL,
        "every resolvable id paired with its lookup value",
        f"{resolved} references checked, {len(problems)} wrong",
        _limit(problems),
        "SELECT <key>, <value> FROM <schema>.<lookup>  -- for request_for, request_isleadvol, "
        "help_categories, request_types, request_priorities, request_statuses; "
        "compared with each file row's id and readable column",
    )


def check_broken_references(evidence: Evidence) -> Result:
    """5. Requests with a null or missing referenced row are archived, unchanged."""
    broken: Dict[str, List[str]] = {}
    in_window: Dict[str, Tuple[datetime, datetime]] = {}
    for window, source in evidence.windows.items():
        for request_id, row in source.rows.items():
            reasons = []
            for ref in REFERENCES:
                value = row.get(ref.id_column)
                if value is None:
                    reasons.append(f"{ref.id_column} is null")
                elif str(value) not in evidence.lookups.get(ref.id_column, {}):
                    reasons.append(f"{ref.id_column}={value} has no row in {ref.lookup_table}")
            if reasons:
                broken[request_id] = reasons
                in_window[request_id] = window

    if not broken:
        return Result(5, "Broken references survive", SKIP,
                      "at least one request with a null or missing reference",
                      "0 such requests in the windows checked",
                      ["Nothing to test in this data. Run against the local copy "
                       "(run_local_harness.py), which seeds such requests."],
                      "n/a")

    rows_by_window: Dict[Tuple[datetime, datetime], Dict[str, Dict[str, str]]] = defaultdict(dict)
    for run in evidence.runs:
        for row in evidence.files[run.key].rows:
            rows_by_window[run.window][row[PRIMARY_KEY]] = row

    problems = []
    for request_id, reasons in sorted(broken.items()):
        row = rows_by_window[in_window[request_id]].get(request_id)
        if row is None:
            problems.append(f"{request_id} DROPPED ({'; '.join(reasons)})")
            continue
        for ref in REFERENCES:
            source_value = evidence.windows[in_window[request_id]].rows[request_id].get(ref.id_column)
            if row[ref.id_column] != render(source_value):
                problems.append(f"{request_id}.{ref.id_column}: expected {render(source_value)!r}, "
                                f"got {row[ref.id_column]!r}")
            if render(source_value) not in evidence.lookups.get(ref.id_column, {}) and row[ref.readable_column]:
                problems.append(f"{request_id}.{ref.readable_column}: should be empty, "
                                f"got {row[ref.readable_column]!r}")

    return Result(
        5, "Broken references survive",
        PASS if not problems else FAIL,
        f"all {len(broken)} request(s) with a null/missing reference archived with the id kept and an empty value",
        f"{len(broken) - sum('DROPPED' in p for p in problems)}/{len(broken)} archived; {len(problems)} problem(s)",
        _limit(problems + [f"{rid}: {'; '.join(r)}" for rid, r in sorted(broken.items())]),
        "Source window rows whose id is NULL or absent from the lookup table (computed in Python "
        "from the window query and the lookup queries, not with a SQL join); each must be in the file",
    )


def check_reruns(evidence: Evidence) -> Result:
    """6. Running one window twice leaves one object with the same bytes."""
    by_window: Dict[Tuple[datetime, datetime], List[Run]] = defaultdict(list)
    for run in evidence.runs:
        by_window[run.window].append(run)
    reruns = {window: runs for window, runs in by_window.items() if len(runs) > 1}

    if not reruns:
        return Result(6, "Re-runs are safe", SKIP,
                      "a window run at least twice", "no window repeated in the manifest",
                      ["Re-run one window (same watermark_start and watermark_end) and add both runs "
                       "to the manifest. This needs permission to invoke the Lambda."],
                      "n/a")

    problems, details = [], []
    for window, runs in sorted(reruns.items()):
        keys = sorted({run.key for run in runs})
        hashes = {evidence.files[key].sha256 for key in keys}
        label = f"({_fmt(window[0])} .. {_fmt(window[1])}] run {len(runs)} times"
        if len(keys) > 1:
            problems.append(f"{label}: {len(keys)} objects instead of 1: {[short_key(k) for k in keys]}")
        details.append(f"{label}: content {'identical' if len(hashes) == 1 else 'DIFFERENT'} "
                       f"(sha256 {sorted(h[:12] for h in hashes)})")
        if len(hashes) > 1:
            problems.append(f"{label}: the files differ")

    if evidence.stored_keys is not None:
        details.append(f"{len(evidence.stored_keys)} object(s) under the prefix")

    return Result(
        6, "Re-runs are safe",
        PASS if not problems else FAIL,
        "one object per window, same bytes on every run",
        f"{len(reruns)} re-run window(s), {len(problems)} problem(s)",
        _limit(problems + details),
        "Group manifest runs by window; count distinct keys and compare SHA-256 of their contents",
    )


def check_utc(evidence: Evidence, tolerance_minutes: float = 10.0) -> Result:
    """7. Timestamps and watermarks are UTC whatever the session time zone."""
    problems, details = [], []

    for column in TIMESTAMP_COLUMNS:
        data_type = evidence.timestamp_types.get(column)
        if data_type is None:
            problems.append(f"requests.{column}: not found in information_schema")
        elif data_type != "timestamp without time zone":
            problems.append(f"requests.{column} is {data_type!r}: a session time zone would shift it")
    details.append(f"column types: {evidence.timestamp_types}")

    for window, source in sorted(evidence.windows.items()):
        counts = source.counts_by_timezone
        if len(set(counts.values())) > 1:
            problems.append(f"({_fmt(window[0])} .. {_fmt(window[1])}] selects different rows by "
                            f"session time zone: {counts}")
    details.append("window counts by session time zone: " + "; ".join(
        f"({_fmt(w[0])} .. {_fmt(w[1])}] {s.counts_by_timezone}" for w, s in sorted(evidence.windows.items())))

    compared = 0
    for run in evidence.runs:
        source = evidence.windows[run.window].rows
        for row in evidence.files[run.key].rows:
            stamp = row.get(WATERMARK_COLUMN, "")
            try:
                updated = parse_timestamp(stamp)
            except ValueError:
                problems.append(f"{run.key}: {row[PRIMARY_KEY]}.last_updated_at {stamp!r} is not a timestamp")
                continue
            if not run.watermark_start < updated <= run.watermark_end:
                problems.append(f"{row[PRIMARY_KEY]}: last_updated_at {stamp} outside its window "
                                f"({_fmt(run.watermark_start)} .. {_fmt(run.watermark_end)}]")
            source_row = source.get(row[PRIMARY_KEY])
            if source_row is None:
                continue  # updated since; nothing current to compare
            for column in TIMESTAMP_COLUMNS:
                compared += 1
                if row.get(column, "") != render(source_row.get(column)):
                    problems.append(f"{row[PRIMARY_KEY]}.{column}: file {row.get(column)!r}, "
                                    f"source (UTC session) {render(source_row.get(column))!r}")
    details.append(f"{compared} exported timestamp values compared with the source")

    checked_keys = 0
    for run in evidence.runs:
        match = _RUN_TS.search(run.key)
        if not match:
            continue
        checked_keys += 1
        run_ts = datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")
        drift = abs((run_ts - run.watermark_end).total_seconds()) / 60
        if drift > tolerance_minutes and run.watermark_end > run_ts:
            problems.append(f"{short_key(run.key)}: watermark_end {_fmt(run.watermark_end)} is after the UTC run "
                            f"time {_fmt(run_ts)} by {drift:.0f} min: not UTC")
    if checked_keys:
        details.append(f"{checked_keys} watermark_end value(s) compared with the UTC run_ts in the key")

    return Result(
        7, "Timestamps are UTC",
        PASS if not problems else FAIL,
        "timestamp without time zone; same rows under every session time zone; exported values equal the source",
        f"{len(problems)} problem(s)",
        _limit(problems + details),
        "information_schema.columns for requests; the window count repeated after "
        "set_config('TimeZone', <tz>, true) for UTC and each --other-timezones value; "
        "file timestamps compared as text with the source read in a UTC session; "
        "watermark_end must not be later than the UTC run_ts in the key (a window ending in "
        "the future means a local clock east of UTC was used)",
    )


def run_checks(evidence: Evidence, strict: bool = False,
               tolerance_minutes: float = 10.0) -> List[Result]:
    """Run all seven checks in order."""
    return [
        check_row_counts(evidence),
        check_duplicates(evidence, strict=strict),
        check_no_gaps(evidence),
        check_joins_resolve(evidence),
        check_broken_references(evidence),
        check_reruns(evidence),
        check_utc(evidence, tolerance_minutes=tolerance_minutes),
    ]


# --------------------------------------------------------------------------- #
# Reading the archive and the source
# --------------------------------------------------------------------------- #
def parse_archive(key: str, raw: bytes) -> ArchiveFile:
    """Parse one archived CSV. A BOM is tolerated; a missing req_id column is not."""
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    columns = list(reader.fieldnames or [])
    if PRIMARY_KEY not in columns:
        raise ValueError(f"{key}: no {PRIMARY_KEY} column")
    return ArchiveFile(key=key, raw=raw, columns=columns, rows=list(reader))


class LocalStore:
    """Archive files already downloaded to a folder; keys are relative paths."""

    def __init__(self, root: str):
        self.root = Path(root)

    def read(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def list_keys(self, prefix: str = "") -> List[str]:
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")
                      if p.is_file() and str(p.relative_to(self.root)).startswith(prefix))


class S3Store:
    """Archive files in S3. Only lists and reads."""

    def __init__(self, bucket: str, region: Optional[str] = None,
                 endpoint_url: Optional[str] = None, client: Any = None):
        if client is None:
            import boto3  # Only needed when reading from S3.

            client = boto3.client("s3", region_name=region, endpoint_url=endpoint_url)
        self.bucket = bucket
        self.client = client

    def read(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def list_keys(self, prefix: str = "") -> List[str]:
        keys: List[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)


class SourceReader:
    """Read-only access to the source tables."""

    def __init__(self, connection: Any, schema: Optional[str] = DEFAULT_SCHEMA):
        if schema and not _IDENTIFIER.match(schema):
            raise ValueError(f"invalid schema name {schema!r}")
        self.connection = connection
        self.schema = schema

    def table(self, name: str) -> str:
        return f"{self.schema}.{name}" if self.schema else name

    def _query(self, sql: str, params: Sequence[Any] = (), timezone_name: str = "UTC") -> List[tuple]:
        cursor = self.connection.cursor()
        try:
            cursor.execute("SELECT set_config('TimeZone', %s, true)", (timezone_name,))
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            columns = [d[0] for d in cursor.description]
        finally:
            cursor.close()
            self.connection.rollback()  # read only: end the transaction, keep nothing
        return [dict(zip(columns, row)) for row in rows]

    def window_rows(self, start: datetime, end: datetime) -> Dict[str, Dict[str, Any]]:
        columns = ", ".join([PRIMARY_KEY, *TIMESTAMP_COLUMNS, *(r.id_column for r in REFERENCES)])
        rows = self._query(
            f"SELECT {columns} FROM {self.table(REQUESTS_TABLE)} "
            f"WHERE {WATERMARK_COLUMN} > %s AND {WATERMARK_COLUMN} <= %s",
            (start, end),
        )
        return {str(row[PRIMARY_KEY]): row for row in rows}

    def window_count(self, start: datetime, end: datetime, timezone_name: str) -> int:
        rows = self._query(
            f"SELECT count(*) AS n FROM {self.table(REQUESTS_TABLE)} "
            f"WHERE {WATERMARK_COLUMN} > %s AND {WATERMARK_COLUMN} <= %s",
            (start, end), timezone_name,
        )
        return int(rows[0]["n"])

    def current_versions(self, request_ids: Iterable[str]) -> Dict[str, Optional[datetime]]:
        ids = sorted(set(request_ids))
        found = {str(row[PRIMARY_KEY]): row[WATERMARK_COLUMN] for row in self._query(
            f"SELECT {PRIMARY_KEY}, {WATERMARK_COLUMN} FROM {self.table(REQUESTS_TABLE)} "
            f"WHERE {PRIMARY_KEY} = ANY(%s)", (ids,))} if ids else {}
        return {request_id: found.get(request_id) for request_id in ids}

    def lookups(self) -> Dict[str, Dict[str, str]]:
        result = {}
        for ref in REFERENCES:
            rows = self._query(f"SELECT {ref.lookup_key} AS k, {ref.lookup_value} AS v "
                               f"FROM {self.table(ref.lookup_table)}")
            result[ref.id_column] = {render(row["k"]): render(row["v"]) for row in rows}
        return result

    def timestamp_types(self) -> Dict[str, str]:
        rows = self._query(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = coalesce(%s, current_schema()) AND table_name = %s "
            "AND column_name = ANY(%s)",
            (self.schema, REQUESTS_TABLE, list(TIMESTAMP_COLUMNS)),
        )
        return {row["column_name"]: row["data_type"] for row in rows}


def load_manifest(path: str) -> List[Run]:
    """Read the runs to verify from a manifest file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    runs = data["runs"] if isinstance(data, dict) else data
    return [Run(key=item["key"], watermark_start=parse_timestamp(item["watermark_start"]),
                watermark_end=parse_timestamp(item["watermark_end"])) for item in runs]


def gather_evidence(runs: List[Run], store: Any, source: SourceReader,
                    other_timezones: Sequence[str] = DEFAULT_OTHER_TIMEZONES,
                    list_prefix: Optional[str] = None) -> Evidence:
    """Read every file and source window the checks need."""
    files = {key: parse_archive(key, store.read(key)) for key in sorted({run.key for run in runs})}

    windows: Dict[Tuple[datetime, datetime], SourceWindow] = {}
    for window in sorted({run.window for run in runs}):
        counts = {tz: source.window_count(*window, tz) for tz in ("UTC", *other_timezones)}
        windows[window] = SourceWindow(rows=source.window_rows(*window), counts_by_timezone=counts)

    archived_ids = {row[PRIMARY_KEY] for f in files.values() for row in f.rows}
    stored_keys = store.list_keys(list_prefix) if list_prefix is not None else None

    return Evidence(
        runs=runs, files=files, windows=windows,
        current_versions=source.current_versions(archived_ids),
        lookups=source.lookups(), timestamp_types=source.timestamp_types(),
        stored_keys=stored_keys,
    )


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def print_report(results: List[Result], seconds: float, out: Any = sys.stdout) -> None:
    print("\nREQUEST ARCHIVE VERIFICATION (issue #586)", file=out)
    print("=" * 60, file=out)
    for result in results:
        print(f"\n[{result.status}] {result.number}. {result.check}", file=out)
        print(f"  Expected: {result.expected}", file=out)
        print(f"  Actual:   {result.actual}", file=out)
        for line in result.details:
            print(f"    - {line}", file=out)
    counts = {status: sum(r.status == status for r in results) for status in (PASS, FAIL, SKIP)}
    print("\n" + "=" * 60, file=out)
    print(f"PASS {counts[PASS]}  FAIL {counts[FAIL]}  SKIP {counts[SKIP]}   "
          f"end-to-end {seconds:.2f} s", file=out)


def write_reports(results: List[Result], seconds: float, report_dir: str,
                  context: Dict[str, Any]) -> Tuple[Path, Path]:
    """Write the results as JSON and as Markdown for the issue."""
    folder = Path(report_dir)
    folder.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")

    json_path = folder / "verification_report.json"
    json_path.write_text(json.dumps({
        "issue": 586, "generated_at_utc": generated, "end_to_end_seconds": round(seconds, 3),
        "context": context, "results": [asdict(r) for r in results],
    }, indent=2, default=str), encoding="utf-8")

    lines = [f"# Requests archive verification (#586)", "",
             f"Generated {generated}. End-to-end run time: **{seconds:.2f} s**.", ""]
    lines += [f"- {k}: `{v}`" for k, v in context.items()]
    lines += ["", "| # | Check | Result | Expected | Actual |", "|---|---|---|---|---|"]
    lines += [f"| {r.number} | {r.check} | **{r.status}** | {r.expected} | {r.actual} |" for r in results]
    for r in results:
        lines += ["", f"## {r.number}. {r.check}: {r.status}", "", f"Method: {r.method}", ""]
        lines += [f"- {d}" for d in r.details]
    md_path = folder / "verification_report.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def verify(runs: List[Run], store: Any, source: SourceReader, strict: bool = False,
           other_timezones: Sequence[str] = DEFAULT_OTHER_TIMEZONES,
           tolerance_minutes: float = 10.0, list_prefix: Optional[str] = None,
           report_dir: Optional[str] = None, context: Optional[Dict[str, Any]] = None,
           out: Any = sys.stdout) -> Tuple[List[Result], float]:
    """Gather evidence, run the checks, print and optionally save the report."""
    started = time.perf_counter()
    evidence = gather_evidence(runs, store, source, other_timezones, list_prefix)
    results = run_checks(evidence, strict=strict, tolerance_minutes=tolerance_minutes)
    seconds = time.perf_counter() - started
    print_report(results, seconds, out)
    if report_dir:
        write_reports(results, seconds, report_dir, context or {})
    return results, seconds


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL"),
                        help="libpq connection string (default: $DATABASE_URL)")
    parser.add_argument("--schema", default=DEFAULT_SCHEMA)
    parser.add_argument("--manifest", required=True, help="JSON list of runs (key, watermark_start, watermark_end)")
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--bucket", help="S3 bucket holding the archive")
    where.add_argument("--archive-dir", help="folder of archive files downloaded from S3")
    parser.add_argument("--region")
    parser.add_argument("--endpoint-url", help="S3-compatible endpoint, e.g. a local MinIO")
    parser.add_argument("--list-prefix", help="also count every object under this prefix")
    parser.add_argument("--other-timezones", default=",".join(DEFAULT_OTHER_TIMEZONES))
    parser.add_argument("--strict-unique-requests", action="store_true",
                        help="fail check 2 when an updated request is archived again")
    parser.add_argument("--run-ts-tolerance-minutes", type=float, default=10.0)
    parser.add_argument("--report-dir")
    args = parser.parse_args(argv)

    if not args.dsn:
        parser.error("--dsn or DATABASE_URL is required")

    import psycopg2  # Only needed here, so the checks can be imported without it.

    connection = psycopg2.connect(args.dsn)
    connection.set_session(readonly=True)
    try:
        store = (S3Store(args.bucket, args.region, args.endpoint_url) if args.bucket
                 else LocalStore(args.archive_dir))
        results, _ = verify(
            load_manifest(args.manifest), store, SourceReader(connection, args.schema),
            strict=args.strict_unique_requests,
            other_timezones=[tz for tz in args.other_timezones.split(",") if tz],
            tolerance_minutes=args.run_ts_tolerance_minutes, list_prefix=args.list_prefix,
            report_dir=args.report_dir,
            context={"schema": args.schema, "archive": args.bucket or args.archive_dir,
                     "manifest": args.manifest},
        )
    finally:
        connection.close()

    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
