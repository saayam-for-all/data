import csv
import io
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
LAMBDA_DIR = os.path.join(os.path.dirname(HERE), 'src', 'Data_ArchiveRequestData')
sys.path.insert(0, HERE)
sys.path.insert(0, LAMBDA_DIR)

import archive_request_fixtures as fx  # noqa: E402
import helpers  # noqa: E402
import lambda_function  # noqa: E402

PERSONAL_COLUMNS = {
    'req_id', 'creator_id', 'beneficiary_id', 'lead_volunteer_id', 'req_subj', 'req_desc',
    'req_doc_link', 'audio_req_desc', 'deletion_reason', 'req_loc', 'created_loc',
    'submission_date', 'serviced_date', 'last_updated_at',
}


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[(Bucket, Key)] = Body.decode('utf-8')


def request(req_id, **overrides):
    row = {
        'req_id': req_id, 'creator_id': 'U1', 'beneficiary_id': 'U2', 'lead_volunteer_id': 'U3',
        'req_cat_id': '1.1', 'req_for_id': 0, 'req_islead_id': 1, 'req_type_id': 1,
        'req_priority_id': 2, 'req_status_id': 3, 'req_subj': 'Need groceries',
        'req_desc': 'Call me at 555-0100', 'req_loc': '0101000020E6100000', 'iscalamity': 'false',
        'to_public': 'true', 'submission_date': '2026-03-01 09:00:00',
        'serviced_date': '2026-03-04 18:30:00', 'last_updated_at': '2026-03-04 18:30:00',
    }
    row.update(overrides)
    return row


def small_db(extra_lookup_rows=None):
    conn = fx.new_db()
    fx.insert_requests(conn, [
        request('REQ-1'),
        request('REQ-2', req_cat_id=None, lead_volunteer_id=None, serviced_date=None),
        request('REQ-3', req_status_id=99, creator_id='U-GONE', req_for_id=7),
    ])
    fx.insert_lookup(conn, 'help_categories', [('1.1', 'FOOD_ASSISTANCE')])
    fx.insert_lookup(conn, 'request_for', [(0, 'SELF'), (1, 'OTHER')])
    fx.insert_lookup(conn, 'request_isleadvol', [(0, 'NO'), (1, 'YES')])
    fx.insert_lookup(conn, 'request_types', [(0, 'IN_PERSON'), (1, 'REMOTE')])
    fx.insert_lookup(conn, 'request_priorities', [(0, 'LOW'), (1, 'MEDIUM'), (2, 'HIGH')])
    fx.insert_lookup(conn, 'request_statuses', [(0, 'CREATED'), (3, 'RESOLVED'), (4, 'CANCELLED')])
    fx.insert_users(conn, ['U1', 'U2', 'U3'])
    for table, pairs in (extra_lookup_rows or {}).items():
        fx.insert_lookup(conn, table, pairs)
    conn.commit()
    return conn


@pytest.fixture(autouse=True)
def no_postgres_snapshot(monkeypatch):
    # SET TRANSACTION is postgres only, sqlite has nothing to switch off
    monkeypatch.setattr(helpers, 'SNAPSHOT_SQL', None)


@pytest.fixture
def s3():
    return FakeS3()


@pytest.fixture
def use_db(monkeypatch, s3):
    def _use(conn):
        monkeypatch.setattr(helpers, 'get_connection', lambda: (conn, fx.SCHEMA))
        monkeypatch.setattr(helpers, 'get_s3_client', lambda: s3)
    return _use


def rows_by_id(conn, statuses=None):
    count, rows, problems = helpers.fetch_requests(conn, fx.SCHEMA, statuses)
    return count, {r['req_id']: r for r in rows}, problems


def call(event):
    res = lambda_function.lambda_handler(event, None)
    return res['statusCode'], json.loads(res['body'])


def test_every_lookup_is_a_left_join():
    query = helpers.build_export_query(fx.SCHEMA)
    joins = [line for line in query.splitlines() if 'JOIN' in line]
    assert len(joins) == len(helpers.LOOKUPS) + len(helpers.USER_REFS) == 9
    assert all(line.startswith('LEFT JOIN') for line in joins)


def test_matched_references_become_readable():
    _, rows, _ = rows_by_id(small_db())
    r = rows['REQ-1']
    assert (r['cat_name'], r['req_for'], r['req_islead'], r['req_type'], r['req_priority'], r['req_status']) == \
        ('FOOD_ASSISTANCE', 'SELF', 'YES', 'REMOTE', 'HIGH', 'RESOLVED')
    assert r['req_status_id'] == '3'


def test_null_reference_stays_in_export():
    count, rows, _ = rows_by_id(small_db())
    assert count == len(rows) == 3
    assert rows['REQ-2']['req_cat_id'] is None
    assert rows['REQ-2']['cat_name'] is None
    assert rows['REQ-2']['lead_volunteer_id'] is None


