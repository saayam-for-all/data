"""Tests for the requests archive verifier (issue #586).

A check that cannot fail proves nothing, so every check is shown failing on the
archive problem it exists to catch: an export that drops broken references the
way an inner join would, a re-run that leaves a second copy, a gap between
windows, ids left unresolved, timestamps shifted by a session time zone. The
evidence is built in memory, so no database or S3 is needed.
"""

import copy
import csv
import io
from datetime import datetime

import pytest

from scripts.archive_verification import verify_request_archive as v

T = datetime.fromisoformat
W1 = (T("2026-11-09 10:00:00"), T("2026-11-09 11:00:00"))
W2 = (T("2026-11-09 11:00:00"), T("2026-11-09 12:00:00"))
KEY1 = "requests_enriched/window_start=20261109T100000Z/window_end=20261109T110000Z/requests_enriched.csv"
KEY2 = "requests_enriched/window_start=20261109T110000Z/window_end=20261109T120000Z/requests_enriched.csv"

LOOKUPS = {
    "req_for_id": {"0": "SELF", "1": "OTHER"},
    "req_islead_id": {"0": "NO", "1": "YES"},
    "req_cat_id": {"1.1": "FOOD_ASSISTANCE"},
    "req_type_id": {"0": "IN_PERSON", "1": "REMOTE"},
    "req_priority_id": {"2": "HIGH"},
    "req_status_id": {"1": "MATCHING_VOLUNTEER", "3": "RESOLVED"},
}
GOOD = {"req_for_id": 0, "req_islead_id": 1, "req_cat_id": "1.1", "req_type_id": 1,
        "req_priority_id": 2, "req_status_id": 1}


def source_row(req_id, updated, **refs):
    row = {"req_id": req_id, "submission_date": T("2026-11-09 08:00:00"),
           "serviced_date": None, "last_updated_at": T(updated), **GOOD}
    row.update(refs)
    return row


def archived(row):
    """Render a source row the way a correct export writes it."""
    out = {"req_id": row["req_id"]}
    for column in v.TIMESTAMP_COLUMNS:
        out[column] = v.render(row[column])
    for ref in v.REFERENCES:
        value = row[ref.id_column]
        out[ref.id_column] = v.render(value)
        out[ref.readable_column] = LOOKUPS[ref.id_column].get(v.render(value), "")
    return out


def csv_bytes(rows):
    columns = ["req_id", *v.TIMESTAMP_COLUMNS]
    for ref in v.REFERENCES:
        columns += [ref.id_column, ref.readable_column]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def make_evidence(files, runs, windows, types=None, counts=None, current=None):
    parsed = {key: v.parse_archive(key, csv_bytes(rows)) for key, rows in files.items()}
    source_windows = {}
    for window, rows in windows.items():
        source_windows[window] = v.SourceWindow(
            rows={r["req_id"]: r for r in rows},
            counts_by_timezone=(counts or {}).get(window, {"UTC": len(rows), "America/Phoenix": len(rows)}),
        )
    if current is None:
        current = {r["req_id"]: r["last_updated_at"] for rows in windows.values() for r in rows}
    return v.Evidence(
        runs=[v.Run(key, *window) for key, window in runs],
        files=parsed, windows=source_windows, current_versions=current, lookups=LOOKUPS,
        timestamp_types=types or {c: "timestamp without time zone" for c in v.TIMESTAMP_COLUMNS},
    )


@pytest.fixture
def source():
    """Two windows; W1 holds a request whose category points at nothing and one with no category."""
    return {
        W1: [source_row("REQ-1", "2026-11-09 10:05:00"),
             source_row("REQ-2", "2026-11-09 10:10:00", req_cat_id="CAT-MISSING"),
             source_row("REQ-3", "2026-11-09 11:00:00", req_cat_id=None)],
        W2: [source_row("REQ-4", "2026-11-09 11:30:00")],
    }


@pytest.fixture
def good(source):
    """A correct archive of both windows."""
    return make_evidence(
        files={KEY1: [archived(r) for r in source[W1]], KEY2: [archived(r) for r in source[W2]]},
        runs=[(KEY1, W1), (KEY2, W2)], windows=source,
    )


def statuses(evidence, **kwargs):
    return {r.number: r.status for r in v.run_checks(evidence, **kwargs)}


# --------------------------------------------------------------------------- #
# A correct archive passes; checks without input skip rather than pass
# --------------------------------------------------------------------------- #
def test_correct_archive_passes_and_unexercised_rerun_check_skips(good):
    assert statuses(good) == {1: "PASS", 2: "PASS", 3: "PASS", 4: "PASS", 5: "PASS", 6: "SKIP", 7: "PASS"}


