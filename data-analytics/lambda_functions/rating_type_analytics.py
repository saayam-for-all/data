"""Organization Rating & Type analytics Lambda. Issue #380."""
import json
import os
from datetime import date, datetime, timedelta

import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None

BUCKETS = ('7D', '30D', '1Y', 'All')


def empty_charts():
    return {'rating_distribution': [], 'organization_mix_trend': {'non_profit': [], 'for_profit': []}}


def parse_request(event):
    event = event or {}
    if not isinstance(event, dict):
        raise ValueError('Request must be a JSON object')
    body = event.get('body')
    if body is not None:
        if isinstance(body, str):
            try:
                body = json.loads(body) if body.strip() else {}
            except json.JSONDecodeError as exc:
                raise ValueError('Invalid JSON body') from exc
        if not isinstance(body, dict):
            raise ValueError('Request body must be a JSON object')
        return {**{k: v for k, v in event.items() if k != 'body'}, **body}
    return event


def date_pair(params, prefix):
    start_raw = params.get(prefix + '_start_date')
    end_raw = params.get(prefix + '_end_date')
    start_present = start_raw is not None and str(start_raw).strip() != ''
    end_present = end_raw is not None and str(end_raw).strip() != ''
    if start_present != end_present:
        raise ValueError(f'{prefix}_start_date and {prefix}_end_date must both be provided')
    if not start_present:
        return None
    try:
        values = []
        for raw in (start_raw, end_raw):
            if not isinstance(raw, str) or len(raw) != 10:
                raise ValueError('format')
            parsed = date.fromisoformat(raw)
            if parsed.isoformat() != raw:
                raise ValueError('format')
            values.append(parsed)
        start, end = values
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{prefix} dates must use YYYY-MM-DD format') from exc
    if start > end:
        raise ValueError(f'{prefix}_start_date must not be after {prefix}_end_date')
    return start, end


def load_data():
    if os.getenv('USE_MOCK_DATA', 'true').lower() == 'true':
        root = os.getenv('MOCK_DATA_DIR', '.')
        org = pd.read_csv(os.path.join(root, 'organizations.csv'))
        states = pd.read_csv(os.path.join(root, 'states.csv'))
        countries = pd.read_csv(os.path.join(root, 'countries.csv'))
    else:
        if psycopg2 is None:
            raise RuntimeError('psycopg2 is required for PostgreSQL mode')
        # Connection uses libpq environment variables: PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD.
        with psycopg2.connect() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT org_id, org_rating, org_type, state_id, created_at FROM organizations')
                org = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
                cur.execute('SELECT state_id, country_id FROM states')
                states = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
                cur.execute('SELECT country_id, country_code, country_name FROM countries')
                countries = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
    required = [(org, ('org_id', 'org_rating', 'org_type', 'state_id', 'created_at'), 'organizations'),
                (states, ('state_id', 'country_id'), 'states'),
                (countries, ('country_id',), 'countries')]
    for df, cols, table in required:
        missing = set(cols) - set(df.columns)
        if missing:
            raise ValueError(f'{table} missing columns: {sorted(missing)}')
    if not ({'country_code', 'country_name'} & set(countries.columns)):
        raise ValueError('countries needs country_code or country_name')
    joined = org.merge(states[['state_id', 'country_id']], on='state_id', how='left').merge(
        countries[[c for c in ('country_id', 'country_code', 'country_name') if c in countries]],
        on='country_id', how='left')
    joined['created_at'] = pd.to_datetime(joined['created_at'], errors='coerce', utc=True).dt.tz_localize(None)
    joined['org_rating'] = pd.to_numeric(joined['org_rating'], errors='coerce')
    joined['org_type'] = joined['org_type'].astype('string').str.strip().str.lower().str.replace('-', '_', regex=False).str.replace(' ', '_', regex=False)
    return joined


