"""Start a task-owned PostgreSQL cluster bound to loopback only."""

import os
import shutil
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from psycopg2 import sql

from harness import TASK_DIR


def _run(command):
    """Run PostgreSQL tools without opening visible console windows."""
    options = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    # On Windows the background server can inherit pipe handles from pg_ctl.
    # A temporary log avoids waiting for pipe EOF until the server stops.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output:
        result = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=output,
            stderr=subprocess.STDOUT, timeout=90, **options,
        )
        output.seek(0)
        message = output.read()
    if result.returncode:
        raise RuntimeError(f"{Path(command[0]).name} failed:\n{message}")
    return message.strip()


@contextmanager
def postgres_cluster():
    """Use a local disposable test DB; stop the server even if checks fail."""
    configured_bin = os.environ.get("TASK673_PG_BIN")
    portable_bin = TASK_DIR / ".local" / "pgsql" / "bin"
    installed_ctl = shutil.which("pg_ctl")
    pg_bin = (Path(configured_bin) if configured_bin else portable_bin)
    suffix = ".exe" if os.name == "nt" else ""
    if not (pg_bin / f"pg_ctl{suffix}").is_file() and installed_ctl and not configured_bin:
        pg_bin = Path(installed_ctl).parent
    pg_ctl = pg_bin / f"pg_ctl{suffix}"
    if not pg_ctl.is_file():
        raise RuntimeError(
            "PostgreSQL tools missing. Install PostgreSQL and set TASK673_PG_BIN "
            "to its bin directory, or put pg_ctl on PATH. See README.md."
        )

    local_dir = TASK_DIR / ".local"
    local_dir.mkdir(exist_ok=True)
    data_dir = local_dir / "pgdata"
    if not (data_dir / "PG_VERSION").exists():
        _run([str(pg_bin / f"initdb{suffix}"), "-D", str(data_dir),
              "-U", "task673", "-A", "trust", "-E", "UTF8", "--no-locale"])
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    _run([str(pg_ctl), "-D", str(data_dir), "-l", str(local_dir / "postgres.log"),
          "-o", f"-h 127.0.0.1 -p {port} -F", "-w", "start"])
    try:
        yield f"host=127.0.0.1 port={port} dbname=postgres user=task673 connect_timeout=10"
    finally:
        _run([str(pg_ctl), "-D", str(data_dir), "-m", "fast", "-w", "stop"])


@contextmanager
def fixture_schema(connection, contributor_column=True):
    """Create/drop only a uniquely named synthetic schema on our local cluster."""
    import uuid

    schema = "task673_" + uuid.uuid4().hex
    identifier = sql.Identifier(schema)
    connection.autocommit = True
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL((TASK_DIR / "fixtures.sql").read_text()).format(schema=identifier))
            if not contributor_column:
                cursor.execute(sql.SQL("ALTER TABLE {}.organizations DROP COLUMN is_contributor").format(identifier))
        yield schema
    finally:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(identifier))
