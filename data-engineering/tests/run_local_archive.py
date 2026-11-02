"""Runs Data_ArchiveRequestData against the mock CSVs in the repo, no AWS needed.

    python tests/run_local_archive.py

Postgres is replaced by an in-memory SQLite copy of the #573 schema and S3 by a local
folder (default ~/Desktop/issue574_deliverables, or set ARCHIVE_OUT_DIR). Keep that
folder outside the repo, the exports are not meant to be committed.

It does three runs to show the watermark: a first run that exports everything, a
second run with nothing new, and a third run after one request has been updated.
"""
import csv
import io
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'src', 'Data_ArchiveRequestData'))

import archive_request_fixtures as fx  # noqa: E402
import helpers  # noqa: E402
import lambda_function  # noqa: E402

OUT_DIR = os.environ.get('ARCHIVE_OUT_DIR', os.path.expanduser('~/Desktop/issue574_deliverables'))
BUCKET = 'local-archive-bucket'


class LocalS3:
    def __init__(self, root):
        self.root = root

    def path(self, bucket, key):
        return os.path.join(self.root, bucket, key)

    def put_object(self, Bucket, Key, Body, ContentType):
        os.makedirs(os.path.dirname(self.path(Bucket, Key)), exist_ok=True)
        with open(self.path(Bucket, Key), 'wb') as f:
            f.write(Body)

    def get_object(self, Bucket, Key):
        try:
            with open(self.path(Bucket, Key), 'rb') as f:
                return {'Body': io.BytesIO(f.read())}
        except FileNotFoundError:
            err = Exception('NoSuchKey')
            err.response = {'Error': {'Code': 'NoSuchKey'}}
            raise err


def run(label):
    res = lambda_function.lambda_handler({'bucket': BUCKET}, None)
    body = json.loads(res['body'])
    print(f'{label}: status {res["statusCode"]} {body.get("status")}, window ({body.get("range_from")}, '
          f'{body.get("range_to")}], source {body.get("source_count")}, exported {body.get("exported_count")}')
    if res['statusCode'] != 200:
        print(json.dumps(body, indent=2))
        sys.exit(1)
    return body


def main():
    archive_root = os.path.join(OUT_DIR, BUCKET)
    shutil.rmtree(archive_root, ignore_errors=True)
    s3 = LocalS3(OUT_DIR)

    conn = fx.new_db()
    csv_rows = fx.load_repo_mock_data(conn)
    clock = {'now': datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)}

    helpers.SNAPSHOT_SQL = None
    helpers.utc_now = lambda: clock['now']
    helpers.get_connection = lambda: (conn, fx.SCHEMA)
    helpers.get_s3_client = lambda: s3

    print(f'Data_ArchiveRequestData local run, {clock["now"]:%Y-%m-%d %H:%M} UTC, {csv_rows} rows in requests.csv')
    print()
    first = run('run 1')
    second = run('run 2')

    # someone cancels a request a few minutes later
    updated_at = clock['now'] + timedelta(minutes=3)
    conn.execute(f"UPDATE {fx.SCHEMA}.requests SET req_status_id = 4, last_updated_at = ? "
                 "WHERE req_id = 'REQ-000002'", (updated_at.strftime('%Y-%m-%d %H:%M:%S.000'),))
    conn.commit()
    clock['now'] += timedelta(minutes=15)
    third = run('run 3')

    full = list(csv.DictReader(open(s3.path(BUCKET, first['s3_key']), newline='', encoding='utf-8')))
    change = list(csv.DictReader(open(s3.path(BUCKET, third['s3_key']), newline='', encoding='utf-8')))
    ids = [r['req_id'] for r in full]
    duplicates = len(ids) - len(set(ids))

    print()
    print(f'rows in first export file  {len(full)}')
    print(f'duplicate req_ids          {duplicates}')
    print(f'watermark after run 3      {json.load(open(s3.path(BUCKET, helpers.state_key("request_archive"))))}')
    print()
    print(f'{"column":<18}{"references":<36}{"null":>6}{"unmatched":>11}')
    for col, s in first['references'].items():
        print(f'{col:<18}{s["references"]:<36}{s["null"]:>6}{s["unmatched"]:>11}')
    print()
    print('first 2 rows of run 1, id and readable columns:')
    for row in full[:2]:
        print(' ', {c: row[c] for c in helpers.EXPORT_COLUMNS[:13]})
    print('run 3 picked up:', {c: change[0][c] for c in ('req_id', 'req_status_id', 'req_status', 'last_updated_at')})

    ok = (first['source_count'] == first['exported_count'] == len(full) == csv_rows and not duplicates
          and second['status'] == 'nothing_to_do'
          and third['exported_count'] == 1 and change[0]['req_status'] == 'CANCELLED')
    write_summary(first, second, third, csv_rows, len(full), duplicates, ok)
    print()
    print('files in', archive_root)
    for folder, _, files in sorted(os.walk(archive_root)):
        for name in sorted(files):
            print(' ', os.path.relpath(os.path.join(folder, name), archive_root))
    print()
    print('PASS' if ok else 'FAIL', '- summary written to', os.path.join(OUT_DIR, 'validation_summary.md'))
    sys.exit(0 if ok else 1)


def write_summary(first, second, third, csv_rows, file_rows, duplicates, ok):
    lines = [
        '# Data_ArchiveRequestData: local validation summary (#574)',
        '',
        f'Run on {datetime.now():%Y-%m-%d %H:%M} against the mock data in the repo '
        '(`data-analytics/sql/requests.csv` and `database/lookup_tables/`), loaded into an in-memory '
        'SQLite copy of the schema from #573. S3 was a local folder. No real database or AWS account was used.',
        '',
        '## Counts',
        '',
        '| Check | Result |',
        '|---|---|',
        f'| Rows in requests.csv | {csv_rows} |',
        f'| Run 1 source count (rows in the window) | {first["source_count"]} |',
        f'| Run 1 exported count | {first["exported_count"]} |',
        f'| Rows in the run 1 file | {file_rows} |',
        f'| Duplicate req_id values | {duplicates} |',
        f'| Rows with no last_updated_at (cannot be windowed) | {first["rows_without_last_updated_at"]} |',
        f'| Run 2, nothing changed | {second["status"]}, {second["exported_count"]} rows |',
        f'| Run 3, after one request was cancelled | {third["exported_count"]} row '
        f'({third["s3_key"].split("/")[-1]}) |',
        f'| Overall | {"PASS" if ok else "FAIL"} |',
        '',
        '## References in run 1',
        '',
        '| Column | References | Null | Unmatched |',
        '|---|---|---|---|',
    ]
    for col, s in first['references'].items():
        lines.append(f'| {col} | {s["references"]} | {s["null"]} | {s["unmatched"]} |')
    lines += [
        '',
        'The mock requests do not line up with the lookup CSVs: categories are `CAT-FOOD` style ids '
        'while help_categories uses `1.1` style ids, and many request_for, islead, type and priority ids '
        'are outside the lookup ranges. That is expected for this data and is a useful test of the LEFT '
        'JOINs: every one of those requests is still in the export, with its id kept and the readable '
        'column left empty.',
        '',
        'Real numbers for the production table need a run against the database, which this local test cannot do.',
    ]
    with open(os.path.join(OUT_DIR, 'validation_summary.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