def filter_country(df, country):
    if country is None or (isinstance(country, str) and country.strip().upper() == 'ALL'):
        return df
    if not isinstance(country, str) or not country.strip():
        raise ValueError('country must be a non-empty country name, code, or ALL')
    cols = [c for c in ('country_code', 'country_name') if c in df.columns]
    mask = pd.Series(False, index=df.index)
    for col in cols:
        mask |= df[col].astype('string').str.casefold().eq(country.strip().casefold()).fillna(False)
    return df.loc[mask]


def in_window(df, start, end):
    dates = df['created_at'].dt.date
    return df.loc[dates.notna() & (dates >= start) & (dates <= end)] if start is not None else df.loc[dates.notna()]


def ratings(df, start, end):
    selected = in_window(df, start, end)
    valid = selected.loc[selected['org_rating'].isin([1, 2, 3, 4, 5])]
    counts = valid.groupby('org_rating').size().sort_index()
    return [{'rating': int(r), 'count': int(n)} for r, n in counts.items()]


def type_trend(df, start, end, monthly):
    """All-time cumulative totals at each period with new activity in the requested window."""
    dated = in_window(df, None, end) if end is not None else in_window(df, None, None)
    result = {'non_profit': [], 'for_profit': []}
    for org_type in result:
        subset = dated.loc[dated['org_type'] == org_type].copy()
        if subset.empty:
            continue
        subset['period'] = subset['created_at'].dt.strftime('%Y-%m' if monthly else '%Y-%m-%d')
        counts = subset.groupby('period').size().sort_index()
        cumulative = counts.cumsum()
        for period, count in cumulative.items():
            period_date = date.fromisoformat(period + '-01') if monthly else date.fromisoformat(period)
            # Monthly buckets include the month containing the start date.
            if monthly and start is not None and (period_date.year, period_date.month) < (start.year, start.month):
                continue
            if start is not None and not monthly and period_date < start:
                continue
            result[org_type].append({'period': period, 'count': int(count)})
    return result


def months_ago(today, count):
    year = today.year
    month = today.month - count
    while month <= 0:
        year -= 1
        month += 12
    day = min(today.day, (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day)
    return date(year, month, day)


def build(params, df, today=None):
    rating_range = date_pair(params, 'rating')
    type_range = date_pair(params, 'type')
    df = filter_country(df, params.get('country', 'ALL'))
    if rating_range or type_range:
        item = empty_charts()
        if rating_range:
            item['rating_distribution'] = ratings(df, *rating_range)
        if type_range:
            item['organization_mix_trend'] = type_trend(df, *type_range, monthly=False)
        return {'Custom': item}
    today = today or date.today()
    windows = {'7D': today - timedelta(days=6), '30D': today - timedelta(days=29),
               '1Y': months_ago(today, 12) + timedelta(days=1), 'All': None}
    result = {}
    for bucket, start in windows.items():
        result[bucket] = {'rating_distribution': ratings(df, start, today),
                          'organization_mix_trend': type_trend(df, start, today, monthly=bucket in ('1Y', 'All'))}
    result['Custom'] = empty_charts()
    return result


def lambda_handler(event, context):
    try:
        params = parse_request(event)
        # Validate input before touching data sources.
        date_pair(params, 'rating')
        date_pair(params, 'type')
        result = build(params, load_data())
        return {'statusCode': 200, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps(result)}
    except (ValueError, TypeError) as exc:
        return {'statusCode': 400, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps({'error': str(exc)})}
    except Exception:
        return {'statusCode': 500, 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps({'error': 'Internal server error'})}


if __name__ == '__main__':
    examples = [
        {}, {'country': 'USA'},
        {'rating_start_date': '2026-01-01', 'rating_end_date': '2026-12-31'},
        {'type_start_date': '2026-01-01', 'type_end_date': '2026-12-31'},
        {'rating_start_date': '2026-01-01', 'rating_end_date': '2026-12-31',
         'type_start_date': '2026-01-01', 'type_end_date': '2026-12-31'},
    ]
    for event in examples:
        print('EVENT:', json.dumps(event))
        print(json.dumps(lambda_handler(event, None), indent=2))
