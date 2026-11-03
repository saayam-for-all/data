"""Run Data_ArchiveRequestData against a throwaway local PostgreSQL (issue #574).

    python scripts/archive_request_data/run_local.py [output_dir]

Writes sample_requests_enriched.csv and prints the source-vs-export validation.
"""

import json
import os
import shutil
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "src", "Data_ArchiveRequestData"))

import lambda_function  # noqa: E402
from archive_request_data_fixture import local_postgres  # noqa: E402


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with local_postgres() as settings:
        os.environ.update(settings, LOCAL_OUTPUT_DIR=out_dir)
        os.environ.pop("S3_BUCKET", None)
        response = lambda_function.lambda_handler({}, None)
    body = json.loads(response["body"])
    print("statusCode:", response["statusCode"])
    print(json.dumps(body, indent=2))
    sample = os.path.join(out_dir, "sample_requests_enriched.csv")
    shutil.move(body["local_path"], sample)
    print("sample export:", sample)
    return response["statusCode"]


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv[1] if len(sys.argv) > 1 else "docs/archive_request_data") == 200 else 1)
