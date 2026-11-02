"""Checks for the synthetic requests dataset (Issue #587), validated against saayam_schema.sql itself."""
import csv
import importlib.util
import os
import re
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pytest

MOCK_DIR = Path(__file__).resolve().parents[1] / "mock_data" / "requests"
SCHEMA_SQL = MOCK_DIR / "saayam_schema.sql"
ARCHIVE_SQL = (Path(__file__).resolve().parents[1] / "infrastructure" / "db" / "requests_s3_archive"
               / "001_requests_s3_archive.sql")

_spec = importlib.util.spec_from_file_location("mock_requests_generate", MOCK_DIR / "generate.py")
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

NULL = gen.NULL_TOKEN
TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
EWKT = re.compile(r"^SRID=4326;POINT\(-?\d+\.\d{6} -?\d+\.\d{6}\)$")


# ----------------------------------------------------------------------------- schema parsing

def parse_schema():
    """{table: {column: {type, limit, not_null, pk, ref}}} read from the DDL, comments stripped."""
    text = re.sub(r"--[^\n]*", "", SCHEMA_SQL.read_text(encoding="utf-8"))
    tables = {}
    for match in re.finditer(r"CREATE TABLE\s+\w+\.(\w+)\s*\(", text):
        depth, pos = 1, match.end()
        while depth:
            depth += (text[pos] == "(") - (text[pos] == ")")
            pos += 1
        body, parts, depth, start = text[match.end():pos - 1], [], 0, 0
        for k, ch in enumerate(body):
            depth += (ch == "(") - (ch == ")")
            if ch == "," and depth == 0:
                parts.append(body[start:k])
                start = k + 1
        parts.append(body[start:])
        columns = {}
        for part in parts:
            d = " ".join(part.split())
            m = re.match(r"(\w+) (.+?)(?= PRIMARY KEY| NOT NULL| REFERENCES| DEFAULT|$)", d)
            limit = re.search(r"varchar\((\d+)\)", m.group(2))
            ref = re.search(r"REFERENCES \w+\.(\w+)\((\w+)\)", d)
            pk = "PRIMARY KEY" in d
            columns[m.group(1)] = {
                "type": m.group(2), "limit": int(limit.group(1)) if limit else None,
                "not_null": pk or "NOT NULL" in d, "pk": pk,
                "ref": (ref.group(1), ref.group(2)) if ref else None,
            }
        tables[match.group(1)] = columns
    return tables


SCHEMA = parse_schema()


# ----------------------------------------------------------------------------- CSV reading

