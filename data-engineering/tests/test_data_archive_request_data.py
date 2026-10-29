import csv
import io
import json
import os
import sys
from datetime import datetime, timedelta

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
LAMBDA_DIR = os.path.join(os.path.dirname(HERE), 'src', 'Data_ArchiveRequestData')
sys.path.insert(0, HERE)
sys.path.insert(0, LAMBDA_DIR)

import archive_request_fixtures as fx  # noqa: E402
import helpers  # noqa: E402
import lambda_function  # noqa: E402

NOW = datetime(2026, 3, 10, 12, 0, 0)
BUCKET = 'archive-bucket'
STATE_KEY = 'request_archive/_state/watermark.json'


class NoSuchKey(Exception):
    response = {'Error': {'Code': 'NoSuchKey'}}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.fail_csv_upload = False

    def put_object(self, Bucket, Key, Body, ContentType):
        if self.fail_csv_upload and Key.endswith('.csv'):
            raise RuntimeError('upload failed')
        self.objects[(Bucket, Key)] = Body.decode('utf-8')

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise NoSuchKey()
        return {'Body': io.BytesIO(self.objects[(Bucket, Key)].encode('utf-8'))}

    def csv_files(self):
        return {k: v for (b, k), v in self.objects.items() if k.endswith('.csv')}

    def watermark(self):
        doc = self.objects.get((BUCKET, STATE_KEY))
        return json.loads(doc)['last_updated_at'] if doc else None


def request(req_id, **overrides):
    row = {
        'req_id': req_id, 'creator_id': 'U1', 'beneficiary_id': 'U2', 'lead_volunteer_id': 'U3',
        'req_cat_id': '1.1', 'req_for_id': 0, 'req_islead_id': 1, 'req_type_id': 1,
        'req_priority_id': 2, 'req_status_id': 3, 'req_subj': 'Need groceries',
        'req_desc': 'Weekly shopping help', 'req_loc': '0101000020E6100000', 'iscalamity': 'false',
        'to_public': 'false', 'submission_date': '2026-03-01 09:00:00',
        'serviced_date': '2026-03-04 18:30:00', 'last_updated_at': '2026-03-04 18:30:00',
    }
    row.update(overrides)
    return row


def small_db(extra_lookup_rows=None):
    conn = fx.new_db()
    fx.insert_requests(conn, [
        request('REQ-1'),
        request('REQ-2', req_cat_id=None, lead_volunteer_id=None, last_updated_at='2026-03-05 08:00:00'),
        request('REQ-3', req_status_id=99, req_for_id=7, last_updated_at='2026-03-06 10:15:00'),
    ])
    fx.insert_lookup(conn, 'help_categories', [('1.1', 'FOOD_ASSISTANCE')])
    fx.insert_lookup(conn, 'request_for', [(0, 'SELF'), (1, 'OTHER')])
    fx.insert_lookup(conn, 'request_isleadvol', [(0, 'NO'), (1, 'YES')])
    fx.insert_lookup(conn, 'request_types', [(0, 'IN_PERSON'), (1, 'REMOTE')])
    fx.insert_lookup(conn, 'request_priorities', [(0, 'LOW'), (1, 'MEDIUM'), (2, 'HIGH')])
    fx.insert_lookup(conn, 'request_statuses', [(0, 'CREATED'), (3, 'RESOLVED'), (4, 'CANCELLED')])
    for table, pairs in (extra_lookup_rows or {}).items():
        fx.insert_lookup(conn, table, pairs)
    conn.commit()
    return conn


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    clock = {'now': NOW}
    monkeypatch.setattr(helpers, 'utc_now', lambda: clock['now'])
    # SET TRANSACTION is postgres only, sqlite has nothing to switch off
    monkeypatch.setattr(helpers, 'SNAPSHOT_SQL', None)
    monkeypatch.delenv('BUCKET', raising=False)
    monkeypatch.delenv('S3_PREFIX', raising=False)
    return clock


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(helpers, 'get_s3_client', lambda: fake)
    return fake


@pytest.fixture
def use_db(monkeypatch):
    def _use(conn):
        monkeypatch.setattr(helpers, 'get_connection', lambda: (conn, fx.SCHEMA))
        return conn
    return _use


def call(event):
    res = lambda_function.lambda_handler(event, None)
    return res['statusCode'], json.loads(res['body'])


def exported_rows(s3, key):
    return list(csv.DictReader(io.StringIO(s3.objects[(BUCKET, key)])))


def window(conn, lo='2000-01-01 00:00:00', hi='2030-01-01 00:00:00'):
    count, rows, problems, missing = helpers.fetch_window(conn, fx.SCHEMA, lo, hi)
    return count, {r['req_id']: r for r in rows}, problems