def test_unmatched_reference_stays_in_export_with_raw_id():
    _, rows, _ = rows_by_id(small_db())
    r = rows['REQ-3']
    assert r['req_status_id'] == '99' and r['req_status'] is None
    assert r['creator_id'] == 'U-GONE' and r['creator_id_found'] is None
    shared = helpers.to_shared_row(r)
    assert shared['status'] == '99'
    assert shared['request_for'] == '7'


def test_reference_stats_count_nulls_and_unmatched_separately():
    count, rows, problems = helpers.fetch_requests(small_db(), fx.SCHEMA)
    stats = helpers.reference_stats(rows)
    assert stats['req_cat_id'] == {'references': 'help_categories.cat_id', 'null': 1, 'unmatched': 0}
    assert stats['req_status_id']['unmatched'] == 1
    assert stats['req_for_id']['unmatched'] == 1
    assert stats['creator_id'] == {'references': 'users.user_id', 'null': 0, 'unmatched': 1}
    assert stats['lead_volunteer_id']['null'] == 1
    assert helpers.validate(count, rows, problems) == []


def test_duplicate_lookup_key_is_caught(use_db, s3):
    conn = small_db(extra_lookup_rows={'request_statuses': [(3, 'RESOLVED_AGAIN')]})
    count, rows, problems = helpers.fetch_requests(conn, fx.SCHEMA)
    errors = helpers.validate(count, rows, problems)
    assert 'request_statuses.req_status_id = 3 appears 2 times' in errors
    assert any('duplicate req_id' in e for e in errors)

    use_db(conn)
    status, body = call({'bucket': 'archive-bucket'})
    assert status == 500
    assert body['error'] == 'validation failed'
    assert s3.objects == {}


def test_status_filter_limits_the_export():
    count, rows, _ = rows_by_id(small_db(), statuses=[3])
    assert count == len(rows) == 2
    assert set(rows) == {'REQ-1', 'REQ-2'}


def test_shared_copy_has_no_personal_fields():
    _, rows, _ = rows_by_id(small_db())
    backup_csv, shared_csv = helpers.build_exports(list(rows.values()))
    shared = list(csv.DictReader(io.StringIO(shared_csv)))

    assert not PERSONAL_COLUMNS & set(shared[0])
    for text in ('REQ-1', 'U1', 'U-GONE', 'Need groceries', '555-0100', '0101000020E6100000'):
        assert text not in shared_csv
        assert text in backup_csv
    assert shared[0]['request_month'] == '2026-03'
    assert shared[0]['days_to_service'] == '3'
    assert shared[1]['days_to_service'] == ''
    assert shared[1]['has_lead_volunteer'] == 'false'


def test_handler_writes_backup_and_shared_files(use_db, s3):
    use_db(small_db())
    status, body = call({'body': json.dumps({'bucket': 'backup-bucket', 'shared_bucket': 'shared-bucket'})})
    assert status == 200
    assert body['source_count'] == body['exported_count'] == 3
    assert body['errors'] == []
    assert body['backup']['key'].startswith('request_archive/backup/run_date=')
    assert body['shared']['bucket'] == 'shared-bucket'

    backup = list(csv.DictReader(io.StringIO(s3.objects[('backup-bucket', body['backup']['key'])])))
    shared = list(csv.DictReader(io.StringIO(s3.objects[('shared-bucket', body['shared']['key'])])))
    assert len(backup) == len(shared) == 3
    assert list(backup[0]) == helpers.BACKUP_COLUMNS


@pytest.mark.parametrize('event, message', [
    ({}, 'bucket is required'),
    ({'bucket': ''}, 'bucket is required'),
    ({'bucket': 'b', 'statuses': '3'}, 'statuses must be'),
    ({'bucket': 'b', 'statuses': []}, 'statuses must be'),
    ({'bucket': 'b', 'statuses': [3, 'x']}, 'statuses must be'),
    ({'bucket': 'b', 'statuses': [True]}, 'statuses must be'),
    ({'bucket': 'b', 'shared_bucket': 5}, 'shared_bucket must be'),
    ({'body': '[1, 2]'}, 'JSON object'),
    ({'body': '{not json'}, 'Invalid JSON'),
])
def test_handler_rejects_bad_input(event, message, s3):
    status, body = call(event)
    assert status == 400
    assert message in body['error']
    assert s3.objects == {}


def test_database_failure_returns_500(monkeypatch):
    def broken():
        raise RuntimeError('connection refused')
    monkeypatch.setattr(helpers, 'get_connection', broken)
    status, body = call({'bucket': 'b'})
    assert status == 500
    assert 'connection refused' in body['error']


def test_repo_mock_data_keeps_every_request():
    conn = fx.new_db()
    loaded = fx.load_repo_mock_data(conn)
    count, rows, problems = helpers.fetch_requests(conn, fx.SCHEMA)
    assert count == len(rows) == loaded
    assert helpers.validate(count, rows, problems) == []
    stats = helpers.reference_stats(rows)
    # the mock categories are CAT-FOOD style ids that aren't in help_categories
    assert stats['req_cat_id']['unmatched'] == loaded
