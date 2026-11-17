"""Invoke the actual Lambda against synthetic local PostgreSQL data."""

import argparse
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import psycopg2

from harness import event, load_app
from local_postgres import fixture_schema, postgres_cluster


def main():
    """Print the Lambda response; always stop the local database afterwards."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--missing-contributor", action="store_true",
                        help="Use an organizations table without is_contributor")
    parser.add_argument("--sort-by-distance", action="store_true")
    parser.add_argument("--output", type=Path, help="Also save the formatted response as UTF-8 JSON")
    args = parser.parse_args()
    with postgres_cluster() as dsn:
        connection = psycopg2.connect(dsn)
        try:
            with fixture_schema(connection, not args.missing_contributor) as schema:
                with load_app(connection, schema) as app, redirect_stdout(sys.stderr):
                    response = app.handler.lambda_handler(
                        event("distance" if args.sort_by_distance else None), None,
                    )
        finally:
            connection.close()
    formatted = json.dumps({**response, "body": json.loads(response["body"])}, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(formatted + "\n", encoding="utf-8")
    print(formatted)
    return 0 if response["statusCode"] == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
