"""The seven checks from issue #586.

Each check builds its own fixture, runs the extract under test, writes the
result to the archive, reads it back, and compares it against the source. They
are numbered as the issue numbers them so a result can be read against it line
by line.

The window is half-open, ``[low, high)``, everywhere, and the watermark advances
to the window's upper bound rather than to ``max(last_updated_at)`` of the rows
returned. Both facts are load-bearing: real rows share ``last_updated_at`` to
the microsecond, and taking the max loses or re-reads every row on a boundary.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from . import fixture
from .adapters import Archive, Extractor, Source, format_timestamp, parse_timestamp

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

ALL_DIGITS = re.compile(r"^\d+$")

#: Readable column -> (lookup table, lookup column). Check 4 asserts each
#: readable column carries words from its lookup rather than identifiers.
READABLE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("cat_name", "help_categories", "cat_name"),
    ("req_for", "request_for", "req_for"),
    ("req_islead", "request_isleadvol", "req_islead"),
    ("req_type", "request_types", "req_type"),
    ("req_priority", "request_priorities", "req_priority"),
    ("req_status", "request_statuses", "req_status"),
)


@dataclass
class CheckResult:
    """The outcome of one check."""

    number: str
    name: str
    status: str
    detail: str = ""
    expected: str = ""
    actual: str = ""
    command: str = ""
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


def read_csv_rows(payload: str) -> tuple[list[str], list[dict[str, str]]]:
    """Parse an archive file into a header and a list of row dicts.

    Parsed with ``csv.reader``, never by counting lines. ``req_subj`` and
    ``req_desc`` are free text that can contain newlines, so a line count
    overstates the rows - and the fixture carries exactly such a row to make
    that mistake fail loudly instead of quietly.
    """
    reader = csv.reader(io.StringIO(payload, newline=""))
    rows = list(reader)
    if not rows:
        return [], []
    header = rows[0]
    return header, [dict(zip(header, row)) for row in rows[1:]]


def _run_window(
    source: Source,
    extract: Extractor,
    archive: Archive,
    low: datetime,
    high: datetime,
):
    """Run the extract over one window and store the result in the archive."""
    result = extract(source, low, high)
    archive.write(result.key, result.csv_text)
    return result


# ------------------------------------------------------------------- check 1


def check_row_counts(extract: Extractor, archive: Archive) -> CheckResult:
    """1. The file's row count matches the source for the same window."""
    source, facts = fixture.build()
    try:
        result = _run_window(source, extract, archive, facts.low, facts.middle)
        _, rows = read_csv_rows(archive.read(result.key))
        expected = fixture.count_in_window(source, facts.low, facts.middle)
        actual = len(rows)

        # The same count taken the naive way, reported so the report shows what
        # the trap costs rather than just asserting it was avoided.
        line_count = len(archive.read(result.key).splitlines()) - 1
        notes = []
        if line_count != actual:
            notes.append(
                f"counting lines instead of parsing CSV gives {line_count}, "
                f"not {actual} - free text in req_desc contains newlines"
            )

        return CheckResult(
            number="1",
            name="Row counts match the source",
            status=PASS if expected == actual else FAIL,
            detail=f"window [{facts.low}, {facts.middle})",
            expected=f"{expected} rows (SELECT count(*) FROM requests)",
            actual=f"{actual} rows parsed from {result.key}",
            command=(
                "SELECT count(*) FROM requests "
                "WHERE last_updated_at >= low AND last_updated_at < high"
            ),
            notes=notes,
        )
    finally:
        source.close()


# ------------------------------------------------------------------- check 2


