"""Run local tests and preserve their real output for the evidence report."""

import subprocess
import sys
from pathlib import Path


def main():
    """Save the test transcript and propagate the subprocess exit status."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    evidence = root / "evidence"
    evidence.mkdir(exist_ok=True)
    (evidence / "tests.txt").write_text(result.stdout, encoding="utf-8")
    print(result.stdout)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
