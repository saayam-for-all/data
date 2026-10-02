"""Load the source extracts from data-analytics/sql into local PostgreSQL.

Uses the same data the task points at (organizations.csv, state.csv) so the API
is exercised against real source records rather than only synthetic ones.

The CSVs carry display labels ('Non-Profit', 'For-profit', 'Small') while
ddl_organizations.sql declares lowercase enums ('non_profit', 'small'), so the
labels are normalized on the way in. The API normalizes on the way out too, and
therefore reports the same buckets whichever form a database happens to hold.

    python3 organization_analytics_load_csv.py [orgs_csv] [state_csv]

Defaults resolve to ../sql/*.csv, i.e. the repo layout when this file sits in
data-analytics/lambda_functions/.
"""
import csv
import os
import sys

import psycopg2

DB = dict(
    host=os.environ.get("DB_HOST", "localhost"),
    database=os.environ.get("DB_NAME", "saayam_local"),
    user=os.environ.get("DB_USER", "saayam"),
    password=os.environ.get("DB_PASSWORD", "saayam_local"),
    port=os.environ.get("DB_PORT", "5432"),
)
SCHEMA = "virginia_dev_saayam_rdbms"

DEFAULT_ORGS_CSV = os.path.join(os.path.dirname(__file__), "..", "sql", "organizations.csv")
DEFAULT_STATE_CSV = os.path.join(os.path.dirname(__file__), "..", "sql", "state.csv")


def normalize_label(value):
    if value in (None, ""):
        return None
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def to_bool(value):
    if value in (None, ""):
        return None
    return value.strip().upper() == "TRUE"


def to_int(value):
    return int(value) if value not in (None, "") else None


def blank_to_none(value):
    return value if value not in (None, "") else None


def load(orgs_csv, state_csv):
    with open(state_csv, newline="", encoding="utf-8") as handle:
        states = list(csv.DictReader(handle))
    with open(orgs_csv, newline="", encoding="utf-8") as handle:
        organizations = list(csv.DictReader(handle))

    conn = psycopg2.connect(**DB)
    cur = conn.cursor()
    cur.execute(f"SET search_path TO {SCHEMA}")

    # The org_id trigger would overwrite the identifiers coming from the extract.
    trigger_disabled = True
    try:
        cur.execute("ALTER TABLE organizations DISABLE TRIGGER before_insert_organizations")
    except psycopg2.Error as error:
        conn.rollback()
        cur = conn.cursor()
        cur.execute(f"SET search_path TO {SCHEMA}")
        trigger_disabled = False
        print(f"WARNING: could not disable the org_id trigger ({error}); "
              "org_id values will be regenerated instead of taken from the CSV.")

    cur.execute("DELETE FROM organizations")
    cur.execute("INSERT INTO country (country_id, country_name) VALUES (1, 'United States') "
                "ON CONFLICT DO NOTHING")

    for row in states:
        cur.execute(
            """INSERT INTO state (state_id, country_id, state_name, state_code, last_update_date)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (state_id) DO UPDATE
                   SET state_name = EXCLUDED.state_name,
                       state_code = EXCLUDED.state_code""",
            (row["state_id"], to_int(row["country_id"]), row["state_name"],
             row["state_code"], blank_to_none(row["last_update_date"]))
        )

    for row in organizations:
        cur.execute(
            """INSERT INTO organizations
               (org_id, org_name, street, city_name, state_id, zip_code, mission,
                web_url, phone, email, org_type, org_size, org_rating,
                is_collaborator, is_contributor, created_at, last_updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (row["org_id"], row["org_name"], blank_to_none(row["street"]),
             blank_to_none(row["city_name"]), blank_to_none(row["state_id"]),
             blank_to_none(row["zip_code"]), blank_to_none(row["mission"]),
             blank_to_none(row["web_url"]), blank_to_none(row["phone"]),
             blank_to_none(row["email"]), normalize_label(row["org_type"]),
             normalize_label(row["org_size"]), to_int(row["org_rating"]),
             to_bool(row["is_collaborator"]), to_bool(row.get("is_contributor")),
             blank_to_none(row["created_at"]), blank_to_none(row["last_updated_at"]))
        )

    if trigger_disabled:
        cur.execute("ALTER TABLE organizations ENABLE TRIGGER before_insert_organizations")

    conn.commit()
    cur.execute("SELECT COUNT(*) FROM organizations")
    print(f"Loaded {cur.fetchone()[0]} organizations and {len(states)} states.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    orgs = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ORGS_CSV
    state = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_STATE_CSV
    load(orgs, state)