def test_only_the_six_lookups_are_joined_and_all_are_left_joins():
    query = helpers.build_export_query(fx.SCHEMA, '2000-01-01', '2030-01-01')
    joins = [line for line in query.splitlines() if 'JOIN' in line]
    assert len(joins) == 6
    assert all(line.startswith('LEFT JOIN') for line in joins)
    assert 'users' not in query


def test_ids_are_kept_next_to_readable_values():
    _, rows, _ = window(small_db())
    r = rows['REQ-1']
    assert (r['req_status_id'], r['req_status']) == ('3', 'RESOLVED')
    assert (r['req_cat_id'], r['cat_name']) == ('1.1', 'FOOD_ASSISTANCE')
    assert (r['req_for'], r['req_islead'], r['req_type'], r['req_priority']) == ('SELF', 'YES', 'REMOTE', 'HIGH')
    assert helpers.EXPORT_COLUMNS.index('req_status') == helpers.EXPORT_COLUMNS.index('req_status_id') + 1


def test_raw_user_ids_and_text_are_exported_as_they_are():
    _, rows, _ = window(small_db())
    r = rows['REQ-1']
    assert (r['creator_id'], r['beneficiary_id'], r['lead_volunteer_id']) == ('U1', 'U2', 'U3')
    assert r['req_desc'] == 'Weekly shopping help'


def test_null_reference_stays_in_export():
    count, rows, _ = window(small_db())
    assert count == len(rows) == 3
    assert rows['REQ-2']['req_cat_id'] is None and rows['REQ-2']['cat_name'] is None


def test_unmatched_reference_stays_in_export_with_its_id():
    _, rows, _ = window(small_db())
    r = rows['REQ-3']
    assert r['req_status_id'] == '99' and r['req_status'] is None
    assert r['req_for_id'] == '7' and r['req_for'] is None


def test_reference_stats_count_nulls_and_unmatched_separately():
    count, rows, problems, _ = helpers.fetch_window(small_db(), fx.SCHEMA, '2000-01-01', '2030-01-01')
    stats = helpers.reference_stats(rows)
    assert stats['req_cat_id'] == {'references': 'help_categories.cat_id', 'null': 1, 'unmatched': 0}
    assert stats['req_status_id'] == {'references': 'request_statuses.req_status_id', 'null': 0, 'unmatched': 1}
    assert stats['req_for_id']['unmatched'] == 1
    assert helpers.validate(count, rows, problems) == []


def test_duplicate_lookup_key_is_caught_and_nothing_is_written(use_db, s3):
    use_db(small_db(extra_lookup_rows={'request_statuses': [(3, 'RESOLVED_AGAIN')]}))
    status, body = call({'bucket': BUCKET})
    assert status == 500
    assert 'request_statuses.req_status_id = 3 appears 2 times' in body['errors']
    assert any('duplicate req_id' in e for e in body['errors'])
    assert s3.objects == {}


def test_first_run_exports_everything_and_sets_the_watermark(use_db, s3):
    use_db(small_db())
    status, body = call({'bucket': BUCKET})
    assert status == 200 and body['status'] == 'success'
    assert body['source_count'] == body['exported_count'] == 3
    assert body['range_from'] == '2000-01-01 00:00:00'
    assert body['range_to'] == str(NOW - timedelta(minutes=5))
    assert body['s3_key'].startswith('request_archive/requests/ingest_date=2026-03-10/requests_20000101T000000_')

    rows = exported_rows(s3, body['s3_key'])
    assert [r['req_id'] for r in rows] == ['REQ-1', 'REQ-2', 'REQ-3']
    assert list(rows[0]) == helpers.EXPORT_COLUMNS
    assert s3.watermark().startswith('2026-03-10 11:55:00')


def test_second_run_with_no_changes_has_nothing_to_do(use_db, s3, fixed_clock):
    use_db(small_db())
    call({'bucket': BUCKET})
    first_watermark = s3.watermark()

    fixed_clock['now'] = NOW + timedelta(hours=1)
    status, body = call({'bucket': BUCKET})
    assert status == 200 and body['status'] == 'nothing_to_do'
    assert len(s3.csv_files()) == 1
    assert s3.watermark() == first_watermark


def test_updated_row_is_exported_again(use_db, s3, fixed_clock):
    conn = use_db(small_db())
    call({'bucket': BUCKET})

    conn.execute(f"UPDATE {fx.SCHEMA}.requests SET req_status_id = 4, "
                 "last_updated_at = '2026-03-10 12:30:00' WHERE req_id = 'REQ-1'")
    conn.commit()
    fixed_clock['now'] = NOW + timedelta(hours=1)
    status, body = call({'bucket': BUCKET})

    assert status == 200 and body['exported_count'] == 1
    rows = exported_rows(s3, body['s3_key'])
    assert rows[0]['req_id'] == 'REQ-1' and rows[0]['req_status'] == 'CANCELLED'
    # both versions are now in S3, which is the history
    assert len(s3.csv_files()) == 2