def check_no_duplicates(extract: Extractor, archive: Archive) -> CheckResult:
    """2. No request appears twice in one file, nor twice at the same version.

    The unique key across files is ``(req_id, last_updated_at)``, not
    ``req_id``. Epic #416: "last_updated_at moves on update as well as insert,
    so a status change on an already-archived request gets re-archived with its
    new value." A repeated ``req_id`` across two files is therefore correct
    behaviour, and a check keyed on ``req_id`` alone would fail on it. This
    check deliberately creates that situation.
    """
    source, facts = fixture.build()
    try:
        first = _run_window(source, extract, archive, facts.low, facts.middle)

        # A request archived in the first window is updated, moving it into the
        # second. It must legitimately appear in both files.
        fixture.move_into_later_window(
            source, "REQ-A-001", facts.middle + timedelta(hours=1)
        )
        second = _run_window(source, extract, archive, facts.middle, facts.high)

        within: list[str] = []
        pairs: list[tuple[str, str]] = []
        for result in (first, second):
            _, rows = read_csv_rows(archive.read(result.key))
            ids = [row["req_id"] for row in rows]
            if len(ids) != len(set(ids)):
                within.append(result.key)
            pairs.extend((row["req_id"], row["last_updated_at"]) for row in rows)

        duplicate_pairs = len(pairs) - len(set(pairs))
        id_counts = Counter(req_id for req_id, _ in pairs)
        repeated_ids = sorted(req_id for req_id, count in id_counts.items() if count > 1)
        failed = bool(within) or duplicate_pairs > 0

        notes = []
        if repeated_ids:
            notes.append(
                f"req_id repeated across files, correctly: {', '.join(repeated_ids)} "
                "- re-archived after an update, each with a different "
                "last_updated_at (#416)"
            )

        return CheckResult(
            number="2",
            name="No duplicates",
            status=FAIL if failed else PASS,
            detail=(
                f"{len(pairs)} rows across {len([first, second])} files; "
                "unique key is (req_id, last_updated_at)"
            ),
            expected="0 duplicate (req_id, last_updated_at); 0 repeated req_id within a file",
            actual=(
                f"{duplicate_pairs} duplicate pairs; "
                f"files with a repeated req_id: {within or 'none'}"
            ),
            command="compare (req_id, last_updated_at) across every archive file",
            notes=notes,
        )
    finally:
        source.close()


# ------------------------------------------------------------------- check 3


def check_no_gaps(extract: Extractor, archive: Archive) -> CheckResult:
    """3. A request between two runs lands in exactly one of them.

    Nothing is changed between the two runs here, so every row belongs to
    exactly one window. The three rows sitting exactly on the boundary are the
    interesting ones: half-open windows put them in the second run only.
    """
    source, facts = fixture.build()
    try:
        first = _run_window(source, extract, archive, facts.low, facts.middle)
        second = _run_window(source, extract, archive, facts.middle, facts.high)

        _, first_rows = read_csv_rows(archive.read(first.key))
        _, second_rows = read_csv_rows(archive.read(second.key))
        first_ids = {row["req_id"] for row in first_rows}
        second_ids = {row["req_id"] for row in second_rows}

        _, source_rows = source.query(
            "SELECT req_id FROM requests "
            "WHERE last_updated_at >= ? AND last_updated_at < ?",
            [format_timestamp(facts.low), format_timestamp(facts.high)],
        )
        source_ids = {row[0] for row in source_rows}

        missing = sorted(source_ids - (first_ids | second_ids))
        both = sorted(first_ids & second_ids)
        boundary_in_first = sorted(set(facts.boundary_tie) & first_ids)
        boundary_in_second = sorted(set(facts.boundary_tie) & second_ids)

        watermark_ok = first.watermark == facts.middle
        failed = bool(missing or both or boundary_in_first) or not watermark_ok
        if sorted(boundary_in_second) != sorted(facts.boundary_tie):
            failed = True

        return CheckResult(
            number="3",
            name="No gaps across the window boundary",
            status=FAIL if failed else PASS,
            detail=(
                f"{len(facts.boundary_tie)} rows share last_updated_at "
                f"== {facts.middle} to the microsecond"
            ),
            expected=(
                f"0 missing, 0 in both runs, boundary ties only in run 2, "
                f"watermark == {facts.middle}"
            ),
            actual=(
                f"missing={missing or 'none'}, in_both={both or 'none'}, "
                f"boundary_in_run1={boundary_in_first or 'none'}, "
                f"boundary_in_run2={boundary_in_second}, "
                f"watermark={first.watermark}"
            ),
            command="run [t0,t1) then [t1,t2) and compare against the source set",
        )
    finally:
        source.close()


