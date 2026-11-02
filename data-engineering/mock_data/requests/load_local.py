"""Load the generated CSVs into a throwaway local PostgreSQL/PostGIS cluster (Issue #587).

Usage:
    python3 data-engineering/mock_data/requests/load_local.py [--keep]

It never connects to an existing server: it runs initdb in a new temp directory, starts a server on
127.0.0.1 at a random free port, loads the schema and the nine CSVs, prints a report, then stops the
server and deletes only that temp directory. With --keep the server is left running and the commands
to connect and clean up are printed.

Needs PostgreSQL 17 (initdb, pg_ctl) with PostGIS, and psycopg2 (already in requirements.txt).
"""
import argparse
import csv
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg2

HERE = Path(__file__).resolve().parent
SCHEMA_SQL = HERE / "saayam_schema.sql"
SCHEMA = "virginia_dev_saayam_rdbms"
TEMP_PREFIX = "saayam587_pg_"
NULL_TOKEN = "\\N"

# Foreign-key load order; columns come from each CSV header.
TABLES = [
    "help_categories", "help_categories_map", "request_for", "request_isleadvol", "request_types",
    "request_priorities", "request_statuses", "users", "requests",
]
SERIAL_TABLES = {  # table -> id column
    "request_for": "req_for_id", "request_isleadvol": "req_islead_id", "request_types": "req_type_id",
    "request_priorities": "req_priority_id", "request_statuses": "req_status_id",
}
BIN_CANDIDATES = [
    "/opt/homebrew/opt/postgresql@17/bin", "/usr/local/opt/postgresql@17/bin",
    "/opt/homebrew/opt/postgresql@18/bin", "/usr/local/opt/postgresql@18/bin",
]


def find_bin(name):
    for directory in BIN_CANDIDATES:
        if (Path(directory) / name).exists():
            return str(Path(directory) / name)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"{name} not found; install PostgreSQL 17 and PostGIS (brew install postgresql@17 postgis)")


class TempCluster:
    """A new cluster in a new temp directory, listening only on 127.0.0.1."""

    def __init__(self):
        self.dir = None
        self.port = None

    def start(self):
        self.dir = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        # macOS needs a valid LC_ALL or the server refuses to start ("became multithreaded")
        env = {**os.environ, "LC_ALL": "en_US.UTF-8"}
        run = lambda *a: subprocess.run(a, check=True, capture_output=True, text=True, env=env)  # noqa: E731
        try:
            run(find_bin("initdb"), "-D", str(self.dir / "data"), "-U", "postgres", "-A", "trust",
                "-E", "UTF8", "--locale=C")
            run(find_bin("pg_ctl"), "-D", str(self.dir / "data"), "-l", str(self.dir / "server.log"), "-w",
                "-o", f"-p {self.port} -h 127.0.0.1 -k {self.dir} -c fsync=off", "start")
        except subprocess.CalledProcessError as e:
            log = self.dir / "server.log"
            detail = log.read_text()[-800:] if log.exists() else (e.stderr or e.stdout)
            self.stop()
            raise RuntimeError(f"could not start the temporary cluster: {detail}") from e
        return self

    def connect(self, dbname="postgres"):
        conn = psycopg2.connect(host="127.0.0.1", port=self.port, user="postgres", dbname=dbname)
        conn.autocommit = True
        return conn

    def stop(self):
        """Stop the server and delete the temp directory this object created, nothing else."""
        if self.dir and self.dir.name.startswith(TEMP_PREFIX):
            if (self.dir / "data" / "postmaster.pid").exists():
                subprocess.run([find_bin("pg_ctl"), "-D", str(self.dir / "data"), "-m", "immediate", "-w", "stop"],
                               capture_output=True, env={**os.environ, "LC_ALL": "en_US.UTF-8"})
            shutil.rmtree(self.dir, ignore_errors=True)
        self.dir = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def load(conn, csv_dir):
    """Create PostGIS and the schema, then COPY the nine CSVs in foreign-key order."""
    cur = conn.cursor()
    cur.execute("CREATE EXTENSION postgis")
    cur.execute(f"CREATE SCHEMA {SCHEMA}")
    cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    for table in TABLES:
        path = Path(csv_dir) / f"{table}.csv"
        with open(path, newline="", encoding="utf-8") as f:
            columns = next(csv.reader([f.readline()]))
            f.seek(0)
            try:
                cur.copy_expert(
                    f"COPY {SCHEMA}.{table} ({', '.join(columns)}) FROM STDIN "
                    f"WITH (FORMAT csv, HEADER true, NULL '\\N', ENCODING 'UTF8')", f)
            except psycopg2.Error as e:
                raise RuntimeError(f"loading {path.name} failed: {e.pgcode} {str(e).strip()}") from e
    for table, id_col in SERIAL_TABLES.items():  # explicit ids were loaded, so move the sequences
        cur.execute(f"SELECT setval(pg_get_serial_sequence('{SCHEMA}.{table}', '{id_col}'), "
                    f"(SELECT max({id_col}) FROM {SCHEMA}.{table}))")


def csv_row_count(path):
    with open(path, newline="", encoding="utf-8") as f:
        return sum(1 for _ in csv.reader(f)) - 1


def report(conn, csv_dir):
    """Print row counts against the CSVs; return True when everything matches."""
    cur = conn.cursor()
    ok = True
    for table in TABLES:
        cur.execute(f"SELECT count(*) FROM {SCHEMA}.{table}")
        loaded, expected = cur.fetchone()[0], csv_row_count(Path(csv_dir) / f"{table}.csv")
        ok &= loaded == expected
        print(f"  {table:<22}{loaded:>5} rows  (csv: {expected})  {'ok' if loaded == expected else 'MISMATCH'}")
    cur.execute("SELECT count(*), count(*) FILTER (WHERE convalidated) FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid = c.connamespace WHERE c.contype = 'f' AND n.nspname = %s", (SCHEMA,))
    total, validated = cur.fetchone()
    ok &= total == validated and total > 0
    print(f"  foreign keys: {validated}/{total} enforced and validated")
    cur.execute("SELECT postgis_version(), version()")
    print("  " + " | ".join(v.split(" on ")[0] for v in cur.fetchone()))
    return bool(ok)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--csv-dir", default=str(HERE / "csv"))
    parser.add_argument("--keep", action="store_true", help="leave the temporary server running")
    args = parser.parse_args()
    cluster = TempCluster().start()
    try:
        conn = cluster.connect()
        load(conn, args.csv_dir)
        print(f"loaded into temporary cluster on 127.0.0.1:{cluster.port}")
        ok = report(conn, args.csv_dir)
        conn.close()
    except Exception as e:  # report and clean up
        print(f"FAILED: {e}", file=sys.stderr)
        cluster.stop()
        return 1
    if args.keep:
        data = cluster.dir / "data"
        print(f"kept: psql -h 127.0.0.1 -p {cluster.port} -U postgres\n"
              f"clean up: {find_bin('pg_ctl')} -D {data} -m immediate stop && rm -r {cluster.dir}")
    else:
        cluster.stop()
        print("temporary cluster stopped and removed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
