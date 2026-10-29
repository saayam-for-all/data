import csv
import io
import json
from datetime import datetime, timezone

CREDS_PARAM = '/dev/saayam/db/Virginia/Analytics/user'

# requests column -> (lookup table, key column, readable column)
# taken from the schema attached to #573, update here if that mapping changes
LOOKUPS = [
    ('req_cat_id', 'help_categories', 'cat_id', 'cat_name'),
    ('req_for_id', 'request_for', 'req_for_id', 'req_for'),
    ('req_islead_id', 'request_isleadvol', 'req_islead_id', 'req_islead'),
    ('req_type_id', 'request_types', 'req_type_id', 'req_type'),
    ('req_priority_id', 'request_priorities', 'req_priority_id', 'req_priority'),
    ('req_status_id', 'request_statuses', 'req_status_id', 'req_status'),
]

# these point at users, which has nothing readable to bring in,
# so the join is only there to count references to users that no longer exist
USER_REFS = ['creator_id', 'beneficiary_id', 'lead_volunteer_id']

OTHER_COLUMNS = [
    'req_subj', 'req_desc', 'req_doc_link', 'audio_req_desc', 'deletion_reason',
    'req_loc', 'created_loc', 'iscalamity', 'to_public',
    'submission_date', 'serviced_date', 'last_updated_at',
]

BACKUP_COLUMNS = ['req_id'] + USER_REFS
for _col, _table, _key, _readable in LOOKUPS:
    BACKUP_COLUMNS += [_col, _readable]
BACKUP_COLUMNS += OTHER_COLUMNS

# what stakeholders get: no ids, no free text, no locations, no exact dates
SHARED_COLUMNS = [
    'request_month', 'category', 'request_for', 'lead_volunteer_flag', 'request_type',
    'priority', 'status', 'is_calamity', 'days_to_service', 'has_beneficiary', 'has_lead_volunteer',
]

# one consistent, read-only view of the table for the count and the export
SNAPSHOT_SQL = 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'

_conn = None
_db_name = None
_s3_client = None


def get_connection():
    global _conn, _db_name
    if _conn is None:
        import pg8000
        from aws_lambda_powertools.utilities import parameters

        creds = json.loads(parameters.get_parameter(CREDS_PARAM, decrypt=True, max_age=3600))
        _db_name = creds['DATABASE NAME']
        _conn = pg8000.connect(
            host=creds['HOST'],
            user=creds['USERNAME'],
            password=creds['PASSWORD'],
            database=_db_name,
            port=creds['PORT'],
            ssl_context=True
        )
    return _conn, _db_name


def get_s3_client():
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client('s3')
    return _s3_client


def status_filter(statuses):
    if not statuses:
        return ''
    # statuses are checked to be ints in the handler, so inlining them is safe
    return 'WHERE r.req_status_id IN (' + ', '.join(str(int(s)) for s in statuses) + ')'


def build_count_query(schema, statuses=None):
    return f'SELECT COUNT(*) FROM {schema}.requests r {status_filter(statuses)}'


def build_export_query(schema, statuses=None):
    select = ['r.req_id']
    joins = []

    for col in USER_REFS:
        select.append(f'r.{col}')
        select.append(f'u_{col}.user_id AS {col}_found')
        joins.append(f'LEFT JOIN {schema}.users u_{col} ON u_{col}.user_id = r.{col}')

    for i, (col, table, key, readable) in enumerate(LOOKUPS):
        select.append(f'CAST(r.{col} AS TEXT) AS {col}')
        select.append(f'l{i}.{readable} AS {readable}')
        joins.append(f'LEFT JOIN {schema}.{table} l{i} ON l{i}.{key} = r.{col}')

    for col in OTHER_COLUMNS:
        # geometry and timestamps come out as text so the csv is the same on any driver
        select.append(f'CAST(r.{col} AS TEXT) AS {col}')

    return (
        'SELECT ' + ',\n       '.join(select) + '\n'
        f'FROM {schema}.requests r\n'
        + '\n'.join(joins) + '\n'
        f'{status_filter(statuses)}\n'
        'ORDER BY r.req_id'
    )


def find_duplicate_lookup_keys(cursor, schema):
    # a repeated key in a lookup table would turn one request into two rows
    problems = []
    for col, table, key, readable in LOOKUPS:
        cursor.execute(
            f'SELECT {key}, COUNT(*) FROM {schema}.{table} GROUP BY {key} HAVING COUNT(*) > 1'
        )
        for value, count in cursor.fetchall():
            problems.append(f'{table}.{key} = {value} appears {count} times')
    cursor.execute(f'SELECT user_id, COUNT(*) FROM {schema}.users GROUP BY user_id HAVING COUNT(*) > 1')
    for value, count in cursor.fetchall():
        problems.append(f'users.user_id = {value} appears {count} times')
    return problems