# ------------------------------------------------------------------- check 4


def check_joins_resolve(extract: Extractor, archive: Archive) -> CheckResult:
    """4. Status, type, priority and category arrive as words, not identifiers."""
    source, facts = fixture.build()
    try:
        result = _run_window(source, extract, archive, facts.low, facts.middle)
        header, rows = read_csv_rows(archive.read(result.key))

        problems: list[str] = []
        resolved: list[str] = []
        for column, table, lookup_column in READABLE_COLUMNS:
            if column not in header:
                problems.append(f"{column} is missing from the export")
                continue
            permitted = fixture.lookup_values(source, table, lookup_column)
            values = {row[column] for row in rows if row[column] != ""}
            numeric = {value for value in values if ALL_DIGITS.match(value)}
            unknown = values - permitted
            if numeric:
                problems.append(f"{column} holds identifiers: {sorted(numeric)[:3]}")
            if unknown:
                problems.append(f"{column} holds values absent from {table}: {sorted(unknown)[:3]}")
            resolved.append(f"{column}={len(values)} distinct")

        return CheckResult(
            number="4",
            name="Joins resolve to readable words",
            status=FAIL if problems else PASS,
            detail=", ".join(resolved),
            expected="every readable column holds words drawn from its lookup table",
            actual="; ".join(problems) if problems else "all six readable columns resolve",
            command="compare each readable column against SELECT <col> FROM <lookup>",
        )
    finally:
        source.close()


# ------------------------------------------------------------------- check 5


def check_broken_references_survive(extract: Extractor, archive: Archive) -> CheckResult:
    """5. A request whose reference is missing or null still appears.

    The failure #586 most wants ruled out, because an inner join drops the row
    silently and the count merely looks small. Two sub-cases:

    * **5a** a null reference, which is the case that actually occurs: in dev,
      ``lead_volunteer_id`` is null in 218 of 221 requests.
    * **5b** a non-null reference pointing at nothing. ``req_cat_id`` is
      ``NOT NULL`` and foreign-key constrained, so production cannot reach this
      state by any ordinary write and the fixture had to disable enforcement to
      create it. It guards against a constraint being dropped or a load running
      with constraints off.
    """
    source, facts = fixture.build()
    try:
        result = _run_window(source, extract, archive, facts.low, facts.middle)
        header, rows = read_csv_rows(archive.read(result.key))
        by_id = {row["req_id"]: row for row in rows}

        problems: list[str] = []

        for req_id in facts.null_lead_volunteer:
            if req_id not in by_id:
                problems.append(f"5a: {req_id} (null lead_volunteer_id) was dropped")
        for req_id in facts.null_beneficiary:
            if req_id not in by_id:
                problems.append(f"5a: {req_id} (null beneficiary_id) was dropped")

        for req_id in facts.dangling_category:
            row = by_id.get(req_id)
            if row is None:
                problems.append(f"5b: {req_id} (category points at nothing) was dropped")
                continue
            if row.get("req_cat_id") != fixture.DANGLING_CATEGORY:
                problems.append(f"5b: {req_id} lost its original req_cat_id")
            if row.get("cat_name", "") != "":
                problems.append(
                    f"5b: {req_id} resolved cat_name to {row['cat_name']!r}, "
                    "but the category does not exist"
                )

        source_total = fixture.count_in_window(source, facts.low, facts.middle)
        inner_join_would_give = len(
            [
                row
                for row in rows
                if row.get("lead_volunteer_user_id", "") != ""
                and row.get("cat_name", "") != ""
            ]
        )

        return CheckResult(
            number="5",
            name="Broken references survive",
            status=FAIL if problems else PASS,
            detail=(
                f"{len(facts.null_lead_volunteer)} null lead_volunteer_id, "
                f"{len(facts.null_beneficiary)} null beneficiary_id, "
                f"{len(facts.dangling_category)} dangling req_cat_id"
            ),
            expected=f"{source_total} rows exported, every broken reference retained",
            actual=(
                f"{len(rows)} rows exported; an inner join would have returned "
                f"{inner_join_would_give}"
                + ("; " + "; ".join(problems) if problems else "")
            ),
            command="assert each deliberately-broken req_id is present in the export",
            notes=[
                "5b required disabling foreign key enforcement to insert the row: "
                "req_cat_id is NOT NULL and FK-constrained, so a faithful copy of "
                "the schema rejects it. Production cannot reach this state by an "
                "ordinary write; the check guards a dropped constraint or a "
                "constraint-disabled load.",
            ],
        )
    finally:
        source.close()