def test_single_window_skips_gap_check(source):
    evidence = make_evidence({KEY1: [archived(r) for r in source[W1]]}, [(KEY1, W1)], {W1: source[W1]})
    assert statuses(evidence)[3] == "SKIP"


def test_no_broken_reference_skips_check_5():
    rows = [source_row("REQ-1", "2026-11-09 10:05:00")]
    evidence = make_evidence({KEY1: [archived(r) for r in rows]}, [(KEY1, W1)], {W1: rows})
    assert statuses(evidence)[5] == "SKIP"


# --------------------------------------------------------------------------- #
# The failure the issue most needs ruled out: an inner join dropping rows
# --------------------------------------------------------------------------- #
def test_inner_join_export_fails_row_count_and_broken_reference_checks(source):
    inner_join = [archived(r) for r in source[W1] if r["req_cat_id"] in LOOKUPS["req_cat_id"]]
    evidence = make_evidence({KEY1: inner_join, KEY2: [archived(r) for r in source[W2]]},
                             [(KEY1, W1), (KEY2, W2)], source)
    results = {r.number: r for r in v.run_checks(evidence)}
    assert results[1].status == "FAIL"
    assert results[5].status == "FAIL"
    assert any("REQ-2 DROPPED" in d for d in results[5].details)
    assert any("REQ-3 DROPPED" in d for d in results[5].details)


def test_broken_reference_with_invented_value_fails(good):
    good.files[KEY1].rows[1]["req_category"] = "GENERAL_CATEGORY"
    assert statuses(good)[5] == "FAIL"


def test_broken_reference_with_id_rewritten_fails(good):
    good.files[KEY1].rows[1]["req_cat_id"] = ""
    assert statuses(good)[5] == "FAIL"


# --------------------------------------------------------------------------- #
# Duplicates and re-runs
# --------------------------------------------------------------------------- #
def test_rerun_written_to_second_object_fails_duplicates_and_reruns(good):
    rerun_key = KEY1.replace("requests_enriched.csv", "rerun/requests_enriched.csv")
    good.files[rerun_key] = copy.deepcopy(good.files[KEY1])
    good.files[rerun_key].key = rerun_key
    good.runs.append(v.Run(rerun_key, *W1))
    result = statuses(good)
    assert result[2] == "FAIL"
    assert result[6] == "FAIL"


def test_rerun_overwriting_one_object_passes(good):
    good.runs.append(v.Run(KEY1, *W1))
    result = statuses(good)
    assert result[2] == "PASS"
    assert result[6] == "PASS"


def test_rerun_with_different_bytes_fails(good):
    rerun_key = "rerun.csv"
    rows = [dict(r) for r in good.files[KEY1].rows]
    rows.reverse()
    good.files[rerun_key] = v.parse_archive(rerun_key, csv_bytes(rows))
    good.runs.append(v.Run(rerun_key, *W1))
    result = {r.number: r for r in v.run_checks(good)}
    assert result[6].status == "FAIL"
    assert any("the files differ" in d for d in result[6].details)


def test_duplicate_row_inside_one_file_fails(good):
    good.files[KEY1].rows.append(dict(good.files[KEY1].rows[0]))
    result = statuses(good)
    assert result[1] == "FAIL"
    assert result[2] == "FAIL"


def test_updated_request_archived_again_is_allowed_unless_strict(source):
    edited = source_row("REQ-1", "2026-11-09 11:45:00", req_status_id=3)
    windows = {W1: [r for r in source[W1] if r["req_id"] != "REQ-1"], W2: source[W2] + [edited]}
    evidence = make_evidence(
        {KEY1: [archived(r) for r in source[W1]], KEY2: [archived(r) for r in windows[W2]]},
        [(KEY1, W1), (KEY2, W2)], windows,
        current={**{r["req_id"]: r["last_updated_at"] for r in source[W1]}, "REQ-1": edited["last_updated_at"],
                 "REQ-4": source[W2][0]["last_updated_at"]},
    )
    assert statuses(evidence)[1] == "PASS"  # REQ-1 left W1 after export: explained
    assert statuses(evidence)[2] == "PASS"
    assert statuses(evidence, strict=True)[2] == "FAIL"


# --------------------------------------------------------------------------- #
# Gaps
# --------------------------------------------------------------------------- #
def test_gap_between_windows_fails(source):
    late = (T("2026-11-09 11:05:00"), T("2026-11-09 12:00:00"))
    evidence = make_evidence({KEY1: [archived(r) for r in source[W1]], KEY2: [archived(r) for r in source[W2]]},
                             [(KEY1, W1), (KEY2, late)], {W1: source[W1], late: source[W2]})
    result = {r.number: r for r in v.run_checks(evidence)}
    assert result[3].status == "FAIL"
    assert any(d.startswith("gap") for d in result[3].details)


