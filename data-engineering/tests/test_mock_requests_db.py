"""Loads the generated CSVs into a temporary local PostgreSQL/PostGIS cluster and checks the result (Issue #587).

Skipped when PostgreSQL 17 / PostGIS are not installed. The cluster is created in a new temp directory,
listens on 127.0.0.1 only, and is removed when the module finishes.
"""
import csv
import importlib.util
import io
import shutil
from datetime import datetime
from pathlib import Path

import pytest

psycopg2 = pytest.importorskip("psycopg2")

MOCK_DIR = Path(__file__).resolve().parents[1] / "mock_data" / "requests"
CSV_DIR = MOCK_DIR / "csv"
BROKEN_FK = MOCK_DIR / "fixtures" / "broken_fk" / "requests_broken_fk.csv"

_spec = importlib.util.spec_from_file_location("mock_requests_load_local", MOCK_DIR / "load_local.py")
loader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(loader)

S = loader.SCHEMA
TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

try:
    loader.find_bin("initdb")
    loader.find_bin("pg_ctl")
except FileNotFoundError as e:  # pragma: no cover
    pytest.skip(str(e), allow_module_level=True)


@pytest.fixture(scope="module")
def db():
    with loader.TempCluster() as cluster:
        conn = cluster.connect()
        loader.load(conn, CSV_DIR)
        yield conn
        conn.close()


def q(db, sql, params=None):
    cur = db.cursor()
    cur.execute(sql, params)
    return cur.fetchall()


def q1(db, sql, params=None):
    return q(db, sql, params)[0][0]


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        return header, [[None if v == loader.NULL_TOKEN else v for v in row] for row in reader]


def test_postgis_works_with_the_installed_postgresql(db):
    assert q1(db, "SELECT split_part(current_setting('server_version'), '.', 1)") == "17"
    assert q1(db, "SELECT postgis_version()")
    assert q1(db, "SELECT ST_SRID(ST_GeomFromEWKT('SRID=4326;POINT(1 2)'))") == 4326


def test_all_nine_tables_load_with_expected_row_counts(db):
    expected = {"help_categories": 80, "help_categories_map": 80, "request_for": 2, "request_isleadvol": 2,
                "request_types": 2, "request_priorities": 4, "request_statuses": 9, "users": 150, "requests": 500}
    assert set(expected) == set(loader.TABLES)
    for table, count in expected.items():
        assert q1(db, f"SELECT count(*) FROM {S}.{table}") == count, table
        assert loader.csv_row_count(CSV_DIR / f"{table}.csv") == count


def test_every_non_null_foreign_key_resolves_and_constraints_are_validated(db):
    fks = q(db, """SELECT c.conrelid::regclass::text, a.attname, c.confrelid::regclass::text, c.convalidated
                   FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                   JOIN pg_namespace n ON n.oid = c.connamespace
                   WHERE c.contype = 'f' AND n.nspname = %s""", (S,))
    assert len(fks) == 11 and all(row[3] for row in fks)
    orphans = 0
    for table, column, target, _ in fks:
        pk = q1(db, """SELECT a.attname FROM pg_index i JOIN pg_attribute a
                       ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
                       WHERE i.indrelid = %s::regclass AND i.indisprimary""", (target,))
        orphans += q1(db, f"SELECT count(*) FROM {table} t WHERE t.{column} IS NOT NULL AND NOT EXISTS "
                          f"(SELECT 1 FROM {target} p WHERE p.{pk} = t.{column})")
    assert orphans == 0


def test_null_skew_and_null_versus_empty_string(db):
    assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE lead_volunteer_id IS NULL") == 493
    assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE beneficiary_id IS NULL") == 18
    header, rows = read_csv(CSV_DIR / "requests.csv")
    for column in ("req_doc_link", "audio_req_desc", "deletion_reason"):
        i = header.index(column)
        want_null = sum(r[i] is None for r in rows)
        want_empty = sum(r[i] == "" for r in rows)
        assert want_null >= 10 and want_empty >= 10
        assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE {column} IS NULL") == want_null
        assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE {column} = ''") == want_empty


def test_islead_yes_with_null_lead_volunteer(db):
    assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE req_islead_id = 1 AND lead_volunteer_id IS NULL") == 10


def test_maximum_length_values_are_preserved(db):
    assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE char_length(req_subj) = 125") >= 4
    assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE char_length(req_desc) = 255") >= 4
    assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE char_length(audio_req_desc) = 255") >= 4
    assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE char_length(req_desc) = 255 "
                  f"AND octet_length(req_desc) > 255") >= 1