# ------------------------------------------------------------------- check 6


def check_reruns_are_safe(extract: Extractor, archive: Archive) -> CheckResult:
    """6. Running the same window twice produces one identical file.

    Three separate properties, reported separately so a diagnosis is possible:
    the same content, the same bytes, and the same archive key. "Content equal,
    bytes differ" means the extract has no ``ORDER BY`` - worth distinguishing
    from data loss, which looks nothing alike but would otherwise report the
    same way. An unstable key means a re-run adds a second copy instead of
    replacing the first, which check 2 would then see as a duplicate.
    """
    source, facts = fixture.build()
    try:
        first = _run_window(source, extract, archive, facts.low, facts.middle)
        first_bytes = archive.read(first.key)
        # Snapshot after the first run, not before it: other checks write the
        # same window to this archive, so the question is only whether the
        # *second* run of a window adds anything.
        after_first = set(archive.keys())
        second = _run_window(source, extract, archive, facts.low, facts.middle)
        second_bytes = archive.read(second.key)
        added = sorted(set(archive.keys()) - after_first)

        _, first_rows = read_csv_rows(first_bytes)
        _, second_rows = read_csv_rows(second_bytes)
        content_equal = sorted(map(repr, first_rows)) == sorted(map(repr, second_rows))
        bytes_equal = first_bytes == second_bytes
        key_stable = first.key == second.key
        no_second_copy = added == []

        problems = []
        if not content_equal:
            problems.append("the two runs returned different rows")
        if content_equal and not bytes_equal:
            problems.append("same rows, different bytes - the extract has no ORDER BY")
        if not key_stable:
            problems.append(f"archive key changed between runs: {first.key} -> {second.key}")
        if not no_second_copy:
            problems.append(f"the re-run wrote {len(added)} extra file(s): {added}")

        return CheckResult(
            number="6",
            name="Re-runs are safe",
            status=FAIL if problems else PASS,
            detail=f"window [{facts.low}, {facts.middle}) run twice",
            expected="identical content, identical bytes, one stable archive key",
            actual=(
                f"content_equal={content_equal}, bytes_equal={bytes_equal}, "
                f"key_stable={key_stable}, extra_files_from_rerun={len(added)}"
            ),
            command="run the same window twice and compare the stored file",
            notes=problems,
        )
    finally:
        source.close()


# ------------------------------------------------------------------ check 7


