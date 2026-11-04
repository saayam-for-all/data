"""Package a Linux x86_64 Python 3.12 Lambda without deploying it."""

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "data-engineering" / "src" / "Data_ArchiveRequestData"


def main():
    """Install target-platform wheels into a disposable directory and zip them."""
    build = ROOT / ".build"
    build.mkdir(exist_ok=True)
    destination = build / "Data_ArchiveRequestData.zip"
    with tempfile.TemporaryDirectory(prefix="lambda-", dir=build) as staging:
        stage = Path(staging)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target",
                str(stage),
                "--platform",
                "manylinux_2_28_x86_64",
                "--platform",
                "manylinux2014_x86_64",
                "--implementation",
                "cp",
                "--python-version",
                "3.12",
                "--only-binary=:all:",
                "--no-compile",
                "-r",
                str(SOURCE / "requirements.txt"),
            ],
            check=True,
        )
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(stage.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(stage).as_posix())
            for name in ("lambda_function.py", "reference_mapping.json"):
                archive.write(SOURCE / name, name)
    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        assert "lambda_function.py" in names and "reference_mapping.json" in names
        assert any(name.endswith(".so") and "psycopg" in name for name in names)
        assert not any(name.endswith((".pyd", ".dll")) for name in names)
    print(f"Linux Python 3.12 x86_64 package validated: {destination}")


if __name__ == "__main__":
    main()
