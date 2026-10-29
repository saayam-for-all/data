import csv
import os
import sqlite3

SCHEMA = 'virginia_dev_saayam_rdbms'

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REQUESTS_CSV = os.path.join(REPO_ROOT, 'data-analytics', 'sql', 'requests.csv')
LOOKUP_DIR = os.path.join(REPO_ROOT, 'database', 'lookup_tables')

REQUEST_COLUMNS = [
    ('req_id', 'TEXT'), ('creator_id', 'TEXT'), ('beneficiary_id', 'TEXT'), ('lead_volunteer_id', 'TEXT'),
    ('req_cat_id', 'TEXT'), ('req_for_id', 'INTEGER'), ('req_islead_id', 'INTEGER'),
    ('req_type_id', 'INTEGER'), ('req_priority_id', 'INTEGER'), ('req_status_id', 'INTEGER'),
    ('req_subj', 'TEXT'), ('req_desc', 'TEXT'), ('req_doc_link', 'TEXT'), ('audio_req_desc', 'TEXT'),
    ('deletion_reason', 'TEXT'), ('req_loc', 'TEXT'), ('created_loc', 'TEXT'), ('iscalamity', 'TEXT'),
    ('to_public', 'TEXT'), ('submission_date', 'TEXT'), ('serviced_date', 'TEXT'), ('last_updated_at', 'TEXT'),
]

# table name in the #573 schema -> (key column, key type, readable column, csv in database/lookup_tables)
LOOKUP_TABLES = {
    'help_categories': ('cat_id', 'TEXT', 'cat_name', 'help_categories.csv'),
    'request_for': ('req_for_id', 'INTEGER', 'req_for', 'request_for.csv'),
    'request_isleadvol': ('req_islead_id', 'INTEGER', 'req_islead', 'request_isleadvol.csv'),
    'request_types': ('req_type_id', 'INTEGER', 'req_type', 'request_type.csv'),
    'request_priorities': ('req_priority_id', 'INTEGER', 'req_priority', 'request_priority.csv'),
    'request_statuses': ('req_status_id', 'INTEGER', 'req_status', 'request_status.csv'),
}


def clean(value):
    if value is None:
        return None
    value = value.strip()
    return None if value == '' or value.upper() == 'NULL' else value


def new_db():
    # no primary keys on purpose, so tests can put duplicate lookup keys in
    conn = sqlite3.connect(':memory:')
    conn.execute(f"ATTACH DATABASE ':memory:' AS {SCHEMA}")
    cols = ', '.join(f'{name} {kind}' for name, kind in REQUEST_COLUMNS)
    conn.execute(f'CREATE TABLE {SCHEMA}.requests ({cols})')
    for table, (key, kind, readable, _) in LOOKUP_TABLES.items():
        conn.execute(f'CREATE TABLE {SCHEMA}.{table} ({key} {kind}, {readable} TEXT)')
    return conn


def insert_requests(conn, rows):
    names = [name for name, _ in REQUEST_COLUMNS]
    marks = ', '.join('?' for _ in names)
    conn.executemany(
        f'INSERT INTO {SCHEMA}.requests ({", ".join(names)}) VALUES ({marks})',
        [[row.get(n) for n in names] for row in rows],
    )


def insert_lookup(conn, table, pairs):
    key, _, readable, _ = LOOKUP_TABLES[table]
    conn.executemany(f'INSERT INTO {SCHEMA}.{table} ({key}, {readable}) VALUES (?, ?)', pairs)


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def load_repo_mock_data(conn):
    # requests.csv follows the #573 schema; it has no created_loc column, so that stays empty
    requests = [{k: clean(v) for k, v in row.items() if k} for row in read_csv(REQUESTS_CSV)]
    insert_requests(conn, requests)

    for table, (key, _, readable, filename) in LOOKUP_TABLES.items():
        rows = read_csv(os.path.join(LOOKUP_DIR, filename))
        insert_lookup(conn, table, [(clean(r[key]), clean(r[readable])) for r in rows])

    conn.commit()
    return len(requests)
