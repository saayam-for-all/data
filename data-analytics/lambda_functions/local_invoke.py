"""
Local runner for steward_volunteer_review_api.

CSV mode (default) loads users.csv and volunteer_applications.csv into an
in-memory SQLite database, attached under the real schema names, and runs the
handler's actual SQL against them. Virginia is seeded from the CSVs and Ireland
is left empty, so the two region merge path is exercised. No AWS, no Postgres:

    python local_invoke.py --page 1 --page-size 5
    python local_invoke.py --page 2 --page-size 5 --show-sql
    python local_invoke.py --statuses UNDER_REVIEW,SUBMITTED

Real mode hits the actual databases using your normal env vars:

    export DB_PARAM_PATH_VIRGINIA=/dev/saayam/db/Virginia/Analytics/user
    export DB_PARAM_PATH_IRELAND=/dev/saayam/db/Ireland/Analytics/user
    export AWS_PROFILE=your-profile
    python local_invoke.py --real --page 1 --page-size 5
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
import types

DEFAULT_CSV_DIR = os.environ.get("LOCAL_CSV_DIR", "/mnt/user-data/uploads")
NULL_TOKENS = {"", "NULL", "null", "None"}

VIRGINIA_SCHEMA = "virginia_dev_saayam_rdbms"
IRELAND_SCHEMA = "ireland_dev_saayam_rdbms"


def install_stubs():
    """Used in CSV mode so the module imports without the Lambda layer."""
    if "psycopg2" not in sys.modules:
        psycopg2_stub = types.ModuleType("psycopg2")

        class Error(Exception):
            pass

        class OperationalError(Error):
            pass

        psycopg2_stub.Error = Error
        psycopg2_stub.OperationalError = OperationalError
        psycopg2_stub.connect = lambda **kwargs: None
        sys.modules["psycopg2"] = psycopg2_stub

    if "boto3" not in sys.modules:
        boto3_stub = types.ModuleType("boto3")
        boto3_stub.client = lambda *args, **kwargs: None
        sys.modules["boto3"] = boto3_stub


# ---------------------------------------------------------------------------
# SQLite stand-in for a psycopg2 connection
# ---------------------------------------------------------------------------

class SqliteCursor:
    """Adapts the handler's Postgres style SQL to SQLite for local runs."""

    def __init__(self, connection, echo_sql=False):
        self._cursor = connection.cursor()
        self._echo_sql = echo_sql

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._cursor.close()
        return False

    def execute(self, sql, params=None):
        # SQLite has no :: cast operator, and stores everything as text here
        # anyway, so the cast is a no-op locally.
        translated = sql.replace("%s", "?").replace("::text", "")
        if self._echo_sql:
            print(f"\n[SQL] {' '.join(translated.split())}\n[PARAMS] {params}")
        self._cursor.execute(translated, tuple(params or ()))

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class SqliteConnection:
    def __init__(self, connection, echo_sql=False):
        self._connection = connection
        self._echo_sql = echo_sql
        self.closed = False

    def cursor(self):
        return SqliteCursor(self._connection, self._echo_sql)

    def close(self):
        self.closed = True


def _load_table(connection, qualified_name, csv_path, seed=True):
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        quoted = ", ".join(f'"{column}" TEXT' for column in columns)
        connection.execute(f"CREATE TABLE {qualified_name} ({quoted})")

        if not seed:
            connection.commit()
            return 0

        placeholders = ", ".join("?" for _ in columns)
        rows = [
            tuple(
                None if (row[column] or "").strip() in NULL_TOKENS else row[column]
                for column in columns
            )
            for row in reader
        ]
        connection.executemany(
            f"INSERT INTO {qualified_name} VALUES ({placeholders})", rows
        )
    connection.commit()
    return len(rows)


def build_csv_connection(csv_dir, echo_sql=False):
    """One SQLite DB with both regional schemas attached. Ireland is empty."""
    raw = sqlite3.connect(":memory:")
    raw.execute(f"ATTACH DATABASE ':memory:' AS {VIRGINIA_SCHEMA}")
    raw.execute(f"ATTACH DATABASE ':memory:' AS {IRELAND_SCHEMA}")

    users_csv = os.path.join(csv_dir, "users.csv")
    apps_csv = os.path.join(csv_dir, "volunteer_applications.csv")

    users_count = _load_table(raw, f"{VIRGINIA_SCHEMA}.users", users_csv)
    apps_count = _load_table(
        raw, f"{VIRGINIA_SCHEMA}.volunteer_applications", apps_csv
    )
    _load_table(raw, f"{IRELAND_SCHEMA}.users", users_csv, seed=False)
    _load_table(
        raw, f"{IRELAND_SCHEMA}.volunteer_applications", apps_csv, seed=False
    )

    print(
        f"[SEED] Virginia: users={users_count}, volunteer_applications={apps_count}. "
        f"Ireland: empty. (from {csv_dir})"
    )
    return SqliteConnection(raw, echo_sql)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--page-size", type=int, default=5)
    parser.add_argument("--statuses", default="UNDER_REVIEW")
    parser.add_argument("--csv-dir", default=DEFAULT_CSV_DIR)
    parser.add_argument("--show-sql", action="store_true")
    parser.add_argument(
        "--real", action="store_true", help="Hit the real databases instead of the CSVs."
    )
    args = parser.parse_args()

    if not args.real:
        install_stubs()

    os.environ["REVIEW_APPLICATION_STATUSES"] = args.statuses

    import steward_volunteer_review_api as api

    event = {"body": json.dumps({"page": args.page, "page_size": args.page_size})}

    if args.real:
        response = api.lambda_handler(event, None)
    else:
        connection = build_csv_connection(args.csv_dir, args.show_sql)
        original_config = api.get_db_config
        original_connect = api.psycopg2.connect
        api.get_db_config = lambda region: {"region": region}
        api.psycopg2.connect = lambda **kwargs: connection
        try:
            response = api.lambda_handler(event, None)
        finally:
            api.get_db_config = original_config
            api.psycopg2.connect = original_connect

    print("\n[RESPONSE]")
    print(
        json.dumps(
            {
                "statusCode": response["statusCode"],
                "body": json.loads(response["body"]),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
