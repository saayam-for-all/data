import csv
import io
import json
from datetime import datetime, timedelta, timezone

CREDS_PARAM = '/dev/saayam/db/Virginia/Analytics/user'

# requests column -> (lookup table, key column, readable column)
# from the schema attached to #573. users is deliberately not joined.
LOOKUPS = [
    ('req_cat_id', 'help_categories', 'cat_id', 'cat_name'),
    ('req_for_id', 'request_for', 'req_for_id', 'req_for'),
    ('req_islead_id', 'request_isleadvol', 'req_islead_id', 'req_islead'),
    ('req_type_id', 'request_types', 'req_type_id', 'req_type'),
    ('req_priority_id', 'request_priorities', 'req_priority_id', 'req_priority'),
    ('req_status_id', 'request_statuses', 'req_status_id', 'req_status'),
]

OTHER_COLUMNS = [
    'creator_id', 'beneficiary_id', 'lead_volunteer_id',
    'req_subj', 'req_desc', 'req_doc_link', 'audio_req_desc', 'deletion_reason',
    'req_loc', 'created_loc', 'iscalamity', 'to_public',
    'submission_date', 'serviced_date',
]

EXPORT_COLUMNS = ['req_id']
for _col, _table, _key, _readable in LOOKUPS:
    EXPORT_COLUMNS += [_col, _readable]
EXPORT_COLUMNS += OTHER_COLUMNS + ['last_updated_at']

TIMESTAMP_COLUMN = 'last_updated_at'
INITIAL_WATERMARK = '2000-01-01 00:00:00'
# last_updated_at is stamped when the statement runs but only visible once the
# transaction commits, so the window stops a few minutes short of now
LAG_MINUTES = 5

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


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_timestamp(value):
    # every timestamp in this schema is timestamp without time zone, stored as UTC
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
    except ValueError:
        raise ValueError(f'not a timestamp: {value!r}')
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def ts_literal(value):
    # bounds are parsed datetimes, never raw input, so inlining them is safe
    return "'" + parse_timestamp(value).strftime('%Y-%m-%d %H:%M:%S.%f') + "'"


def window_filter(lo, hi):
    # half open (lo, hi]: a row stamped exactly on a bound lands in one run only
    return (f'WHERE r.{TIMESTAMP_COLUMN} > {ts_literal(lo)} '
            f'AND r.{TIMESTAMP_COLUMN} <= {ts_literal(hi)}')


def build_count_query(schema, lo, hi):
    return f'SELECT COUNT(*) FROM {schema}.requests r {window_filter(lo, hi)}'


