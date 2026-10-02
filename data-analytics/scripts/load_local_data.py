import csv
import os
from pathlib import Path

import psycopg2

SCHEMA_NAME = os.environ.get("SAAYAM_SCHEMA", "virginia_dev_saayam_rdbms")
STATES_TABLE = f"{SCHEMA_NAME}.states"
ORGANIZATIONS_TABLE = f"{SCHEMA_NAME}.organizations"

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
STATES_CSV = SQL_DIR / "state.csv"
ORGANIZATIONS_CSV = SQL_DIR / "organizations.csv"


def get_db_connection():
    # Plain env vars only -- no AWS Parameter Store / SSM per issue #228 constraints.
    return psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", 5432),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"]
    )


def to_bool(value):
    if value is None:
        return None
    value = value.strip().upper()
    if value == "TRUE":
        return True
    if value == "FALSE":
        return False
    return None


def to_int(value):
    if value is None or value.strip() == "":
        return None
    return int(value)


def to_none_if_blank(value):
    if value is None or value.strip() == "":
        return None
    return value


def load_states(cursor):
    with open(STATES_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [
            (
                row["state_id"],
                to_int(row["country_id"]),
                to_none_if_blank(row["state_name"]),
                to_none_if_blank(row["state_code"]),
                to_none_if_blank(row["last_update_date"])
            )
            for row in reader
        ]

    query = f"""
        INSERT INTO {STATES_TABLE}
            (state_id, country_id, state_name, state_code, last_update_date)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (state_id) DO NOTHING;
    """
    cursor.executemany(query, rows)
    return len(rows)


def load_organizations(cursor):
    with open(ORGANIZATIONS_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [
            (
                row["org_id"],
                row["org_name"],
                to_none_if_blank(row["street"]),
                to_none_if_blank(row["city_name"]),
                to_none_if_blank(row["state_id"]),
                to_none_if_blank(row["zip_code"]),
                to_none_if_blank(row["mission"]),
                to_none_if_blank(row["web_url"]),
                to_none_if_blank(row["phone"]),
                to_none_if_blank(row["email"]),
                to_none_if_blank(row["org_type"]),
                to_none_if_blank(row["org_size"]),
                to_int(row["org_rating"]),
                to_bool(row["is_collaborator"]),
                to_bool(row["is_contributor"]),
                to_none_if_blank(row["created_at"]),
                to_none_if_blank(row["last_updated_at"])
            )
            for row in reader
        ]

    query = f"""
        INSERT INTO {ORGANIZATIONS_TABLE}
            (org_id, org_name, street, city_name, state_id, zip_code, mission,
             web_url, phone, email, org_type, org_size, org_rating,
             is_collaborator, is_contributor, created_at, last_updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (org_id) DO NOTHING;
    """
    cursor.executemany(query, rows)
    return len(rows)


def main():
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        states_count = load_states(cursor)
        organizations_count = load_organizations(cursor)
        conn.commit()
        cursor.close()
        print(
            f"Loaded {states_count} states row(s) and {organizations_count} organizations row(s) "
            "from CSV (rows with an existing primary key were skipped via ON CONFLICT DO NOTHING)."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
