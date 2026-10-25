"""
Load organizations.csv and state.csv into a local Postgres so
organization_analytics.py can be tested against real data.

Usage:
    python load_organizations.py ../sql

DB connection uses standard libpq env vars with local defaults:
    PGHOST (localhost)  PGPORT (5432)  PGDATABASE (saayam_local)
    PGUSER (your OS username, matching libpq's own default)  PGPASSWORD (unset)

Homebrew and Postgres.app create a superuser named after your OS account rather
than "postgres", so the OS username is the default that works out of the box on
macOS. Override with PGUSER when the server does have a "postgres" role.

Add --ireland to also populate ireland_dev_saayam_rdbms with the same rows,
so the multi-region merge path can be exercised locally.

Idempotent: drops and recreates the two tables, then loads.
"""
import argparse
import csv
import getpass
import os
import sys

import psycopg2

VIRGINIA_SCHEMA = "virginia_dev_saayam_rdbms"
IRELAND_SCHEMA = "ireland_dev_saayam_rdbms"

# Column types that must not be plain text for the analytics queries to behave
# the way they will against the real database.
ORGANIZATION_COL_TYPES = {
    "org_rating": "integer",
    "is_collaborator": "boolean",
    "is_contributor": "boolean",
    "created_at": "timestamp",
    "last_updated_at": "timestamp",
}

STATE_COL_TYPES = {
    "country_id": "integer",
    "last_update_date": "timestamp",
}


def default_user():
    """libpq defaults the DB user to the OS username; mirror that."""
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - no passwd entry (some containers)
        return "postgres"


def dsn():
    return dict(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE", "saayam_local"),
        user=os.getenv("PGUSER") or default_user(),
        password=os.getenv("PGPASSWORD", ""),
    )


def get_header(path):
    with open(path, newline="") as handle:
        return next(csv.reader(handle))


def load_csv(cursor, schema, table, csv_path, col_types, primary_key=None):
    """Recreate ``schema.table`` from ``csv_path`` and COPY the rows in."""
    columns = get_header(csv_path)
    coldefs = ", ".join(f'"{c}" {col_types.get(c, "text")}' for c in columns)
    pk_clause = f", PRIMARY KEY ({primary_key})" if primary_key else ""
    cursor.execute(f"DROP TABLE IF EXISTS {schema}.{table} CASCADE;")
    cursor.execute(f"CREATE TABLE {schema}.{table} ({coldefs}{pk_clause});")
    with open(csv_path, newline="") as handle:
        cursor.copy_expert(
            f"COPY {schema}.{table} FROM STDIN "
            f"WITH (FORMAT csv, HEADER true, NULL '')",
            handle,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "sql_dir",
        help="Path to data-analytics/sql (must contain organizations.csv and state.csv)",
    )
    parser.add_argument(
        "--ireland",
        action="store_true",
        help="Also load the same rows into ireland_dev_saayam_rdbms",
    )
    parser.add_argument(
        "--drop-is-contributor",
        action="store_true",
        help="Simulate the dev database that predates the is_contributor column",
    )
    args = parser.parse_args()

    organizations_csv = os.path.join(args.sql_dir, "organizations.csv")
    state_csv = os.path.join(args.sql_dir, "state.csv")
    for path in (organizations_csv, state_csv):
        if not os.path.isfile(path):
            sys.exit(f"Missing required file: {path}")

    settings = dsn()
    try:
        conn = psycopg2.connect(**settings)
    except psycopg2.OperationalError as exc:
        sys.exit(
            f"Could not connect to Postgres as user '{settings['user']}' "
            f"on {settings['host']}:{settings['port']}/{settings['dbname']}.\n"
            f"  {str(exc).strip()}\n\n"
            "Common fixes:\n"
            "  server not running   brew services start postgresql@16\n"
            "  database missing     createdb saayam_local\n"
            "  role missing         override with PGUSER=<role> (Homebrew uses "
            "your OS username, not 'postgres')\n"
            "  list existing roles  psql -d postgres -c '\\du'"
        )
    conn.autocommit = True
    cursor = conn.cursor()

    schemas = [VIRGINIA_SCHEMA]
    if args.ireland:
        schemas.append(IRELAND_SCHEMA)

    for schema in schemas:
        cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")
        load_csv(
            cursor,
            schema,
            "organizations",
            organizations_csv,
            ORGANIZATION_COL_TYPES,
            primary_key="org_id",
        )
        load_csv(
            cursor, schema, "state", state_csv, STATE_COL_TYPES, primary_key="state_id"
        )
        if args.drop_is_contributor:
            cursor.execute(
                f"ALTER TABLE {schema}.organizations DROP COLUMN IF EXISTS is_contributor;"
            )
        cursor.execute(f"SELECT COUNT(*) FROM {schema}.organizations;")
        organizations = cursor.fetchone()[0]
        cursor.execute(f"SELECT COUNT(*) FROM {schema}.state;")
        states = cursor.fetchone()[0]
        print(f"{schema}: {organizations} organizations, {states} states")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
