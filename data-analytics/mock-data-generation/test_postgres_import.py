#!/usr/bin/env python3
"""Import fixtures into an ephemeral local Docker PostgreSQL/PostGIS database."""

import argparse
import csv
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from schema import BASE, DEFAULT_LOOKUP, EXPECTED_HEADERS
from validate_mock_data import validate_dataset


def run(*args: str, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    """Execute a bounded command and retain output for failure diagnostics."""
    return subprocess.run(
        args,
        input=input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=120,
    )


def main() -> None:
    """Import fixtures into a disposable container and always remove it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=BASE)
    parser.add_argument("--lookup-dir", type=Path, default=DEFAULT_LOOKUP)
    parser.add_argument("--image", default="postgis/postgis:16-3.4")
    args = parser.parse_args()
    if not shutil.which("docker"):
        parser.error(
            "Docker with a Linux container engine is required "
            "for this optional import test"
        )
    if not validate_dataset(args.data_dir, args.lookup_dir):
        raise SystemExit(1)
    name = "saayam-mock-test-" + uuid.uuid4().hex[:12]
    # No host ports, host mounts, production credentials, or persistent volumes.
    try:
        run(
            "docker",
            "run",
            "--detach",
            "--name",
            name,
            "--network",
            "none",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            args.image,
        )
        for _ in range(60):
            ready = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-U", "postgres"],
                capture_output=True,
                timeout=10,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError(
                "Temporary PostgreSQL did not become ready within 60 seconds"
            )

        def sql(payload: bytes) -> subprocess.CompletedProcess[bytes]:
            """Execute SQL with errors fatal and unaligned scalar output."""
            return run(
                "docker",
                "exec",
                "-i",
                name,
                "psql",
                "-X",
                "-A",
                "-t",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                "postgres",
                input=payload,
            )

        sql((BASE / "schema.sql").read_bytes())
        for table, key in [
            ("supporting_languages", "language_id"),
            ("user_status", "user_status_id"),
        ]:
            with (args.lookup_dir / (table + ".csv")).open(
                encoding="utf-8", newline=""
            ) as f:
                ids = [int(r[key]) for r in csv.DictReader(f)]
            payload = f"COPY virginia_dev_saayam_rdbms.{table} ({key}) FROM STDIN;\n"
            payload += "".join(f"{i}\n" for i in ids) + "\\.\n"
            sql(payload.encode())
        for filename, columns in EXPECTED_HEADERS.items():
            table = filename[:-4]
            header = (
                f"COPY virginia_dev_saayam_rdbms.{table} "
                f"({','.join(columns)}) "
                "FROM STDIN WITH (FORMAT csv, HEADER true);\n"
            )
            sql(
                header.encode()
                + (args.data_dir / filename).read_bytes().rstrip(b"\r\n")
                + b"\n\\.\n"
            )
            result = sql(
                f"SELECT count(*) FROM virginia_dev_saayam_rdbms.{table};\n".encode()
            )
            with (args.data_dir / filename).open(encoding="utf-8", newline="") as f:
                expected = sum(1 for _ in csv.DictReader(f))
            if result.stdout.decode().strip() != str(expected):
                raise RuntimeError(f"{table}: imported row count differs")
        print(
            "PASS: all 10 CSVs imported with PostgreSQL/PostGIS types and constraints."
        )
    finally:
        subprocess.run(
            ["docker", "rm", "--force", "--volumes", name],
            capture_output=True,
            timeout=30,
        )


if __name__ == "__main__":
    main()
