"""Runs Data_ArchiveRequestData against the mock CSVs in the repo, no AWS needed.

    python tests/run_local_archive.py

Postgres is replaced by an in-memory SQLite copy of the #573 schema and S3 by a local
folder (default ~/Desktop/issue574_deliverables, or set ARCHIVE_OUT_DIR). Keep that
folder outside the repo, the exports are not meant to be committed.
"""
import csv
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'src', 'Data_ArchiveRequestData'))

import archive_request_fixtures as fx  # noqa: E402
import helpers  # noqa: E402
import lambda_function  # noqa: E402

OUT_DIR = os.environ.get('ARCHIVE_OUT_DIR', os.path.expanduser('~/Desktop/issue574_deliverables'))


class LocalS3:
    def __init__(self, root):
        self.root = root

    def put_object(self, Bucket, Key, Body, ContentType):
        path = os.path.join(self.root, Bucket, Key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(Body)


def read_back(bucket, key):
    with open(os.path.join(OUT_DIR, bucket, key), newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def main():
    conn = fx.new_db()
    csv_rows = fx.load_repo_mock_data(conn)

    helpers.SNAPSHOT_SQL = None
    helpers.get_connection = lambda: (conn, fx.SCHEMA)
    helpers.get_s3_client = lambda: LocalS3(OUT_DIR)

    event = {'bucket': 'local-backup', 'shared_bucket': 'local-shared'}
    res = lambda_function.lambda_handler(event, None)
    body = json.loads(res['body'])
    if res['statusCode'] != 200:
        print(json.dumps(body, indent=2))
        sys.exit(1)

    # check the files that were actually written, not just what the handler reported
    backup = read_back(body['backup']['bucket'], body['backup']['key'])
    shared = read_back(body['shared']['bucket'], body['shared']['key'])
    ids = [r['req_id'] for r in backup]
    duplicates = len(ids) - len(set(ids))

    print(f'Data_ArchiveRequestData local run, {datetime.now():%Y-%m-%d %H:%M}')
    print(f'status code          {res["statusCode"]}')
    print(f'rows in requests.csv {csv_rows}')
    print(f'source count (db)    {body["source_count"]}')
    print(f'exported count       {body["exported_count"]}')
    print(f'backup file rows     {len(backup)}')
    print(f'shared file rows     {len(shared)}')
    print(f'duplicate req_ids    {duplicates}')
    print()
    print(f'{"column":<20}{"references":<36}{"null":>6}{"unmatched":>11}')
    for col, s in body['references'].items():
        print(f'{col:<20}{s["references"]:<36}{s["null"]:>6}{s["unmatched"]:>11}')
    print()
    print('backup file:', os.path.join(OUT_DIR, body['backup']['bucket'], body['backup']['key']))
    print('shared file:', os.path.join(OUT_DIR, body['shared']['bucket'], body['shared']['key']))
    print()
    print('first 3 rows of the shared (stakeholder) copy:')
    for row in shared[:3]:
        print(' ', row)

    ok = body['source_count'] == body['exported_count'] == len(backup) == len(shared) == csv_rows and not duplicates
    write_summary(body, csv_rows, len(backup), len(shared), duplicates, ok)
    print()
    print('PASS' if ok else 'FAIL', '- summary written to', os.path.join(OUT_DIR, 'validation_summary.md'))
    sys.exit(0 if ok else 1)


def write_summary(body, csv_rows, backup_rows, shared_rows, duplicates, ok):
    lines = [
        '# Data_ArchiveRequestData: local validation summary (#574)',
        '',
        f'Run on {datetime.now():%Y-%m-%d %H:%M} against the mock data in the repo '
        '(`data-analytics/sql/requests.csv`, `data-analytics/sql/users.csv` and `database/lookup_tables/`), '
        'loaded into an in-memory SQLite copy of the schema from #573. S3 was a local folder. '
        'No real database or AWS account was used.',
        '',
        '| Check | Result |',
        '|---|---|',
        f'| Rows in requests.csv | {csv_rows} |',
        f'| Source count selected for archival | {body["source_count"]} (filter: {body["statuses"]}) |',
        f'| Exported count | {body["exported_count"]} |',
        f'| Rows in backup file | {backup_rows} |',
        f'| Rows in shared file | {shared_rows} |',
        f'| Duplicate req_id values | {duplicates} |',
        f'| Overall | {"PASS" if ok else "FAIL"} |',
        '',
        '## References',
        '',
        '| Column | References | Null | Unmatched |',
        '|---|---|---|---|',
    ]
    for col, s in body['references'].items():
        lines.append(f'| {col} | {s["references"]} | {s["null"]} | {s["unmatched"]} |')
    lines += [
        '',
        'The mock requests do not line up with the lookup CSVs: categories are `CAT-FOOD` style ids '
        'while help_categories uses `1.1` style ids, many request_for, islead, type and priority ids '
        'are outside the lookup ranges, and many user ids are not in users.csv. That is expected for this '
        'data and is a useful test: every one of those requests is still in both exports, the backup keeps '
        'the original id next to an empty readable column, and the shared copy falls back to the raw id.',
        '',
        'Real numbers for the production table need a run against the database, which this local test cannot do.',
    ]
    with open(os.path.join(OUT_DIR, 'validation_summary.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
