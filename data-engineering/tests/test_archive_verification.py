"""Tests for the archive verification harness (issue #586).

These run anywhere, including CI: the local copy of the schema is SQLite, which
ships with Python, so no container, credentials or network are needed. Tests
that genuinely need the real Postgres source skip themselves, the same way
``test_organization_analytics.py`` mocks the DB layer rather than requiring one.

Roughly half of this file is mutation tests. A suite of checks that all pass
proves nothing unless the checks can fail, so each ``test_mutation_*`` removes
one property the extract is supposed to hold and asserts the matching check
goes red. Those are the tests worth keeping green.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

from src.archive_verification import checks, fixture, verify
from src.archive_verification.adapters import (
    EXTRACT_SQL,
    ExtractResult,
    LocalDirectoryArchive,
    SqliteSource,
    format_timestamp,
    parse_timestamp,
    reference_extract,
    resolve_extractor,
    rows_to_csv,
    window_key,
)

BASE_SQL = EXTRACT_SQL.read_text(encoding="utf-8")


@pytest.fixture
def archive(tmp_path):
    """A throwaway archive directory per test."""
    return LocalDirectoryArchive(tmp_path / "archive")


def make_extract(sql_transform=None, result_transform=None, watermark=None):
    """Build an extractor with one property optionally broken, for mutations."""
    state = {"calls": 0}

    def extract(source, low, high):
        sql = sql_transform(BASE_SQL) if sql_transform else BASE_SQL
        columns, rows = source.query(
            source.render(sql), [format_timestamp(low), format_timestamp(high)]
        )
        state["calls"] += 1
        if result_transform:
            rows = result_transform(rows, state["calls"])
        return ExtractResult(
            columns=columns,
            rows=rows,
            watermark=watermark(rows, low, high) if watermark else high,
            csv_text=rows_to_csv(columns, rows),
            key=window_key(low, high),
        )

    return extract


# ------------------------------------------------------------------- fixture


def test_fixture_contains_every_case_the_checks_rely_on():
    """The local copy carries each deliberately awkward row."""
    source, facts = fixture.build()
    try:
        assert facts.null_lead_volunteer
        assert facts.null_beneficiary
        assert facts.dangling_category
        assert len(facts.boundary_tie) == 3
        assert facts.awkward_text
        assert facts.updated_after_submission
    finally:
        source.close()


def test_fixture_loads_the_committed_lookup_values():
    """Lookup values come from database/lookup_tables, not from invented data."""
    source, _ = fixture.build()
    try:
        assert fixture.lookup_values(source, "help_categories", "cat_name")
        statuses = fixture.lookup_values(source, "request_statuses", "req_status")
        # Values and ids both match #573's DDL comments.
        assert {"CREATED", "MATCHING_VOLUNTEER", "RESOLVED"} <= statuses
        # request_status.csv stops at 7; the DDL comment lists 8.
        assert "VOLUNTEER_NOT_FOUND" in statuses
        assert fixture.lookup_values(source, "request_priorities", "req_priority") == {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }
    finally:
        source.close()


def test_boundary_rows_share_a_timestamp_to_the_microsecond():
    """The tie group is an exact tie, which is what makes check 3 meaningful."""
    source, facts = fixture.build()
    try:
        _, rows = source.query(
            "SELECT DISTINCT last_updated_at FROM requests WHERE req_id IN (?, ?, ?)",
            facts.boundary_tie,
        )
        assert len(rows) == 1
        assert parse_timestamp(rows[0][0]) == facts.middle
    finally:
        source.close()


def test_dangling_category_is_absent_from_the_lookup():
    """Check 5b's row points at a category that genuinely does not exist."""
    source, _ = fixture.build()
    try:
        _, rows = source.query(
            "SELECT count(*) FROM help_categories WHERE cat_id = ?",
            [fixture.DANGLING_CATEGORY],
        )
        assert rows[0][0] == 0
    finally:
        source.close()


def test_schema_enforces_the_foreign_key_the_dangling_row_violates():
    """The constraint is real, so check 5b's row needed enforcement disabled.

    This is the evidence for the claim in the report: production's foreign keys
    make a dangling non-null reference unreachable by an ordinary write.
    """
    source, _ = fixture.build()
    try:
        with pytest.raises(Exception):
            fixture._insert_request(
                source,
                "REQ-REJECTED",
                fixture.T0,
                req_cat_id=fixture.DANGLING_CATEGORY,
            )
    finally:
        source.close()


