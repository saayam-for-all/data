from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "review_api", ROOT / "lambda_functions/steward_volunteer_review_api.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


def render(query):
    if isinstance(query, sql.SQL):
        return query.string
    if isinstance(query, sql.Identifier):
        return '.'.join('"' + part.replace('"', '""') + '"' for part in query.strings)
    return ''.join(render(part) for part in query.seq)


class LocalCursor:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters):
        statuses, limit, offset = parameters
        query = render(query).replace('= ANY(%s)', 'IN (' + ','.join('?' for _ in statuses) + ')')
        self.cursor = self.connection.execute(query.replace('%s', '?'), (*statuses, limit, offset))

    def fetchall(self):
        return [(user, datetime.fromisoformat(updated) if updated else None, total)
                for user, updated, total in self.cursor.fetchall()]


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE users (user_id TEXT PRIMARY KEY);
            CREATE TABLE volunteer_applications (
                user_id TEXT PRIMARY KEY, application_status TEXT, last_updated_at TEXT);
            INSERT INTO users VALUES ('a'), ('b'), ('c'), ('d'), ('e'), ('f');
            INSERT INTO volunteer_applications VALUES
                ('a', 'SUBMITTED', '2026-05-12T07:15:00'),
                ('b', 'SUBMITTED', '2026-05-13T07:15:00'),
                ('c', 'UNDER_REVIEW', '2026-05-13T07:15:00'),
                ('d', 'ACCEPTED', '2026-05-14T07:15:00'),
                ('e', 'DRAFT', '2026-05-14T07:15:00'),
                ('f', 'SUBMITTED', NULL),
                ('orphan', 'SUBMITTED', '2026-05-15T07:15:00');
        ''')

    def queue(self, page=1, size=2, statuses=None):
        return api.get_review_queue(LocalCursor(self.db), 'main',
                                    statuses or ['SUBMITTED', 'UNDER_REVIEW'], page, size)

    def test_filter_join_order_and_pages(self):
        first = self.queue()
        self.assertEqual([r['user_id'] for r in first['data']], ['b', 'c'])
        self.assertEqual(first['pagination'], dict(current_page=1, page_size=2, total_records=4, total_pages=2))
        second = self.queue(page=2)
        self.assertEqual(second['data'], [
            dict(user_id='a', updated_time='2026-05-12T07:15:00Z', volunteer_review='Review'),
            dict(user_id='f', updated_time=None, volunteer_review='Review')])
        self.assertEqual(len(self.queue(size=3)['data']), 3)
        self.assertEqual(self.queue(size=3)['pagination']['total_pages'], 2)
        self.assertEqual([r['user_id'] for r in self.queue(size=100, statuses=['SUBMITTED'])['data']], ['b', 'a', 'f'])

    def test_empty_and_out_of_range(self):
        result = self.queue(statuses=['NO_MATCH'])
        self.assertEqual(result['data'], [])
        self.assertEqual(result['pagination']['total_pages'], 0)
        result = self.queue(page=20)
        self.assertEqual(result['data'], [])
        self.assertEqual(result['pagination']['total_records'], 4)

    def test_status_is_bound_not_interpolated(self):
        self.assertEqual(self.queue(statuses=["SUBMITTED') OR 1=1 --"])['data'], [])
        cursor = MagicMock()
        cursor.fetchall.return_value = [(None, None, 0)]
        api.get_review_queue(cursor, 'schema"name', ['SUBMITTED'], 3, 5)
        query, params = cursor.execute.call_args.args
        self.assertEqual(params, (['SUBMITTED'], 5, 10))
        self.assertIn('"schema""name"."users"', render(query))
        self.assertNotIn('SUBMITTED', render(query))


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'DB_SCHEMA': 'test', 'STEWARD_REVIEW_STATUSES': '["SUBMITTED"]',
            'DB_CONFIG_PARAMETER': '/test/config'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.connect = patch.object(api, 'get_db_connection')
        self.mock_connect = self.connect.start()
        self.addCleanup(self.connect.stop)
        self.connection = self.mock_connect.return_value
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.cursor.fetchall.return_value = [('id', datetime(2026, 5, 12, 7, 15), 1)]

    def test_direct_and_gateway_bodies(self):
        for event in ({}, {'body': '{"page":1,"page_size":5}'}, {'body': {'page': 1}}):
            with self.subTest(event=event):
                result = api.lambda_handler(event, None)
                self.assertEqual(result['statusCode'], 200)
                self.assertEqual(result['body']['data'][0]['updated_time'], '2026-05-12T07:15:00Z')
        self.connection.set_session.assert_called_with(readonly=True)
        self.connection.close.assert_called()
        self.connection.cursor.return_value.__exit__.assert_called()

    def test_invalid_input_does_not_connect(self):
        for event in (None, [], {'body': 'oops'}, {'body': '[]'}, {'body': None},
                      {'page': True}, {'page': 0}, {'page': '1'}, {'page': 1.5},
                      {'page_size': 0}, {'page_size': 101}, {'page_size': False},
                      {'page': 10**30}):
            with self.subTest(event=event):
                self.assertEqual(api.lambda_handler(event, None)['statusCode'], 400)
        self.mock_connect.assert_not_called()

    def test_safe_database_errors_and_cleanup(self):
        self.cursor.execute.side_effect = RuntimeError('secret password SQL hostname')
        with self.assertLogs(api.LOGGER) as logs:
            result = api.lambda_handler({}, None)
        self.assertEqual(result['statusCode'], 500)
        self.assertNotIn('secret', json.dumps(result) + str(logs.output))
        self.connection.close.assert_called_once()
        self.connection.cursor.return_value.__exit__.assert_called_once()

    def test_missing_or_invalid_status_configuration(self):
        for value in ('[]', 'null', '"SUBMITTED"', '[""]', '[1]', 'invalid'):
            with patch.dict(os.environ, STEWARD_REVIEW_STATUSES=value), self.assertLogs(api.LOGGER):
                self.assertEqual(api.lambda_handler({}, None)['statusCode'], 500)
        with patch.dict(os.environ, {}, clear=True), self.assertLogs(api.LOGGER):
            self.assertEqual(api.lambda_handler({}, None)['statusCode'], 500)
        self.mock_connect.assert_not_called()

    def test_connection_failure_is_safe(self):
        self.mock_connect.side_effect = RuntimeError('secret connection details')
        with self.assertLogs(api.LOGGER) as logs:
            result = api.lambda_handler({}, None)
        self.assertEqual(result['statusCode'], 500)
        self.assertNotIn('secret', json.dumps(result) + str(logs.output))

    def test_blank_schema_does_not_connect(self):
        with patch.dict(os.environ, DB_SCHEMA=' '), self.assertLogs(api.LOGGER):
            self.assertEqual(api.lambda_handler({}, None)['statusCode'], 500)
        self.mock_connect.assert_not_called()

    def test_duplicate_statuses_are_removed(self):
        with patch.dict(os.environ, STEWARD_REVIEW_STATUSES='["SUBMITTED", "SUBMITTED"]'):
            self.assertEqual(api.get_review_statuses(), ['SUBMITTED'])

    def test_empty_success(self):
        self.cursor.fetchall.return_value = [(None, None, 0)]
        result = api.lambda_handler({}, None)
        self.assertEqual(result['statusCode'], 200)
        self.assertEqual(result['body']['data'], [])

    def test_timezone_conversion(self):
        value = datetime(2026, 5, 12, 9, 15, tzinfo=timezone(timedelta(hours=2)))
        self.assertEqual(api.format_updated_time(value), '2026-05-12T07:15:00Z')


class ConnectionTests(unittest.TestCase):
    @patch.object(api.psycopg2, 'connect')
    @patch.object(api.boto3, 'client')
    def test_ssm_configuration(self, client, connect):
        client.return_value.get_parameter.return_value = {'Parameter': {'Value': json.dumps({
            'HOST': 'example', 'PORT': 5432, 'DATABASE NAME': 'db',
            'USERNAME': 'user', 'PASSWORD': 'test-only'})}}
        with patch.dict(os.environ, DB_CONFIG_PARAMETER='/configured/path'):
            api.get_db_connection()
        client.assert_called_once_with('ssm')
        client.return_value.get_parameter.assert_called_once_with(Name='/configured/path', WithDecryption=True)
        self.assertEqual(connect.call_args.kwargs['sslmode'], 'require')
        self.assertEqual(connect.call_args.kwargs['dbname'], 'db')


if __name__ == '__main__':
    unittest.main()