def read_csv(path):
    """(header, rows as dicts). \\N becomes None; an empty field stays ''."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = [{h: (None if v == NULL else v) for h, v in zip(header, r)} for r in reader]
    return header, rows


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    path = tmp_path_factory.mktemp("mock_requests")
    gen.generate(path)
    return path


@pytest.fixture(scope="module")
def data(out):
    return {t: read_csv(out / "csv" / f"{t}.csv")[1] for t in gen.TABLES}


@pytest.fixture(scope="module")
def requests_rows(data):
    return data["requests"]


@pytest.fixture(scope="module")
def manifest(out):
    return read_csv(out / "special_cases_manifest.csv")[1]


def by_id(rows):
    return {r["req_id"]: r for r in rows}


def ts(value):
    return datetime.strptime(value, TS_FORMAT)


# ----------------------------------------------------------------------------- schema conformance

def test_schema_has_the_nine_tables_and_nine_request_foreign_keys():
    assert set(SCHEMA) == set(gen.TABLES)
    refs = [c["ref"] for c in SCHEMA["requests"].values() if c["ref"]]
    assert len(refs) == 9


def test_headers_match_schema_columns(out):
    for table, columns in gen.TABLES.items():
        header, _ = read_csv(out / "csv" / f"{table}.csv")
        assert header == columns
        assert set(header) <= set(SCHEMA[table])
    # only users is trimmed (key column only); every other table lists all its columns
    for table in gen.TABLES:
        if table != "users":
            assert set(gen.TABLES[table]) == set(SCHEMA[table])
    assert gen.TABLES["users"] == ["user_id"]


def test_row_counts(data):
    assert {t: len(r) for t, r in data.items()} == {
        "help_categories": 80, "help_categories_map": 80, "request_for": 2, "request_isleadvol": 2,
        "request_types": 2, "request_priorities": 4, "request_statuses": 9, "users": 150, "requests": 500,
    }


def test_primary_keys_are_unique_and_not_null(data):
    for table, rows in data.items():
        for column, meta in SCHEMA[table].items():
            if meta["pk"] and column in gen.TABLES[table]:
                values = [r[column] for r in rows]
                assert None not in values and "" not in values
                assert len(set(values)) == len(values), (table, column)


def test_not_null_columns_are_never_null(data):
    for table, rows in data.items():
        for column in gen.TABLES[table]:
            if SCHEMA[table][column]["not_null"]:
                assert all(r[column] is not None for r in rows), (table, column)


def test_varchar_limits_are_respected(data):
    for table, rows in data.items():
        for column in gen.TABLES[table]:
            limit = SCHEMA[table][column]["limit"]
            if limit:
                longest = max(len(r[column]) for r in rows if r[column] is not None)
                assert longest <= limit, (table, column, longest, limit)


def test_values_parse_as_their_declared_types(data):
    for table, rows in data.items():
        for column in gen.TABLES[table]:
            kind = SCHEMA[table][column]["type"]
            for r in rows:
                v = r[column]
                if v is None:
                    continue
                if kind in ("serial", "integer"):
                    assert re.fullmatch(r"\d+", v), (table, column, v)
                elif kind.startswith("timestamp"):
                    ts(v) if "." in v else datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
                elif kind == "boolean":
                    assert v in ("true", "false")
                elif kind.startswith("public.geometry"):
                    assert EWKT.match(v), v


def test_foreign_keys_are_valid(data):
    checked = 0
    for table, rows in data.items():
        for column, meta in SCHEMA[table].items():
            if meta["ref"] and column in gen.TABLES[table]:
                ref_table, ref_column = meta["ref"]
                targets = {r[ref_column] for r in data[ref_table]}
                for r in rows:
                    if r[column] is not None:
                        assert r[column] in targets, (table, column, r[column])
                checked += 1
    assert checked == 9 + 2  # nine on requests, two on help_categories_map


def test_null_token_is_only_ever_written_unquoted(out):
    for path in (out / "csv").glob("*.csv"):
        assert '"\\N"' not in path.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- fixed lookups

def test_fixed_lookup_values_are_exactly_the_expected_ones(data):
    def names(table, id_col, name_col):
        return {int(r[id_col]): r[name_col] for r in data[table]}

    assert names("request_for", "req_for_id", "req_for") == {0: "SELF", 1: "OTHER"}
    assert names("request_isleadvol", "req_islead_id", "req_islead") == {0: "NO", 1: "YES"}
    assert names("request_types", "req_type_id", "req_type") == {0: "IN_PERSON", 1: "REMOTE"}
    assert names("request_priorities", "req_priority_id", "req_priority") == {
        0: "LOW", 1: "MEDIUM", 2: "HIGH", 3: "CRITICAL"}
    assert names("request_statuses", "req_status_id", "req_status") == {
        0: "CREATED", 1: "MATCHING_VOLUNTEER", 2: "IN_PROGRESS", 3: "RESOLVED", 4: "CANCELLED",
        5: "DELETED", 6: "RATED_BY_REQUESTER", 7: "RATED_BY_VOLUNTEER", 8: "VOLUNTEER_NOT_FOUND"}
    assert len(data["help_categories"]) == 80


# ----------------------------------------------------------------------------- numbered cases

def test_case_1_skewed_null_references(requests_rows):
    assert sum(r["lead_volunteer_id"] is None for r in requests_rows) == 493
    assert sum(r["beneficiary_id"] is None for r in requests_rows) == 18
    for column in ("creator_id", "req_cat_id", "req_for_id", "req_islead_id", "req_type_id",
                   "req_priority_id", "req_status_id"):
        assert all(r[column] is not None for r in requests_rows)


def test_case_2_identical_microsecond_last_updated_at(requests_rows):
    counts = Counter(r["last_updated_at"] for r in requests_rows)
    shared = {k: v for k, v in counts.items() if v > 1}
    assert shared == {
        gen.TIE_DAY_END.strftime(TS_FORMAT): 6,
        gen.TIE_MIDNIGHT.strftime(TS_FORMAT): 6,
        gen.TIE_MID.strftime(TS_FORMAT): 5,
    }
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{6}", r["last_updated_at"])
               for r in requests_rows)
    assert "2026-09-30 23:59:59.999999" in shared and "2026-10-01 00:00:00.000000" in shared


def test_case_3_updated_before_submitted(requests_rows):
    early = [r for r in requests_rows if ts(r["last_updated_at"]) < ts(r["submission_date"])]
    assert len(early) == 8
    assert any(ts(r["submission_date"]) - ts(r["last_updated_at"]) == timedelta(microseconds=1) for r in early)


def test_case_4_csv_special_characters_round_trip(out, requests_rows):
    text = " ".join(r["req_subj"] + " " + r["req_desc"] for r in requests_rows)
    assert "\n" in text and "\r\n" in text and '"' in text and "," in text and "'" in text
    assert any("\n" in r["req_desc"] for r in requests_rows)
    # rewriting what was read must reproduce the file exactly
    again = out / "again.csv"
    header, rows = read_csv(out / "csv" / "requests.csv")
    gen.write_csv(again, header, rows)
    assert again.read_bytes() == (out / "csv" / "requests.csv").read_bytes()


def test_case_5_unicode_and_spanish_text(out, requests_rows):
    raw = (out / "csv" / "requests.csv").read_bytes()
    raw.decode("utf-8")
    assert not raw.startswith(b"\xef\xbb\xbf")
    text = "".join(r["req_subj"] + r["req_desc"] for r in requests_rows)
    assert unicodedata.normalize("NFC", text) == text
    assert all(ch in text for ch in "ñ¿¡áéíóú")
    assert re.search(r"[\u0900-\u097f]", text) and re.search(r"[\u0600-\u06ff]", text)
    assert re.search(r"[\u4e00-\u9fff]", text) and re.search(r"[\u0400-\u04ff]", text)
    assert re.search(r"[\U0001F300-\U0001FAFF]", text)  # 4-byte emoji
    assert sum("Necesit" in r["req_subj"] or "Ayuda" in r["req_subj"] for r in requests_rows) >= 20


def test_case_6_synthetic_personal_details_are_tracked(requests_rows, manifest):
    rows = by_id(requests_rows)
    entries = [m for m in manifest if m["case_no"] == "6"]
    assert len(entries) >= 21
    formats = set()
    for m in entries:
        kind_format, value = m["detail"].split(": ", 1)
        formats.add(kind_format)
        assert value in rows[m["req_id"]]["req_desc"]
        if kind_format.startswith("phone/") and not kind_format.startswith("phone/words"):
            assert re.search(r"555\D?01\d\d", value)  # reserved fictional range
        if kind_format.startswith("email"):
            assert value.endswith("example.test")
    assert {"phone/words_en", "phone/words_es", "phone/parenthesized", "phone/dashed", "phone/dotted",
            "phone/e164_spaced", "email/plain", "name/full_name", "address/street_address"} <= formats
    # nothing outside the manifest looks like an email address
    tracked = {m["req_id"] for m in entries}
    for r in requests_rows:
        if r["req_id"] not in tracked:
            assert "@" not in r["req_desc"] and "@" not in r["req_subj"]


def test_case_7_empty_string_is_distinct_from_null(out, requests_rows):
    for column in ("req_doc_link", "audio_req_desc", "deletion_reason"):
        values = [r[column] for r in requests_rows]
        assert values.count("") >= 10, column
        assert values.count(None) >= 10, column
    raw = (out / "csv" / "requests.csv").read_text(encoding="utf-8")
    assert NULL in raw
    # round trip: NULL -> None, '' -> '' -> written as an empty field, not \N
    sample = out / "null_vs_empty.csv"
    gen.write_csv(sample, ["a", "b", "c"], [{"a": None, "b": "", "c": "x"}])
    assert sample.read_bytes() == b"a,b,c\n\\N,,x\n"
    assert read_csv(sample)[1] == [{"a": None, "b": "", "c": "x"}]


def test_case_8_exact_maximum_lengths(requests_rows):
    for column in ("req_subj", "req_desc", "audio_req_desc"):
        limit = SCHEMA["requests"][column]["limit"]
        at_max = [r[column] for r in requests_rows if r[column] is not None and len(r[column]) == limit]
        assert len(at_max) >= 4, column
        assert all(len(v) <= limit for r in requests_rows for v in [r[column]] if v is not None)
    assert (SCHEMA["requests"]["req_subj"]["limit"], SCHEMA["requests"]["req_desc"]["limit"]) == (125, 255)
    # at least one maximum-length value has more bytes than characters
    assert any(len(r["req_desc"]) == 255 and len(r["req_desc"].encode("utf-8")) > 255 for r in requests_rows)


def test_case_9_every_lookup_value_is_used(data, requests_rows):
    for column, table, id_col in [
        ("req_for_id", "request_for", "req_for_id"), ("req_islead_id", "request_isleadvol", "req_islead_id"),
        ("req_type_id", "request_types", "req_type_id"), ("req_priority_id", "request_priorities", "req_priority_id"),
        ("req_status_id", "request_statuses", "req_status_id"),
    ]:
        assert {r[column] for r in requests_rows} == {r[id_col] for r in data[table]}, column
    assert {r["req_cat_id"] for r in requests_rows} == {r["cat_id"] for r in data["help_categories"]}
    assert any(r["req_priority_id"] == "3" for r in requests_rows)  # CRITICAL
    assert any(r["req_status_id"] == "8" for r in requests_rows)    # VOLUNTEER_NOT_FOUND


def test_case_10_islead_yes_with_null_lead_volunteer(requests_rows):
    assert sum(r["req_islead_id"] == "1" and r["lead_volunteer_id"] is None for r in requests_rows) >= 1
    assert sum(r["req_islead_id"] == "1" and r["lead_volunteer_id"] is not None for r in requests_rows) >= 1


def test_case_11_broken_fk_fixture_is_separate_and_broken(out, data, requests_rows):
    header, broken = read_csv(out / "fixtures" / "broken_fk" / "requests_broken_fk.csv")
    assert header == gen.TABLES["requests"]
    assert not {r["req_id"] for r in broken} & {r["req_id"] for r in requests_rows}
    # every foreign key column is broken by exactly one fixture row
    broken_columns = []
    for r in broken:
        bad = [c for c, m in SCHEMA["requests"].items()
               if m["ref"] and r[c] is not None
               and r[c] not in {t[m["ref"][1]] for t in data[m["ref"][0]]}]
        assert len(bad) == 1
        broken_columns += bad
    assert sorted(broken_columns) == sorted(c for c, m in SCHEMA["requests"].items() if m["ref"])
    # the fixture never leaks into the main load
    assert not (out / "csv" / "requests_broken_fk.csv").exists()
    assert all(r["req_id"] not in {b["req_id"] for b in broken} for r in requests_rows)


# ----------------------------------------------------------------------------- manifest

def test_manifest_covers_all_eleven_cases_and_matches_the_data(manifest, requests_rows, out):
    assert {int(m["case_no"]) for m in manifest} == set(range(1, 12))
    rows = by_id(requests_rows)
    _, broken = read_csv(out / "fixtures" / "broken_fk" / "requests_broken_fk.csv")
    broken = by_id(broken)
    for m in manifest:
        r = (broken if m["case_no"] == "11" else rows)[m["req_id"]]
        case, column = int(m["case_no"]), m["column"]
        if case == 2:
            assert r["last_updated_at"] == m["detail"]
        elif case == 3:
            assert ts(r["last_updated_at"]) < ts(r["submission_date"])
        elif case == 7:
            assert r[column] == ""
        elif case == 8:
            assert len(r[column]) == int(m["detail"].split("=")[1])
        elif case == 10:
            assert r["req_islead_id"] == "1" and r["lead_volunteer_id"] is None
        elif case == 11:
            assert r[column] == m["detail"].split(" ")[0]


# ----------------------------------------------------------------------------- pipeline boundaries

def test_timestamp_boundaries_follow_the_archive_pipeline_sql(requests_rows):
    sql = ARCHIVE_SQL.read_text(encoding="utf-8")
    for predicate in ("last_updated_at > v_watermark_start", "last_updated_at <= v_watermark_end",
                      "last_updated_at >= v_partition_start", "last_updated_at < v_partition_end",
                      "ORDER BY last_updated_at, req_id"):
        assert predicate in sql

    updated = [(ts(r["last_updated_at"]), r["req_id"]) for r in requests_rows]

    def window(start, end):  # the run window: > start AND <= end
        return [x for x in updated if start < x[0] <= end]

    def partition(rows):  # one export per day: >= day start AND < day start + 1 day
        days = defaultdict(list)
        for stamp, rid in rows:
            days[stamp.replace(hour=0, minute=0, second=0, microsecond=0)].append(rid)
        return days

    for tie, size in [(gen.TIE_DAY_END, 6), (gen.TIE_MIDNIGHT, 6), (gen.TIE_MID, 5)]:
        tied = {rid for stamp, rid in updated if stamp == tie}
        assert len(tied) == size
        one_us = timedelta(microseconds=1)
        # a tie is all-or-nothing around a watermark: included at the end, excluded at the start
        assert tied <= {rid for _, rid in window(datetime.min, tie)}
        assert not tied & {rid for _, rid in window(datetime.min, tie - one_us)}
        assert not tied & {rid for _, rid in window(tie, datetime.max)}
        # two consecutive runs cut at the tie export every row exactly once
        first, second = window(datetime.min, tie), window(tie, datetime.max)
        assert sorted(first + second) == sorted(updated)
        assert not set(first) & set(second)

    days = partition(window(datetime.min, datetime.max))
    assert sum(len(v) for v in days.values()) == len(updated)  # each row lands in exactly one day
    day_end_day = gen.TIE_DAY_END.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight_day = gen.TIE_MIDNIGHT
    assert len([1 for s, _ in updated if s == gen.TIE_DAY_END]) == 6 and day_end_day != midnight_day
    assert {rid for s, rid in updated if s == gen.TIE_MIDNIGHT} <= set(days[midnight_day])
    assert {rid for s, rid in updated if s == gen.TIE_DAY_END} <= set(days[day_end_day])
    # rows updated before they were submitted are still picked up: only last_updated_at is filtered
    early = {r["req_id"] for r in requests_rows if ts(r["last_updated_at"]) < ts(r["submission_date"])}
    assert early <= {rid for _, rid in window(datetime.min, datetime.max)}


# ----------------------------------------------------------------------------- determinism

def _tree(path):
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


def test_regeneration_is_byte_identical(tmp_path):
    gen.generate(tmp_path / "a")
    gen.generate(tmp_path / "b")
    assert _tree(tmp_path / "a") == _tree(tmp_path / "b")
    assert len(_tree(tmp_path / "a")) == 11  # nine csv + manifest + broken fixture


def test_regeneration_does_not_depend_on_hash_randomisation(tmp_path):
    for name, hash_seed in (("a", "1"), ("b", "2")):
        subprocess.run([sys.executable, str(MOCK_DIR / "generate.py"), "--out", str(tmp_path / name)],
                       check=True, capture_output=True, env={**os.environ, "PYTHONHASHSEED": hash_seed})
    assert _tree(tmp_path / "a") == _tree(tmp_path / "b")


def test_a_different_seed_gives_different_data(tmp_path):
    gen.generate(tmp_path / "a", seed=1)
    gen.generate(tmp_path / "b", seed=2)
    assert _tree(tmp_path / "a")["csv/requests.csv"] != _tree(tmp_path / "b")["csv/requests.csv"]


def test_committed_files_match_a_fresh_run_with_the_default_seed(tmp_path):
    gen.generate(tmp_path)
    committed = _tree(MOCK_DIR)
    for name, content in _tree(tmp_path).items():
        assert committed[name] == content, f"{name} is stale; rerun generate.py"