def test_foreign_key_pragma_refuses_to_fail_silently():
    """PRAGMA foreign_keys is ignored inside a transaction; that must raise."""
    source = SqliteSource(":memory:")
    try:
        source.executescript("CREATE TABLE t (a INTEGER)")
        source.connection.execute("INSERT INTO t VALUES (1)")  # opens a transaction
        source.connection.execute("PRAGMA foreign_keys = OFF")
        assert source.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        # The guarded accessor commits first, so it actually applies.
        source.set_foreign_keys(False)
        assert source.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
    finally:
        source.close()


# ----------------------------------------------------------------- utilities


def test_format_timestamp_rejects_tz_aware_values():
    """Mixing aware and naive values is the bug check 7a exists to catch."""
    with pytest.raises(ValueError, match="naive UTC"):
        format_timestamp(datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert format_timestamp(None) == ""
    assert format_timestamp(datetime(2026, 10, 1)) == "2026-10-01 00:00:00.000000"


def test_read_csv_rows_survives_newlines_inside_a_field():
    """Line counting overstates the rows; parsing does not."""
    payload = rows_to_csv(["req_id", "req_desc"], [("REQ-1", "a\nb\nc"), ("REQ-2", "d")])
    _, rows = checks.read_csv_rows(payload)
    assert len(rows) == 2
    assert len(payload.splitlines()) - 1 == 4  # the trap, for contrast
    assert rows[0]["req_desc"] == "a\nb\nc"


def test_window_key_depends_only_on_the_window():
    """A key containing the run time would make a re-run write a second file."""
    low, high = datetime(2026, 10, 1), datetime(2026, 10, 8)
    assert window_key(low, high) == window_key(low, high)
    assert window_key(low, high) != window_key(low, high + timedelta(days=1))


def test_rows_to_csv_is_byte_stable_and_uses_unix_line_endings():
    """Check 6 compares bytes, so serialisation must not vary."""
    rows = [("REQ-1", datetime(2026, 10, 1)), ("REQ-2", None)]
    first = rows_to_csv(["req_id", "last_updated_at"], rows)
    assert first == rows_to_csv(["req_id", "last_updated_at"], rows)
    assert "\r\n" not in first


def test_resolve_extractor_labels_the_fixture_as_a_fixture():
    """A passing report must never read as a verified production pipeline."""
    extractor, label = resolve_extractor(None)
    assert extractor is reference_extract
    assert "FIXTURE" in label

    extractor, label = resolve_extractor("src.archive_verification.adapters:reference_extract")
    assert extractor is reference_extract
    assert label == "src.archive_verification.adapters:reference_extract"

    with pytest.raises(ValueError, match="module:callable"):
        resolve_extractor("not-a-spec")
    with pytest.raises(ValueError, match="no attribute"):
        resolve_extractor("src.archive_verification.adapters:nope")


# -------------------------------------------------------- the checks pass


ALL_CHECKS = (
    checks.check_row_counts,
    checks.check_no_duplicates,
    checks.check_no_gaps,
    checks.check_joins_resolve,
    checks.check_broken_references_survive,
    checks.check_reruns_are_safe,
    checks.check_timestamps_utc,
)


@pytest.mark.parametrize("check", ALL_CHECKS, ids=lambda check: check.__name__)
def test_reference_extract_passes_every_check(check, archive):
    """The reference extract satisfies the contract #586 describes."""
    result = check(reference_extract, archive)
    assert result.status == checks.PASS, f"{result.name}: {result.actual}"


def test_session_time_zone_check_skips_without_postgres(archive):
    """Check 7b reports SKIP rather than a PASS it could not have earned."""
    result = checks.check_session_time_zone(reference_extract, archive, None)
    assert result.status == checks.SKIP
    assert "postgres" in result.actual.lower()


def test_row_count_check_compares_against_the_source(archive):
    """#586: counts must come from the source, not from the file itself."""
    result = checks.check_row_counts(reference_extract, archive)
    assert "count(*)" in result.command
    assert result.status == checks.PASS


def test_duplicate_check_accepts_a_legitimate_rearchive(archive):
    """A req_id in two files with different versions is correct, not a duplicate."""
    result = checks.check_no_duplicates(reference_extract, archive)
    assert result.status == checks.PASS
    assert any("re-archived" in note for note in result.notes)


# ------------------------------------------------------------- mutations


def _inner_join_categories(sql):
    return sql.replace(
        "LEFT JOIN {prefix}help_categories    hc", "JOIN {prefix}help_categories    hc"
    )


def _inner_join_lead_volunteer(sql):
    return sql.replace(
        "LEFT JOIN {prefix}users              lu", "JOIN {prefix}users              lu"
    )


def _closed_high_bound(sql):
    return sql.replace("AND r.last_updated_at <  {p}", "AND r.last_updated_at <= {p}")


def _exclusive_low_bound(sql):
    return sql.replace("WHERE r.last_updated_at >= {p}", "WHERE r.last_updated_at > {p}")


def _status_as_identifier(sql):
    return sql.replace("rs.req_status,", "r.req_status_id AS req_status,")


def _unstable_order(rows, call_number):
    return list(reversed(rows)) if call_number % 2 == 0 else list(rows)


def _watermark_from_max(rows, low, high):
    stamps = [row[-1] for row in rows if row[-1]]
    return parse_timestamp(max(stamps)) if stamps else low


def _watermark_from_local_clock(rows, low, high):
    return datetime.now()


def test_mutation_inner_join_on_category_drops_the_broken_row(archive):
    """The failure #586 most wants ruled out: a silent drop, count merely lower."""
    extract = make_extract(sql_transform=_inner_join_categories)
    assert checks.check_broken_references_survive(extract, archive).status == checks.FAIL
    assert checks.check_row_counts(extract, archive).status == checks.FAIL


def test_mutation_inner_join_on_lead_volunteer_drops_null_rows(archive):
    """218 of 221 real requests have no lead volunteer."""
    extract = make_extract(sql_transform=_inner_join_lead_volunteer)
    assert checks.check_broken_references_survive(extract, archive).status == checks.FAIL


def test_mutation_closed_window_duplicates_boundary_rows(archive):
    """A closed window archives a boundary tie in both of two adjacent runs."""
    extract = make_extract(sql_transform=_closed_high_bound)
    assert checks.check_no_duplicates(extract, archive).status == checks.FAIL


def test_mutation_exclusive_low_bound_loses_boundary_rows(archive):
    """An exclusive low bound drops rows sitting exactly on the boundary."""
    extract = make_extract(sql_transform=_exclusive_low_bound)
    assert checks.check_no_gaps(extract, archive).status == checks.FAIL


def test_mutation_watermark_from_max_loses_the_boundary(archive):
    """Advancing to max(last_updated_at) is the classic watermark bug."""
    extract = make_extract(watermark=_watermark_from_max)
    assert checks.check_no_gaps(extract, archive).status == checks.FAIL


def test_mutation_unstable_row_order_is_not_reported_as_data_loss(archive):
    """Check 6 must distinguish a missing ORDER BY from losing rows."""
    extract = make_extract(result_transform=_unstable_order)
    result = checks.check_reruns_are_safe(extract, archive)
    assert result.status == checks.FAIL
    assert any("ORDER BY" in note for note in result.notes)
    assert not any("different rows" in note for note in result.notes)


def test_mutation_identifier_instead_of_readable_word(archive):
    """Check 4 catches a reference that arrives as a number."""
    extract = make_extract(sql_transform=_status_as_identifier)
    assert checks.check_joins_resolve(extract, archive).status == checks.FAIL


def test_mutation_watermark_from_local_clock(archive):
    """datetime.now() where datetime.now(timezone.utc) was required."""
    extract = make_extract(watermark=_watermark_from_local_clock)
    assert checks.check_timestamps_utc(extract, archive).status == checks.FAIL


# ------------------------------------------------------------------ the CLI


def test_cli_reports_every_check_and_exits_zero(capsys, tmp_path):
    """The committed script prints a pass or fail for each check, as #586 asks."""
    exit_code = verify.main(["--archive-dir", str(tmp_path / "out")])
    output = capsys.readouterr().out
    assert exit_code == 0
    for number in ("1", "2", "3", "4", "5", "6", "7a", "7b"):
        assert f"[PASS] {number} " in output or f"[SKIP] {number} " in output
    assert "7 passed, 0 failed, 1 skipped" in output
    assert "FIXTURE, not production" in output
    assert "total" in output


def test_cli_exits_non_zero_when_a_check_fails(tmp_path, monkeypatch):
    """A failing check must fail the process, so this can gate CI later."""
    monkeypatch.setattr(
        verify.checks, "check_row_counts", lambda *_: checks.CheckResult("1", "x", checks.FAIL)
    )
    assert verify.main(["--archive-dir", str(tmp_path / "out")]) == 1


# -------------------------------------------------------------- postgres


@pytest.mark.skipif(
    not os.getenv("ARCHIVE_VERIFY_POSTGRES"),
    reason="needs a reachable Postgres; set ARCHIVE_VERIFY_POSTGRES=1 to run",
)
def test_session_time_zone_check_against_postgres(archive):  # pragma: no cover
    """Check 7b, the one criterion only a Postgres source can settle."""
    from src.archive_verification.adapters import PostgresSource

    result = checks.check_session_time_zone(
        reference_extract, archive, lambda: PostgresSource(os.getenv("DB_SCHEMA", "public"))
    )
    assert result.status in (checks.PASS, checks.FAIL)
    assert result.status != checks.SKIP