def test_overlapping_windows_fail(source):
    early = (T("2026-11-09 10:55:00"), T("2026-11-09 12:00:00"))
    evidence = make_evidence({KEY1: [archived(r) for r in source[W1]], KEY2: [archived(r) for r in source[W2]]},
                             [(KEY1, W1), (KEY2, early)], {W1: source[W1], early: source[W2]})
    assert statuses(evidence)[3] == "FAIL"


def test_request_created_between_runs_missing_from_next_file_fails(good):
    good.files[KEY2].rows.clear()
    result = statuses(good)
    assert result[3] == "FAIL"
    assert result[1] == "FAIL"


# --------------------------------------------------------------------------- #
# Joins
# --------------------------------------------------------------------------- #
def test_readable_value_left_as_id_fails(good):
    good.files[KEY1].rows[0]["req_status"] = "1"
    assert statuses(good)[4] == "FAIL"


def test_wrong_readable_value_fails(good):
    good.files[KEY1].rows[0]["req_priority"] = "LOW"
    assert statuses(good)[4] == "FAIL"


def test_missing_readable_column_fails(source):
    rows = [archived(r) for r in source[W1]]
    for row in rows:
        del row["req_type"]
    raw = csv_bytes(rows).replace(b",req_type,", b",", 1)  # header without req_type
    evidence = make_evidence({KEY1: rows}, [(KEY1, W1)], {W1: source[W1]})
    evidence.files[KEY1] = v.parse_archive(KEY1, raw)
    assert statuses(evidence)[4] == "FAIL"


# --------------------------------------------------------------------------- #
# UTC
# --------------------------------------------------------------------------- #
def test_timestamps_shifted_by_session_time_zone_fail(good):
    for row in good.files[KEY1].rows:  # exported as America/Phoenix wall time
        row["last_updated_at"] = str(T(row["last_updated_at"]).replace(hour=T(row["last_updated_at"]).hour - 7))
    result = {r.number: r for r in v.run_checks(good)}
    assert result[7].status == "FAIL"
    assert any("outside its window" in d for d in result[7].details)


def test_timestamp_with_time_zone_column_fails(good):
    good.timestamp_types["last_updated_at"] = "timestamp with time zone"
    assert statuses(good)[7] == "FAIL"


def test_window_selecting_different_rows_by_time_zone_fails(good):
    good.windows[W1].counts_by_timezone = {"UTC": 3, "Asia/Kolkata": 1}
    assert statuses(good)[7] == "FAIL"


def test_watermark_end_after_utc_run_time_fails(source):
    key = "requests_enriched/archive_year=2026/archive_month=11/archive_day=09/run_ts=20261109T053000Z/x.csv"
    evidence = make_evidence({key: [archived(r) for r in source[W1]]}, [(key, W1)], {W1: source[W1]})
    result = {r.number: r for r in v.run_checks(evidence)}
    assert result[7].status == "FAIL"  # window ends 11:00 but the run happened at 05:30 UTC


# --------------------------------------------------------------------------- #
# Parsing and stores
# --------------------------------------------------------------------------- #
def test_parse_archive_accepts_bom_and_quoted_newlines():
    raw = '﻿req_id,req_desc\nREQ-1,"a, ""b""\nc"\n'.encode("utf-8")
    archive = v.parse_archive("k", raw)
    assert archive.rows == [{"req_id": "REQ-1", "req_desc": 'a, "b"\nc'}]


def test_parse_archive_without_req_id_raises():
    with pytest.raises(ValueError):
        v.parse_archive("k", b"id,x\n1,2\n")


def test_parse_timestamp_normalises_offsets_to_utc():
    assert v.parse_timestamp("2026-11-09T11:00:00Z") == T("2026-11-09 11:00:00")
    assert v.parse_timestamp("2026-11-09 04:00:00-07:00") == T("2026-11-09 11:00:00")


def test_local_store_reads_manifest_keys(tmp_path):
    (tmp_path / "a" / "b.csv").parent.mkdir()
    (tmp_path / "a" / "b.csv").write_bytes(b"req_id\nX\n")
    store = v.LocalStore(str(tmp_path))
    assert store.list_keys() == ["a/b.csv"]
    assert store.read("a/b.csv") == b"req_id\nX\n"


def test_s3_store_lists_and_reads():
    moto = pytest.importorskip("moto")
    boto3 = pytest.importorskip("boto3")
    with moto.mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="archive-test")
        client.put_object(Bucket="archive-test", Key="p/one.csv", Body=b"req_id\n1\n")
        store = v.S3Store("archive-test", client=client)
        assert store.list_keys("p/") == ["p/one.csv"]
        assert store.read("p/one.csv") == b"req_id\n1\n"
