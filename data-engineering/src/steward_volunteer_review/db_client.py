"""
Database connection helpers.

Credentials and connection details come entirely from environment
variables - nothing is hardcoded, including AWS Parameter Store paths.

The review queue spans two regional databases (Virginia / us-east-1 and
Ireland / eu-west-1), so this exposes one connection per configured
region rather than a single get_connection(). Expected env vars per
region (example for Virginia): DB_VIRGINIA_HOST, DB_VIRGINIA_PORT,
DB_VIRGINIA_NAME, DB_VIRGINIA_USER, DB_VIRGINIA_PASSWORD.

NOTE: per CONTRIBUTING.md, shared DB connection code belongs in
`src/utils/db_client.py`. Check whether that file already exists in the
repo before adding this one - reuse it instead of duplicating if so.
"""

import os
from typing import Dict

import psycopg2

# Region keys map to env var prefixes, e.g. DB_VIRGINIA_HOST, DB_IRELAND_HOST
REGIONS = ["VIRGINIA", "IRELAND"]


def get_connection(region: str):
    """Return a new psycopg2 connection for the given region."""
    prefix = f"DB_{region}"
    return psycopg2.connect(
        host=os.environ[f"{prefix}_HOST"],
        port=os.environ.get(f"{prefix}_PORT", "5432"),
        dbname=os.environ[f"{prefix}_NAME"],
        user=os.environ[f"{prefix}_USER"],
        password=os.environ[f"{prefix}_PASSWORD"],
    )


def get_region_connections() -> Dict[str, "psycopg2.extensions.connection"]:
    """Open one connection per region configured in REGIONS."""
    return {region: get_connection(region) for region in REGIONS}