def check_timestamps_utc(extract: Extractor, archive: Archive) -> CheckResult:
    """7a. Exported timestamps and the watermark do not follow the local clock.

    Every column in this schema is ``timestamp without time zone``, holding UTC
    by convention with nothing enforcing it. This half asserts the harness and
    the extract keep that convention: exported values are naive and canonical,
    and the watermark is the window bound rather than anything read from a
    clock. It catches ``datetime.now()`` used where
    ``datetime.now(timezone.utc)`` is required, which is the mistake that
    shifts a window by the local offset.

    It does **not** cover the Postgres session time zone. See
    ``check_session_time_zone`` for that half, which only a Postgres source can
    answer.
    """
    source, facts = fixture.build()
    try:
        result = _run_window(source, extract, archive, facts.low, facts.middle)
        _, rows = read_csv_rows(archive.read(result.key))

        problems: list[str] = []
        for column in ("last_updated_at", "submission_date"):
            for row in rows:
                value = row.get(column, "")
                if value == "":
                    continue
                try:
                    parsed = parse_timestamp(value)
                except ValueError:
                    problems.append(f"{column}={value!r} is not canonical UTC-naive form")
                    break
                if parsed.tzinfo is not None:
                    problems.append(f"{column}={value!r} carries an offset")
                    break

        if result.watermark != facts.middle:
            problems.append(
                f"watermark is {result.watermark}, not the window bound {facts.middle}"
            )
        if result.watermark.tzinfo is not None:
            problems.append("watermark is tz-aware; this schema stores naive UTC")

        # A watermark taken from the local clock would drift from UTC by this
        # much. Reported as evidence rather than asserted, since the offset is
        # whatever the machine running this happens to use - and a machine
        # already set to UTC could not reveal the bug at all.
        offset = datetime.now(timezone.utc).astimezone().utcoffset() or timedelta(0)
        total_minutes = int(offset.total_seconds() // 60)
        local_offset = (
            f"{'-' if total_minutes < 0 else '+'}"
            f"{abs(total_minutes) // 60:02d}:{abs(total_minutes) % 60:02d}"
        )

        return CheckResult(
            number="7a",
            name="Timestamps are UTC (clock independence)",
            status=FAIL if problems else PASS,
            detail=f"{len(rows)} rows checked; this machine's local offset is UTC{local_offset}",
            expected="canonical naive-UTC values; watermark == the window's upper bound",
            actual="; ".join(problems) if problems else "all timestamps canonical and naive",
            command="parse every exported timestamp and compare the watermark",
        )
    finally:
        source.close()


def check_session_time_zone(
    extract: Extractor, archive: Archive, source_factory: Optional[Callable[[], Source]]
) -> CheckResult:
    """7b. The extract is unaffected by a non-UTC session time zone.

    #586: "The watermark and the exported timestamps are in UTC regardless of
    the session time zone. Every timestamp column in this schema is `timestamp
    without time zone`, so a wrong session time zone shifts the extraction
    window silently."

    A session time zone is a Postgres concept. SQLite has none, so against the
    local copy this reports SKIP rather than PASS - the acceptance criterion
    stays visibly outstanding instead of being quietly ticked by a test that
    could not have failed.

    ``Asia/Kolkata`` is deliberate: its +05:30 offset catches an implementation
    that assumes whole-hour offsets, which a zone like ``America/New_York``
    would not.
    """
    if source_factory is None:
        return CheckResult(
            number="7b",
            name="Timestamps are UTC (session time zone)",
            status=SKIP,
            detail="needs a Postgres source; SQLite has no session time zone",
            expected="identical output under SET TIME ZONE 'UTC' and 'Asia/Kolkata'",
            actual="not run - re-run with --source postgres against the real schema",
            command="--source postgres  (then SET TIME ZONE 'Asia/Kolkata')",
            notes=[
                "This is the one acceptance criterion a local copy cannot settle. "
                "The requests.last_updated_at default is now() AT TIME ZONE 'UTC', "
                "which is session-independent, but a trigger set_updated_at() also "
                "writes that column and its body is not in #573's schema dump.",
            ],
        )

    outputs: dict[str, str] = {}
    watermarks: dict[str, str] = {}
    for time_zone in ("UTC", "Asia/Kolkata"):
        source = source_factory()
        try:
            source.set_session_time_zone(time_zone)
            result = extract(source, fixture.T0, fixture.T1)
            outputs[time_zone] = result.csv_text
            watermarks[time_zone] = format_timestamp(result.watermark)
        finally:
            source.close()

    same_rows = outputs["UTC"] == outputs["Asia/Kolkata"]
    same_watermark = watermarks["UTC"] == watermarks["Asia/Kolkata"]

    return CheckResult(
        number="7b",
        name="Timestamps are UTC (session time zone)",
        status=PASS if same_rows and same_watermark else FAIL,
        detail="extract run under SET TIME ZONE 'UTC' and 'Asia/Kolkata' (+05:30)",
        expected="byte-identical export and an identical watermark",
        actual=f"export_identical={same_rows}, watermark_identical={same_watermark}",
        command="SET TIME ZONE '<zone>' then run the extract over the same window",
    )
