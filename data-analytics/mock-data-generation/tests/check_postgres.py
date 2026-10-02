"""Import smoke test for an isolated PostgreSQL/PostGIS database.

Example (database must already exist):
python tests/check_postgres.py --database saayam_mock_301 --initialize
Pass --psql /path/to/psql if PostgreSQL is not on PATH.
"""
import argparse
import csv
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "virginia_dev_saayam_rdbms"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--psql", default="psql")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="5432")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--initialize", action="store_true",
                        help="create the test schema; fails if it already exists")
    args = parser.parse_args()
    if not args.database.startswith("saayam_mock_"):
        parser.error("Use a dedicated database named saayam_mock_*")
    base = [args.psql, "-X", "-w", "-h", args.host, "-p", args.port,
            "-U", args.user, "-d", args.database, "-v", "ON_ERROR_STOP=1"]

    def run(*extra, expected_success=True):
        result = subprocess.run(base + list(extra), cwd=str(ROOT),
                                text=True, encoding="utf-8", capture_output=True)
        if (result.returncode == 0) != expected_success:
            raise RuntimeError(result.stderr or "Expected SQL rejection, but command succeeded")
        return result.stdout.strip()

    def query(sql):
        return run("-A", "-t", "-c", sql)

    if args.initialize:
        run("-f", "tests/schema.sql")
    run("-f", "load_local.sql")
    total = 0
    expected_counts = {}
    for path in sorted((ROOT / "output_csv_files").glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            rows, columns = list(reader), reader.fieldnames
        table = path.stem  # fixed local file names, not arbitrary SQL identifiers
        if not table.replace("_", "").isalpha():
            raise RuntimeError("Unexpected CSV filename")
        count = int(query("SELECT count(*) FROM " + SCHEMA + "." + table))
        if count != len(rows):
            raise RuntimeError(table + ": imported row count differs")
        actual_columns = query(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='"
            + SCHEMA + "' AND table_name='" + table + "' ORDER BY ordinal_position").splitlines()
        if actual_columns != columns:
            raise RuntimeError(table + ": CSV header differs from database schema")
        # Prove triggers did not replace the CSV identifiers or break their joins.
        if table in ("users", "organizations"):
            key = "user_id" if table == "users" else "org_id"
            actual_ids = set(query("SELECT " + key + " FROM " + SCHEMA + "." + table).splitlines())
            if actual_ids != {row[key] for row in rows}:
                raise RuntimeError(table + ": input IDs were replaced")
        total += count
        expected_counts[table] = count
        print(table + ": " + str(count) + " rows, schema checked")

    states = query(
        "SELECT tgname || ':' || tgenabled::text FROM pg_trigger "
        "WHERE tgrelid IN ('" + SCHEMA + ".users'::regclass,'"
        + SCHEMA + ".organizations'::regclass) AND NOT tgisinternal")
    if set(states.splitlines()) != {"before_insert_users:O", "before_insert_organizations:O"}:
        raise RuntimeError("ID triggers were not restored")

    # Prove native types and FK constraints are enforced by the engine.
    for statement in ("SELECT '2147483648'::integer",
                      "SELECT '[NaN]'::jsonb",
                      "BEGIN; INSERT INTO " + SCHEMA
                      + ".volunteer_locations(user_id) VALUES ('missing-user'); COMMIT;"):
        run("-c", statement, expected_success=False)

    # A second load must refuse to append and leave the successful dataset intact.
    run("-f", "load_local.sql", expected_success=False)
    if int(query("SELECT count(*) FROM " + SCHEMA + ".users")) != expected_counts["users"]:
        raise RuntimeError("Rejected repeat load changed user data")
    print(query("SELECT version()"))
    print(query("SELECT postgis_full_version()"))
    print("PASS: " + str(total) + " rows loaded; identifiers preserved; triggers restored; "
          "types/FKs enforced; repeat load rejected.")


if __name__ == "__main__":
    main()