def build_export_query(schema, lo, hi):
    select = ['r.req_id']
    joins = []
    for i, (col, table, key, readable) in enumerate(LOOKUPS):
        select.append(f'CAST(r.{col} AS TEXT) AS {col}')
        select.append(f'l{i}.{readable} AS {readable}')
        joins.append(f'LEFT JOIN {schema}.{table} l{i} ON l{i}.{key} = r.{col}')
    for col in OTHER_COLUMNS + [TIMESTAMP_COLUMN]:
        # geometry and timestamps come out as text so the csv is the same on any driver
        select.append(f'CAST(r.{col} AS TEXT) AS {col}')

    return (
        'SELECT ' + ',\n       '.join(select) + '\n'
        f'FROM {schema}.requests r\n'
        + '\n'.join(joins) + '\n'
        f'{window_filter(lo, hi)}\n'
        f'ORDER BY r.{TIMESTAMP_COLUMN}, r.req_id'
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
    return problems


def count_missing_timestamps(cursor, schema):
    # these can never fall inside a window, so report them rather than lose them quietly
    cursor.execute(f'SELECT COUNT(*) FROM {schema}.requests WHERE {TIMESTAMP_COLUMN} IS NULL')
    return cursor.fetchone()[0]


def fetch_window(conn, schema, lo, hi):
    cursor = conn.cursor()
    try:
        if SNAPSHOT_SQL:
            cursor.execute(SNAPSHOT_SQL)
        cursor.execute(build_count_query(schema, lo, hi))
        source_count = cursor.fetchone()[0]
        lookup_problems = find_duplicate_lookup_keys(cursor, schema)
        missing_timestamps = count_missing_timestamps(cursor, schema)
        rows = []
        if source_count:
            cursor.execute(build_export_query(schema, lo, hi))
            names = [d[0] for d in cursor.description]
            rows = [dict(zip(names, r)) for r in cursor.fetchall()]
    finally:
        # nothing is written to the db, this just ends the read transaction
        conn.rollback()
    return source_count, rows, lookup_problems, missing_timestamps


def is_blank(value):
    return value is None or str(value).strip() == ''


def reference_stats(rows):
    stats = {}
    for col, table, key, readable in LOOKUPS:
        nulls = sum(1 for r in rows if is_blank(r[col]))
        unmatched = sum(1 for r in rows if not is_blank(r[col]) and r[readable] is None)
        stats[col] = {'references': f'{table}.{key}', 'null': nulls, 'unmatched': unmatched}
    return stats


def validate(source_count, rows, lookup_problems):
    errors = list(lookup_problems)
    if len(rows) != source_count:
        errors.append(f'source has {source_count} requests in the window but the export has {len(rows)}')
    ids = [r['req_id'] for r in rows]
    duplicates = len(ids) - len(set(ids))
    if duplicates:
        errors.append(f'{duplicates} duplicate req_id values in the export')
    return errors


def to_csv(rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=EXPORT_COLUMNS, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({c: '' if row.get(c) is None else row.get(c) for c in EXPORT_COLUMNS})
    return out.getvalue()


def stamp(value):
    return parse_timestamp(value).strftime('%Y%m%dT%H%M%S')


def export_key(prefix, lo, hi, day):
    # the key comes from the window, so re-running the same window overwrites
    return f'{prefix}/requests/ingest_date={day}/requests_{stamp(lo)}_{stamp(hi)}.csv'


def state_key(prefix):
    return f'{prefix}/_state/watermark.json'


def read_watermark(s3, bucket, prefix):
    try:
        res = s3.get_object(Bucket=bucket, Key=state_key(prefix))
    except Exception as e:
        code = getattr(e, 'response', {}).get('Error', {}).get('Code', '')
        if code in ('NoSuchKey', '404') or type(e).__name__ == 'NoSuchKey':
            return None
        raise
    return json.loads(res['Body'].read())['last_updated_at']


def write_watermark(s3, bucket, prefix, value):
    body = {'last_updated_at': parse_timestamp(value).strftime('%Y-%m-%d %H:%M:%S.%f'),
            'written_at': utc_now().isoformat(sep=' ')}
    s3.put_object(Bucket=bucket, Key=state_key(prefix), Body=json.dumps(body).encode('utf-8'),
                  ContentType='application/json')


def run_archive(bucket, prefix='request_archive', range_from=None, range_to=None):
    conn, schema = get_connection()
    s3 = get_s3_client()

    # an explicit range is for backfills and never moves the watermark
    explicit = range_from is not None
    if explicit:
        lo, hi = parse_timestamp(range_from), parse_timestamp(range_to)
    else:
        lo = parse_timestamp(read_watermark(s3, bucket, prefix) or INITIAL_WATERMARK)
        hi = utc_now() - timedelta(minutes=LAG_MINUTES)
        if lo > hi:
            raise RuntimeError(f'watermark {lo} is ahead of {hi}, check for future dated rows')

    source_count, rows, lookup_problems, missing_timestamps = fetch_window(conn, schema, lo, hi)
    result = {
        'range_from': str(lo),
        'range_to': str(hi),
        'explicit_range': explicit,
        'source_count': source_count,
        'exported_count': len(rows),
        'rows_without_last_updated_at': missing_timestamps,
        'references': reference_stats(rows),
        'errors': validate(source_count, rows, lookup_problems),
    }
    if result['errors']:
        result['status'] = 'failed'
        return result
    if source_count == 0:
        result['status'] = 'nothing_to_do'
        return result

    key = export_key(prefix, lo, hi, utc_now().strftime('%Y-%m-%d'))
    s3.put_object(Bucket=bucket, Key=key, Body=to_csv(rows).encode('utf-8'), ContentType='text/csv')

    # only after S3 has the file, so a failed upload leaves the next run on the same window
    if not explicit:
        write_watermark(s3, bucket, prefix, hi)

    result['status'] = 'success'
    result['s3_key'] = key
    return result
