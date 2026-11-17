import csv
import json
import os
import sys

import psycopg2
import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "Data_ArchiveRequestData"))
import lambda_function as archive  # noqa: E402
from archive_request_data_fixture import SCHEMA, local_postgres  # noqa: E402

pytestmark = pytest.mark.skipif(
    not any(os.path.exists(os.path.join(b, "initdb")) for b in
            ("/opt/homebrew/opt/postgresql@16/bin", "/usr/lib/postgresql/16/bin")),
    reason="local PostgreSQL 16 binaries not found",
)


@pytest.fixture(scope="module")
def db():
    with local_postgres() as settings:
        yield settings


@pytest.fixture
def run(db, tmp_path, monkeypatch):
    for key, value in db.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("LOCAL_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("S3_BUCKET", raising=False)

    def invoke(event=None):
        response = archive.lambda_handler(event or {}, None)
        body = json.loads(response["body"])
        rows = []
        if response["statusCode"] == 200:
            with open(body["local_path"], newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
        return response["statusCode"], body, rows

    return invoke


def test_all_requests_exported_once(run):
    status, body, rows = run()
    assert status == 200
    assert body["source_count"] == body["exported_count"] == len(rows) == 8
    assert body["duplicate_requests"] == 0
    assert len({r["req_id"] for r in rows}) == 8


def test_header_has_readable_columns_and_no_raw_ids(run):
    _, _, rows = run()
    assert list(rows[0]) == archive.output_columns()
    for raw in ("creator_id", "beneficiary_id", "lead_volunteer_id", "req_cat_id", "req_for_id",
                "req_islead_id", "req_type_id", "req_priority_id", "req_status_id"):
        assert raw not in rows[0]


def test_references_replaced_with_readable_values(run):
    _, _, rows = run()
    r = {row["req_id"]: row for row in rows}
    assert r["REQ-000-000-000-0003"]["creator_name"] == "Ben Carter"
    assert r["REQ-000-000-000-0003"]["lead_volunteer_name"] == "Chen Li"
    assert r["REQ-000-000-000-0003"]["help_category"] == "Housing"
    assert r["REQ-000-000-000-0003"]["request_for"] == "OTHER"
    assert r["REQ-000-000-000-0003"]["is_lead_volunteer"] == "YES"
    assert r["REQ-000-000-000-0003"]["request_type"] == "REMOTE"
    assert r["REQ-000-000-000-0003"]["request_priority"] == "CRITICAL"
    assert r["REQ-000-000-000-0003"]["request_status"] == "IN_PROGRESS"
    assert r["REQ-000-000-000-0001"]["req_loc"] == "POINT(-122.4 37.8)"


def test_null_references_are_kept(run, db):
    _, _, rows = run()
    assert sum(1 for r in rows if r["lead_volunteer_name"] == "") == 6
    assert sum(1 for r in rows if r["beneficiary_name"] == "") == 2
    # An INNER JOIN on lead_volunteer_id would silently keep only 2 of the 8 requests.
    conn = psycopg2.connect(host=db["DB_HOST"], port=db["DB_PORT"], dbname="postgres", user="postgres")
    with conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.requests r JOIN {SCHEMA}.users u "
                    "ON u.user_id = r.lead_volunteer_id")
        assert cur.fetchone()[0] == 2
    conn.close()


def test_csv_escaping_round_trips(run):
    _, _, rows = run()
    subject = next(r for r in rows if r["req_id"] == "REQ-000-000-000-0006")["req_subj"]
    assert subject == 'Food, "urgent"\nplease'


def test_every_lookup_is_a_left_join_on_a_primary_key(db):
    where, _ = archive.build_where({})
    export, _ = archive.build_queries(SCHEMA, where)
    conn = psycopg2.connect(host=db["DB_HOST"], port=db["DB_PORT"], dbname="postgres", user="postgres")
    text = export.as_string(conn)
    conn.close()
    assert text.count("LEFT JOIN") == 9
    assert " JOIN " not in text.replace("LEFT JOIN", "")


def test_last_updated_window(run):
    _, body, rows = run({"last_updated_from": "2026-01-20T00:00:00", "last_updated_to": "2026-02-03T00:00:00"})
    assert body["source_count"] == body["exported_count"] == 3
    assert [r["req_id"] for r in rows] == ["REQ-000-000-000-0004", "REQ-000-000-000-0005", "REQ-000-000-000-0006"]


def test_invalid_window_is_400(run):
    assert run({"last_updated_from": "not-a-date"})[0] == 400
    assert run({"last_updated_from": "2026-02-01", "last_updated_to": "2026-01-01"})[0] == 400


def test_export_is_read_only(db):
    conn = psycopg2.connect(host=db["DB_HOST"], port=db["DB_PORT"], dbname="postgres", user="postgres")
    with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {SCHEMA}.requests")
    conn.close()


def test_s3_upload(run, monkeypatch):
    uploads = []

    class FakeS3:
        def upload_file(self, path, bucket, key):
            uploads.append((os.path.exists(path), bucket, key))

    import types
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda name: FakeS3()))
    monkeypatch.setenv("S3_BUCKET", "archive-bucket")
    status, body, _ = run()
    assert status == 200
    assert uploads[0][:2] == (True, "archive-bucket")
    assert body["s3_uri"].startswith("s3://archive-bucket/requests/requests_enriched_")