def test_row_inside_the_lag_waits_for_the_next_run(use_db, s3, fixed_clock):
    conn = use_db(small_db())
    fx.insert_requests(conn, [request('REQ-4', last_updated_at='2026-03-10 11:58:00')])
    conn.commit()

    _, body = call({'bucket': BUCKET})
    assert body['exported_count'] == 3

    fixed_clock['now'] = NOW + timedelta(minutes=10)
    _, body = call({'bucket': BUCKET})
    assert body['exported_count'] == 1
    assert exported_rows(s3, body['s3_key'])[0]['req_id'] == 'REQ-4'


def test_failed_upload_does_not_move_the_watermark(use_db, s3):
    use_db(small_db())
    s3.fail_csv_upload = True
    status, body = call({'bucket': BUCKET})
    assert status == 500 and 'upload failed' in body['error']
    assert s3.watermark() is None

    s3.fail_csv_upload = False
    status, body = call({'bucket': BUCKET})
    assert status == 200 and body['exported_count'] == 3


def test_explicit_range_does_not_touch_the_watermark(use_db, s3):
    use_db(small_db())
    status, body = call({'bucket': BUCKET, 'from': '2026-03-05 00:00:00', 'to': '2026-03-07 00:00:00'})
    assert status == 200 and body['explicit_range'] is True
    assert {r['req_id'] for r in exported_rows(s3, body['s3_key'])} == {'REQ-2', 'REQ-3'}
    assert s3.watermark() is None


def test_row_on_a_window_boundary_lands_in_exactly_one_window(use_db, s3):
    conn = use_db(small_db())
    fx.insert_requests(conn, [request('REQ-EDGE', last_updated_at='2026-03-08 00:00:00.000000')])
    conn.commit()
    seen = []
    for lo, hi in (('2026-03-07 00:00:00', '2026-03-08 00:00:00'), ('2026-03-08 00:00:00', '2026-03-09 00:00:00')):
        _, rows, _ = window(conn, lo, hi)
        seen += list(rows)
    assert seen.count('REQ-EDGE') == 1


def test_rows_without_last_updated_at_are_reported(use_db, s3):
    conn = use_db(small_db())
    fx.insert_requests(conn, [request('REQ-NULL', last_updated_at=None)])
    conn.commit()
    _, body = call({'bucket': BUCKET})
    assert body['rows_without_last_updated_at'] == 1


def test_bucket_can_come_from_the_environment(use_db, s3, monkeypatch):
    use_db(small_db())
    monkeypatch.setenv('BUCKET', BUCKET)
    status, body = call({})
    assert status == 200 and (BUCKET, body['s3_key']) in s3.objects


@pytest.mark.parametrize('event, message', [
    ({}, 'bucket is required'),
    ({'bucket': ''}, 'bucket is required'),
    ({'bucket': 'b', 'prefix': 5}, 'prefix must be'),
    ({'bucket': 'b', 'from': '2026-01-01'}, 'sent together'),
    ({'bucket': 'b', 'from': 'yesterday', 'to': '2026-01-02'}, 'must be timestamps'),
    ({'bucket': 'b', 'from': '2026-02-01', 'to': '2026-01-01'}, 'cannot be after'),
    ({'body': '[1, 2]'}, 'JSON object'),
    ({'body': '{not json'}, 'Invalid JSON'),
])
def test_handler_rejects_bad_input(event, message, s3):
    status, body = call(event)
    assert status == 400
    assert message in body['error']
    assert s3.objects == {}


def test_database_failure_returns_500(monkeypatch, s3):
    def broken():
        raise RuntimeError('connection refused')
    monkeypatch.setattr(helpers, 'get_connection', broken)
    status, body = call({'bucket': BUCKET})
    assert status == 500 and 'connection refused' in body['error']


def test_repo_mock_data_keeps_every_request(use_db, s3):
    conn = use_db(fx.new_db())
    loaded = fx.load_repo_mock_data(conn)
    status, body = call({'bucket': BUCKET, 'from': '2000-01-01 00:00:00', 'to': '2030-01-01 00:00:00'})
    assert status == 200
    assert body['source_count'] == body['exported_count'] == loaded
    rows = exported_rows(s3, body['s3_key'])
    assert len({r['req_id'] for r in rows}) == loaded
    # the mock categories are CAT-FOOD style ids that aren't in help_categories
    assert body['references']['req_cat_id']['unmatched'] == loaded