def fetch_requests(conn, schema, statuses=None):
    cursor = conn.cursor()
    try:
        if SNAPSHOT_SQL:
            cursor.execute(SNAPSHOT_SQL)
        cursor.execute(build_count_query(schema, statuses))
        source_count = cursor.fetchone()[0]
        lookup_problems = find_duplicate_lookup_keys(cursor, schema)
        cursor.execute(build_export_query(schema, statuses))
        names = [d[0] for d in cursor.description]
        rows = [dict(zip(names, r)) for r in cursor.fetchall()]
    finally:
        # nothing is written to the db, this just ends the read transaction
        conn.rollback()
    return source_count, rows, lookup_problems


def is_blank(value):
    return value is None or str(value).strip() == ''


def reference_stats(rows):
    stats = {}
    for col, table, key, readable in LOOKUPS:
        nulls = sum(1 for r in rows if is_blank(r[col]))
        unmatched = sum(1 for r in rows if not is_blank(r[col]) and r[readable] is None)
        stats[col] = {'references': f'{table}.{key}', 'null': nulls, 'unmatched': unmatched}
    for col in USER_REFS:
        nulls = sum(1 for r in rows if is_blank(r[col]))
        unmatched = sum(1 for r in rows if not is_blank(r[col]) and r[f'{col}_found'] is None)
        stats[col] = {'references': 'users.user_id', 'null': nulls, 'unmatched': unmatched}
    return stats


def validate(source_count, rows, lookup_problems):
    errors = list(lookup_problems)
    if len(rows) != source_count:
        errors.append(f'source has {source_count} requests but the export has {len(rows)}')
    ids = [r['req_id'] for r in rows]
    duplicates = len(ids) - len(set(ids))
    if duplicates:
        errors.append(f'{duplicates} duplicate req_id values in the export')
    return errors


def to_datetime(value):
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None


def to_flag(value):
    if is_blank(value):
        return ''
    return 'true' if str(value).strip().lower() in ('true', 't', '1') else 'false'


def readable(row, col, readable_col):
    # keep the raw id as text when there's no lookup match, so the value isn't lost
    if row[readable_col] is not None:
        return row[readable_col]
    return '' if is_blank(row[col]) else str(row[col])


def to_shared_row(row):
    submitted = to_datetime(row['submission_date'])
    serviced = to_datetime(row['serviced_date'])
    days = ''
    if submitted and serviced and serviced >= submitted:
        days = (serviced - submitted).days
    return {
        'request_month': submitted.strftime('%Y-%m') if submitted else '',
        'category': readable(row, 'req_cat_id', 'cat_name'),
        'request_for': readable(row, 'req_for_id', 'req_for'),
        'lead_volunteer_flag': readable(row, 'req_islead_id', 'req_islead'),
        'request_type': readable(row, 'req_type_id', 'req_type'),
        'priority': readable(row, 'req_priority_id', 'req_priority'),
        'status': readable(row, 'req_status_id', 'req_status'),
        'is_calamity': to_flag(row['iscalamity']),
        'days_to_service': days,
        'has_beneficiary': 'false' if is_blank(row['beneficiary_id']) else 'true',
        'has_lead_volunteer': 'false' if is_blank(row['lead_volunteer_id']) else 'true',
    }


def to_csv(rows, columns):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({c: '' if row.get(c) is None else row.get(c) for c in columns})
    return out.getvalue()


def build_exports(rows):
    return to_csv(rows, BACKUP_COLUMNS), to_csv([to_shared_row(r) for r in rows], SHARED_COLUMNS)


def run_archive(bucket, shared_bucket=None, prefix='request_archive', statuses=None, run_date=None):
    conn, schema = get_connection()
    source_count, rows, lookup_problems = fetch_requests(conn, schema, statuses)

    result = {
        'source_count': source_count,
        'exported_count': len(rows),
        'statuses': statuses or 'all',
        'references': reference_stats(rows),
        'errors': validate(source_count, rows, lookup_problems),
    }
    if result['errors']:
        return result

    run_date = run_date or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    backup_csv, shared_csv = build_exports(rows)
    backup_key = f'{prefix}/backup/run_date={run_date}/requests_full.csv'
    shared_key = f'{prefix}/shared/run_date={run_date}/requests_shared.csv'

    s3 = get_s3_client()
    s3.put_object(Bucket=bucket, Key=backup_key, Body=backup_csv.encode('utf-8'), ContentType='text/csv')
    s3.put_object(Bucket=shared_bucket or bucket, Key=shared_key,
                  Body=shared_csv.encode('utf-8'), ContentType='text/csv')

    result['backup'] = {'bucket': bucket, 'key': backup_key}
    result['shared'] = {'bucket': shared_bucket or bucket, 'key': shared_key}
    return result