def test_every_loaded_value_equals_the_csv_value(db):
    """Text (Unicode, quotes, commas, newlines), booleans, timestamps and geometry survive the real load."""
    header, rows = read_csv(CSV_DIR / "requests.csv")
    db_rows = q(db, f"""SELECT req_id, creator_id, beneficiary_id, lead_volunteer_id, req_cat_id,
                        req_for_id::text, req_islead_id::text, req_type_id::text, req_priority_id::text,
                        req_status_id::text, req_subj, req_desc, req_doc_link, audio_req_desc, deletion_reason,
                        ST_X(req_loc), ST_Y(req_loc), ST_X(created_loc), ST_Y(created_loc),
                        iscalamity, to_public, submission_date, serviced_date, last_updated_at
                        FROM {S}.requests ORDER BY req_id""")
    assert len(db_rows) == len(rows) == 500
    for csv_row, db_row in zip(sorted(rows), db_rows):
        for k in range(15):  # ids, lookups and every text column
            assert db_row[k] == csv_row[k], (csv_row[0], header[k])
        for k, name in [(15, "req_loc"), (17, "created_loc")]:
            value = csv_row[header.index(name)]
            if value is None:
                assert db_row[k] is None and db_row[k + 1] is None
            else:
                lon, lat = value[len("SRID=4326;POINT("):-1].split(" ")
                assert (round(db_row[k], 6), round(db_row[k + 1], 6)) == (float(lon), float(lat))
        for k, name in [(19, "iscalamity"), (20, "to_public")]:
            value = csv_row[header.index(name)]
            assert db_row[k] == (None if value is None else value == "true")
        for k, name in [(21, "submission_date"), (22, "serviced_date"), (23, "last_updated_at")]:
            value = csv_row[header.index(name)]
            assert db_row[k] == (None if value is None else datetime.strptime(value, TS_FORMAT))
    texts = " ".join(r[10] + r[11] for r in db_rows)
    assert "\n" in texts and "\r\n" in texts and '"' in texts and "ñ" in texts and "🙏" in texts


def test_duplicate_microsecond_timestamps_are_preserved(db):
    ties = q(db, f"""SELECT to_char(last_updated_at, 'YYYY-MM-DD HH24:MI:SS.US'), count(*)
                     FROM {S}.requests GROUP BY last_updated_at HAVING count(*) > 1 ORDER BY 1""")
    assert ties == [("2026-08-15 12:34:56.123456", 5), ("2026-09-30 23:59:59.999999", 6),
                    ("2026-10-01 00:00:00.000000", 6)]
    assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE last_updated_at < submission_date") == 8
    assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE last_updated_at = submission_date - interval '1 microsecond'") == 1


def test_archive_window_and_partition_predicates_in_sql(db):
    """The same predicates as archive.export_requests_to_s3, run against the mock table."""
    def window(start, end):
        return q1(db, f"SELECT count(*) FROM {S}.requests WHERE last_updated_at > %s AND last_updated_at <= %s",
                  (start, end))

    total = q1(db, f"SELECT count(*) FROM {S}.requests")
    for tie, size in [("2026-09-30 23:59:59.999999", 6), ("2026-10-01 00:00:00", 6), ("2026-08-15 12:34:56.123456", 5)]:
        before = window("-infinity", tie)
        after = window(tie, "infinity")
        assert before + after == total                      # consecutive runs cut at the tie lose and repeat nothing
        assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE last_updated_at > '-infinity' "
                      f"AND last_updated_at <= %s::timestamp - interval '1 microsecond'", (tie,)) == before - size
    days = q(db, f"""SELECT d::date, (SELECT count(*) FROM {S}.requests
                       WHERE last_updated_at >= d AND last_updated_at < d + interval '1 day')
                     FROM generate_series(date_trunc('day', (SELECT min(last_updated_at) FROM {S}.requests)),
                                          date_trunc('day', (SELECT max(last_updated_at) FROM {S}.requests)),
                                          interval '1 day') d""")
    assert sum(count for _, count in days) == total
    by_day = dict(days)
    assert by_day[datetime(2026, 10, 1).date()] >= 6 and by_day[datetime(2026, 9, 30).date()] >= 6


def test_broken_fk_fixture_fails_with_23503_without_touching_valid_data(db):
    header, rows = read_csv(BROKEN_FK)
    assert len(rows) == 9
    before = q1(db, f"SELECT count(*) FROM {S}.requests")
    failed_columns = set()
    cur = db.cursor()
    for row in rows:
        buffer = io.StringIO()
        csv.writer(buffer, lineterminator="\n").writerow([loader.NULL_TOKEN if v is None else v for v in row])
        buffer.seek(0)
        cur.execute("BEGIN")
        with pytest.raises(psycopg2.errors.ForeignKeyViolation) as err:
            cur.copy_expert(f"COPY {S}.requests ({', '.join(header)}) FROM STDIN "
                            f"WITH (FORMAT csv, NULL '\\N')", buffer)
        assert err.value.pgcode == "23503"
        failed_columns.add(err.value.diag.constraint_name)
        cur.execute("ROLLBACK")
    assert len(failed_columns) == 9  # one distinct foreign key per fixture row
    assert q1(db, f"SELECT count(*) FROM {S}.requests") == before == 500
    assert q1(db, f"SELECT count(*) FROM {S}.requests WHERE req_id LIKE 'REQ-000-000-000-9%'") == 0


@pytest.mark.parametrize("table,id_col,name_col", [
    ("request_for", "req_for_id", "req_for"), ("request_isleadvol", "req_islead_id", "req_islead"),
    ("request_types", "req_type_id", "req_type"), ("request_priorities", "req_priority_id", "req_priority"),
    ("request_statuses", "req_status_id", "req_status"),
])
def test_serial_sequences_continue_after_explicit_ids(db, table, id_col, name_col):
    highest = q1(db, f"SELECT max({id_col}) FROM {S}.{table}")
    cur = db.cursor()
    cur.execute("BEGIN")
    cur.execute(f"INSERT INTO {S}.{table} ({name_col}) VALUES ('TEST_ONLY') RETURNING {id_col}")
    assert cur.fetchone()[0] == highest + 1
    cur.execute("ROLLBACK")
    assert q1(db, f"SELECT count(*) FROM {S}.{table} WHERE {name_col} = 'TEST_ONLY'") == 0
