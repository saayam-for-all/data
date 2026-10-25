"""
Local test for organization_analytics.py
Bypasses get_db_connection() (which uses SSM/AWS) and connects to local Postgres instead.
Run: python3 test_organization_analytics.py
"""
import json
import psycopg2
from psycopg2.extras import RealDictCursor

import organization_analytics as oa

LOCAL_DB = {
    "host": "localhost",
    "database": "saayam_local",
    "user": "prajaktawankhede",  # change if your local pg user differs
    "port": 5432,
}


def local_get_db_connection():
    return psycopg2.connect(**LOCAL_DB)


# monkey-patch so lambda_handler uses local DB instead of SSM
oa.get_db_connection = local_get_db_connection


def run(dashboard_type, **kwargs):
    event = {"dashboard_type": dashboard_type, **kwargs}
    result = oa.lambda_handler(event, None)
    print(f"\n=== {dashboard_type} | {kwargs} ===")
    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    run("overview", time_filter="ALL")
    run("overview", time_filter="ALL", group_by="monthly")
    run("overview", time_filter="ALL", org_type="non_profit")
    run("performance", time_filter="ALL")
    run("performance", time_filter="ALL", org_size="large")
