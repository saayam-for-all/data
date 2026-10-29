"""Run acceptance tests and the demo on a dedicated, loopback-only PostgreSQL cluster."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "data-engineering" / "docs" / "archive_requests" / "evidence"


def run(command, **kwargs):
    """Run a command without opening a visible Windows helper window."""
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.run(command, cwd=ROOT, check=True, **options, **kwargs)


def main():
    """Initialize only our cluster if needed; always stop it after verification."""
    pg_bin = Path(os.environ.get("PG_BIN", "C:/Program Files/PostgreSQL/18/bin"))
    cluster = (ROOT / ".local-postgres").resolve()
    if not cluster.is_relative_to(ROOT):
        raise ValueError("Local database must remain inside this workspace")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    if not (cluster / "PG_VERSION").exists():
        run(
            [
                str(pg_bin / "initdb.exe"),
                "-D",
                str(cluster),
                "-U",
                "archive_test",
                "-A",
                "trust",
                "--encoding=UTF8",
                "--locale=C",
            ]
        )
    run(
        [
            str(pg_bin / "pg_ctl.exe"),
            "-D",
            str(cluster),
            "-l",
            str(EVIDENCE / "postgres-local.log"),
            "-o",
            "-h 127.0.0.1 -p 55740 -c max_connections=20 -c shared_buffers=16MB",
            "-w",
            "start",
        ]
    )
    environment = dict(
        os.environ,
        TEST_DATABASE_URL="postgresql://archive_test@127.0.0.1:55740/postgres?connect_timeout=5",
    )
    try:
        with (EVIDENCE / "test-output.txt").open("w", encoding="utf-8") as output:
            run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "data-engineering/tests/test_archive_requests.py",
                    "-q",
                    "--tb=short",
                    f"--junitxml={EVIDENCE / 'test-results.xml'}",
                ],
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        print((EVIDENCE / "test-output.txt").read_text(encoding="utf-8"))
        with (EVIDENCE / "local-execution.txt").open("w", encoding="utf-8") as output:
            run(
                [sys.executable, str(Path(__file__).with_name("run_local.py"))],
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        print((EVIDENCE / "local-execution.txt").read_text(encoding="utf-8"))
        run([sys.executable, str(Path(__file__).with_name("build_evidence.py"))])
    finally:
        run(
            [str(pg_bin / "pg_ctl.exe"), "-D", str(cluster), "-m", "fast", "-w", "stop"]
        )


if __name__ == "__main__":
    main()
