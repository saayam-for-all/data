"""
Loads data-analytics/sql/organizations.csv (Sana's mock data for the
Organization Analytics task) into a local PostgreSQL database so
organization_analytics.py can be tested against real-shaped mock data.

Usage:
    psql -d saayam_local -f local_setup.sql   # create schema/table (once)
    python3 seed_from_csv.py                  # load/reload the CSV

Connects using the same LOCAL_DB_* environment variables as
organization_analytics.py (defaults: localhost:5432/saayam_local/postgres).
This script never touches AWS/SSM or any non-local database.
"""

import os
import psycopg2

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "sql", "organizations.csv")


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("LOCAL_DB_HOST", "localhost"),
        port=int(os.environ.get("LOCAL_DB_PORT", "5432")),
        database=os.environ.get("LOCAL_DB_NAME", "saayam_local"),
        user=os.environ.get("LOCAL_DB_USER", "postgres"),
        password=os.environ.get("LOCAL_DB_PASSWORD", ""),
    )


def main():
    conn = get_connection()
    cursor = conn.cursor()

    # TRUNCATE first so re-running this script is idempotent.
    cursor.execute("TRUNCATE TABLE virginia_dev_saayam_rdbms.organizations;")

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        cursor.copy_expert(
            "COPY virginia_dev_saayam_rdbms.organizations FROM STDIN WITH CSV HEADER",
            f
        )

    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM virginia_dev_saayam_rdbms.organizations;")
    count = cursor.fetchone()[0]
    print(f"Loaded {count} organizations from {CSV_PATH}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
