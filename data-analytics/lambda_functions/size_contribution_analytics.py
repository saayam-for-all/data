"""Size and Contribution Analytics Lambda Handler.

Computes metrics for the Organization Analytics dashboard which includes two charts:
  1. Organizations By Size: Counts organizations grouped by size category.
  2. Collaborators vs Contributors: Independent counts and percentages of
     collaborators and contributors within the filtered organizations.

Supported filters in event body:
  - country: Country name or country code or 'All' (default)
  - organization_type: 'non_profit', 'for_profit', or 'ALL' (default)
  - size_start_date: Custom start date for Organizations By Size chart
  - size_end_date: Custom end date for Organizations By Size chart
  - contribution_start_date: Custom start date for Collaborators vs Contributors chart
  - contribution_end_date: Custom end date for Collaborators vs Contributors chart

    All the fields are optional string.
    For both charts, providing a start date requires an end date, and vice versa.
    All dates must be in in ISO-8601 format (YYYY-MM-DD).

Response:
  - If no custom date parameters are provided: Returns 4 fixed time buckets
    ('7D', '30D', '1Y', 'All') plus an empty 'Custom' bucket.
  - If either or both custom date ranges are provided: Returns only the 'Custom'
    bucket with the corresponding charts populated.

Environment Configuration:
- USE_MOCK_DATA (str): Toggles data backend.
    If "true", provides analytics based on local mock CSV via Pandas.
    Otherwise, provides analytics based on PostgreSQL database.
"""

import json
import os
from datetime import date

USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "true") == "true"
if USE_MOCK_DATA:
    import pandas as pd

    DEFAULT_MOCK_DIR = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "sql")
    )
    MOCK_DATA_DIR = os.getenv("MOCK_DATA_DIR", DEFAULT_MOCK_DIR)
else:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor

        SCHEMA_NAME = "virginia_dev_saayam_rdbms"
        TABLE_ORG = f"{SCHEMA_NAME}.organizations"
        TABLE_STATE = f"{SCHEMA_NAME}.state"
        TABLE_COUNTRY = f"{SCHEMA_NAME}.country"
    except ImportError:
        psycopg2 = None
        RealDictCursor = None


def parse_event_body(event):
    if not event:
        return {}
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body
    return {}


def get_date_validation_errors(prefix, start_date, end_date):
    """Returns errors in start/end date pair."""
    errs = []
    if start_date and not end_date:
        errs.append(
            f"{prefix}_end_date is required when {prefix}_start_date is provided"
        )
    if end_date and not start_date:
        errs.append(
            f"{prefix}_start_date is required when {prefix}_end_date is provided"
        )
    if start_date and end_date:
        try:
            start_dt = date.fromisoformat(start_date)
        except ValueError:
            errs.append(f"Invalid date format for {prefix}_start_date. Use YYYY-MM-DD")

        try:
            end_dt = date.fromisoformat(end_date)
        except ValueError:
            errs.append(f"Invalid date format for {prefix}_end_date. Use YYYY-MM-DD")
        if errs:
            return errs

        if start_dt > end_dt:
            return [f"{prefix}_start_date must be before {prefix}_end_date"]
    return errs


def prepare_filter_params(request_body):
    """Extract, normalize and validate filter parameters from a request body."""
    errs = []
    country = request_body.get("country", "ALL").lower()

    org_type = request_body.get("organization_type", "ALL").lower()
    valid_org_types = {"non_profit", "for_profit", "all"}
    if org_type not in valid_org_types:
        errs.append(f"Invalid organization_type: {org_type}")

    size_start_date = request_body.get("size_start_date")
    size_end_date = request_body.get("size_end_date")
    errs.extend(get_date_validation_errors("size", size_start_date, size_end_date))

    contrib_start_date = request_body.get("contribution_start_date")
    contrib_end_date = request_body.get("contribution_end_date")
    errs.extend(
        get_date_validation_errors("contribution", contrib_start_date, contrib_end_date)
    )

    if errs:
        raise ValueError("; ".join(errs))

    return {
        "country": country,
        "org_type": org_type,
        "size_start_date": size_start_date,
        "size_end_date": size_end_date,
        "contrib_start_date": contrib_start_date,
        "contrib_end_date": contrib_end_date,
    }


def get_default_response(custom_only=False):
    """Empty-but-valid default response so the dashboard never breaks on a 500."""
    if custom_only:
        return {
            "Custom": {"organizations_by_size": [], "collaborator_vs_contributor": []}
        }
    else:
        return {
            "7D": {"organizations_by_size": [], "collaborator_vs_contributor": []},
            "30D": {"organizations_by_size": [], "collaborator_vs_contributor": []},
            "1Y": {"organizations_by_size": [], "collaborator_vs_contributor": []},
            "All": {"organizations_by_size": [], "collaborator_vs_contributor": []},
            "Custom": {"organizations_by_size": [], "collaborator_vs_contributor": []},
        }


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "saayam_db"),
        user=os.environ.get("DB_USER", os.getenv("USER")),
        password=os.environ.get("DB_PASSWORD", ""),
    )


def load_csv_df():
    """
    Load mock csv files to pandas DataFrame.
    Expected files in MOCK_DATA_DIR: organizations.csv, state.csv, country.csv
    """
    org_df = pd.read_csv(os.path.join(MOCK_DATA_DIR, "organizations.csv"))
    if "is_contributor" not in org_df.columns:
        org_df["is_contributor"] = False
    required_cols = [
        "org_id",
        "state_id",
        "org_type",
        "org_size",
        "is_contributor",
        "is_collaborator",
        "created_at",
    ]
    org_df = org_df[required_cols]

    state_df = pd.read_csv(
        os.path.join(MOCK_DATA_DIR, "state.csv"),
        usecols=["state_id", "country_id"],
    )
    country_df = pd.read_csv(
        os.path.join(MOCK_DATA_DIR, "country.csv"),
        usecols=["country_id", "country_name", "country_code"],
    )

    org_df["org_size"] = org_df["org_size"].str.lower()
    org_df["org_type"] = org_df["org_type"].str.lower().str.replace("-", "_")
    org_df["created_at"] = pd.to_datetime(org_df["created_at"])

    country_df["country_code"] = country_df["country_code"].str.lower()
    country_df["country_name"] = country_df["country_name"].str.lower()

    df = org_df.merge(state_df, on="state_id", how="left")
    df = df.merge(country_df, on="country_id", how="left")
    return df


def _apply_common_filters(df, params):
    """Slices DataFrame based on country and org_type filters common to both analytics"""
    if params["country"] != "all":
        match_code = df["country_code"] == params["country"]
        match_name = df["country_name"] == params["country"]
        df = df[match_code | match_name]

    if params["org_type"] != "all":
        df = df[df["org_type"] == params["org_type"]]

    return df


def get_size_analytics_df(df):
    """Gets organization counts by size category using DataFrame"""
    org_size_counts = df.groupby("org_size").size().to_dict()
    size_analytics = [
        {"size": str(size), "count": int(org_size_counts[size])}
        for size in ("small", "medium", "large")
        if size in org_size_counts
    ]
    return size_analytics


def get_contrib_analytics_df(df):
    """Gets collaborator and contributor counts using DataFrame"""
    contrib_analytics = []
    total_orgs = len(df)
    if total_orgs == 0:
        return [
            {"type": "Collaborator", "count": 0, "percentage": 0.0},
            {"type": "Contributor", "count": 0, "percentage": 0.0},
        ]

    for contrib_type in ("Collaborator", "Contributor"):
        count = int(df[f"is_{contrib_type.lower()}"].sum())
        percentage = round(count / total_orgs * 100, 1)
        contrib_analytics.append(
            {"type": contrib_type, "count": count, "percentage": percentage}
        )
    return contrib_analytics


def window(df, start_date, end_date):
    """Slices DataFrame between start_date and end_date (inclusive)"""
    start_ts = pd.to_datetime(start_date).normalize()
    end_ts = pd.to_datetime(end_date).normalize() + pd.Timedelta(days=1)
    df_window = df[(df["created_at"] >= start_ts) & (df["created_at"] < end_ts)]
    return df_window


def get_analytics_df(df, params):
    """Gets size and contribution analytics for given filter params using DataFrames"""
    df = _apply_common_filters(df, params)

    if not params["size_start_date"] and not params["contrib_start_date"]:
        response_body = get_default_response()
        today = pd.Timestamp.now().normalize()

        # Ordered from largest window to smallest window for optimization
        cutoffs = [
            ("All", None),
            ("1Y", today - pd.DateOffset(years=1)),
            ("30D", today - pd.Timedelta(days=30)),
            ("7D", today - pd.Timedelta(days=7)),
        ]

        for bucket, cutoff in cutoffs:
            bucket_df = df[df["created_at"] >= cutoff] if cutoff is not None else df
            response_body[bucket] = {
                "organizations_by_size": get_size_analytics_df(bucket_df),
                "collaborator_vs_contributor": get_contrib_analytics_df(bucket_df),
            }

    else:
        response_body = get_default_response(custom_only=True)

        if params["size_start_date"]:
            df_size = window(df, params["size_start_date"], params["size_end_date"])
            size_analytics = get_size_analytics_df(df_size)
            response_body["Custom"]["organizations_by_size"] = size_analytics

        if params["contrib_start_date"]:
            df_contrib = window(
                df, params["contrib_start_date"], params["contrib_end_date"]
            )
            contrib_analytics = get_contrib_analytics_df(df_contrib)
            response_body["Custom"]["collaborator_vs_contributor"] = contrib_analytics

    return response_body


def get_base_sql_parts(params):
    """Get base conditions, arguments and table joins used by all queries"""
    conditions = []
    sql_args = []

    if params["country"] != "all":
        # Country filter (matches code or name case-insensitively)
        conditions.append("(LOWER(c.country_code) = %s OR LOWER(c.country_name) = %s)")
        sql_args.extend([params["country"], params["country"]])

    if params["org_type"] != "all":
        conditions.append("LOWER(REPLACE(o.org_type, '-', '_')) = %s")
        sql_args.append(params["org_type"])

    base_from = f"""
        FROM {TABLE_ORG} o
        LEFT JOIN {TABLE_STATE} s ON o.state_id = s.state_id
        LEFT JOIN {TABLE_COUNTRY} c ON s.country_id = c.country_id 
    """
    return conditions, sql_args, base_from


def column_exists(cursor, table_name, column_name):
    """Check whether a column exists in the current database schema."""
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        LIMIT 1;
        """,
        (table_name, column_name),
    )
    return cursor.fetchone() is not None


def fetch_size_analytics(cursor, params):
    """Fetches organization counts by size category for all four buckets from database"""
    base_conditions, sql_args, base_from = get_base_sql_parts(params)
    base_where = (" WHERE " + " AND ".join(base_conditions)) if base_conditions else ""

    query = f"""
        SELECT
            LOWER(o.org_size) AS size,
            COUNT(*) AS count_all,
            COUNT(*) FILTER(WHERE o.created_at >= CURRENT_DATE - INTERVAL '1 year') AS count_1y,
            COUNT(*) FILTER (WHERE o.created_at >= CURRENT_DATE - INTERVAL '30 days') AS count_30d,
            COUNT(*) FILTER (WHERE o.created_at >= CURRENT_DATE - INTERVAL '7 days') AS count_7d
        {base_from}
        {base_where}
        GROUP BY LOWER(o.org_size)
        ORDER BY 
            CASE LOWER(o.org_size)
                WHEN 'small' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'large' THEN 3
                ELSE 4
            END;
    """
    cursor.execute(query, sql_args)
    rows = cursor.fetchall()
    # each row is a dict with size, count_All, count_1Y, count30D, count_7D

    buckets = [
        ("7D", "7d"),
        ("30D", "30d"),
        ("1Y", "1y"),
        ("All", "all"),
    ]

    size_analytics = {"7D": [], "30D": [], "1Y": [], "All": []}
    for row in rows:
        size = row["size"]
        for bucket, suffix in buckets:
            count = row[f"count_{suffix}"]
            if count > 0:
                size_analytics[bucket].append({"size": size, "count": count})
    return size_analytics


def fetch_contrib_analytics(cursor, params):
    """Fetches collaborator and contributor counts for all four buckets from database"""
    base_conditions, sql_args, base_from = get_base_sql_parts(params)
    base_where = (" WHERE " + " AND ".join(base_conditions)) if base_conditions else ""

    has_contributor_col = column_exists(cursor, "organizations", "is_contributor")
    contrib_condition = "o.is_contributor = true" if has_contributor_col else "false"

    query = f"""
        SELECT
            COUNT(*) AS total_all,
            COUNT(*) FILTER (WHERE o.created_at >= CURRENT_DATE - INTERVAL '1 year') AS total_1y,
            COUNT(*) FILTER (WHERE o.created_at >= CURRENT_DATE - INTERVAL '30 days') AS total_30d,
            COUNT(*) FILTER (WHERE o.created_at >= CURRENT_DATE - INTERVAL '7 days') AS total_7d,

            COUNT(*) FILTER (WHERE o.is_collaborator = true) AS collab_all,
            COUNT(*) FILTER (WHERE o.is_collaborator = true 
                AND o.created_at >= CURRENT_DATE - INTERVAL '1 year') AS collab_1y,
            COUNT(*) FILTER (WHERE o.is_collaborator = true 
                AND o.created_at >= CURRENT_DATE - INTERVAL '30 days') AS collab_30d,
            COUNT(*) FILTER (WHERE o.is_collaborator = true 
                AND o.created_at >= CURRENT_DATE - INTERVAL '7 days') AS collab_7d,

            COUNT(*) FILTER (WHERE {contrib_condition}) AS contrib_all,
            COUNT(*) FILTER (WHERE {contrib_condition} AND 
                o.created_at >= CURRENT_DATE - INTERVAL '1 year') AS contrib_1y,
            COUNT(*) FILTER (WHERE {contrib_condition} AND 
                o.created_at >= CURRENT_DATE - INTERVAL '30 days') AS contrib_30d,
            COUNT(*) FILTER (WHERE {contrib_condition} AND 
                o.created_at >= CURRENT_DATE - INTERVAL '7 days') AS contrib_7d
        {base_from}
        {base_where};
    """

    cursor.execute(query, sql_args)
    row = cursor.fetchone()

    buckets = [
        ("7D", "7d"),
        ("30D", "30d"),
        ("1Y", "1y"),
        ("All", "all"),
    ]

    contrib_analytics = {}
    for bucket, suffix in buckets:
        total = row[f"total_{suffix}"]
        collab_count = row[f"collab_{suffix}"]
        contrib_count = row[f"contrib_{suffix}"]

        collab_pct = round((collab_count / total) * 100, 1) if total > 0 else 0.0
        contrib_pct = round((contrib_count / total) * 100, 1) if total > 0 else 0.0

        contrib_analytics[bucket] = [
            {"type": "Collaborator", "count": collab_count, "percentage": collab_pct},
            {"type": "Contributor", "count": contrib_count, "percentage": contrib_pct},
        ]

    return contrib_analytics


def fetch_size_analytics_custom(cursor, params):
    """Fetches organization counts by size category for Custom bucket from database"""
    base_conditions, sql_args, base_from = get_base_sql_parts(params)
    base_conditions.append(
        "o.created_at >= %s::date AND o.created_at < (%s::date + INTERVAL '1 day')"
    )
    sql_args.extend([params["size_start_date"], params["size_end_date"]])
    base_where = (" WHERE " + " AND ".join(base_conditions)) if base_conditions else ""

    query = f"""
        SELECT
            LOWER(o.org_size) AS size,
            COUNT(*) AS count
        {base_from}
        {base_where}
        GROUP BY LOWER(o.org_size)
        ORDER BY 
            CASE LOWER(o.org_size)
                WHEN 'small' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'large' THEN 3
                ELSE 4
            END;
    """
    cursor.execute(query, sql_args)
    rows = cursor.fetchall()

    size_analytics_custom = []
    for row in rows:
        size = row["size"]
        count = row["count"]
        if count > 0:
            size_analytics_custom.append({"size": size, "count": count})
    return size_analytics_custom


def fetch_contrib_analytics_custom(cursor, params):
    """Fetches collaborator and contributor counts for Custom bucket from database"""
    base_conditions, sql_args, base_from = get_base_sql_parts(params)
    base_conditions.append(
        "o.created_at >= %s::date AND o.created_at < (%s::date + INTERVAL '1 day')"
    )
    sql_args.extend([params["contrib_start_date"], params["contrib_end_date"]])
    base_where = (" WHERE " + " AND ".join(base_conditions)) if base_conditions else ""

    has_contributor_col = column_exists(cursor, "organizations", "is_contributor")
    contrib_condition = "o.is_contributor = true" if has_contributor_col else "false"

    query = f"""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE o.is_collaborator = true) AS collab,
                COUNT(*) FILTER (WHERE {contrib_condition}) AS contrib
            {base_from}
            {base_where};
        """
    cursor.execute(query, sql_args)
    row = cursor.fetchone()

    total = row["total"]
    collab_count = row["collab"]
    contrib_count = row["contrib"]

    collab_pct = round((collab_count / total) * 100, 1) if total > 0 else 0.0
    contrib_pct = round((contrib_count / total) * 100, 1) if total > 0 else 0.0

    contrib_analytics = [
        {"type": "Collaborator", "count": collab_count, "percentage": collab_pct},
        {"type": "Contributor", "count": contrib_count, "percentage": contrib_pct},
    ]
    return contrib_analytics


def fetch_analytics_db(cursor, params):
    """Fetches size and contribution analytics for given filter params from database"""
    if not params["size_start_date"] and not params["contrib_start_date"]:
        response_body = get_default_response()

        size_analytics = fetch_size_analytics(cursor, params)
        contrib_analytics = fetch_contrib_analytics(cursor, params)

        for bucket in ("7D", "30D", "1Y", "All"):
            response_body[bucket]["organizations_by_size"] = size_analytics[bucket]
            response_body[bucket]["collaborator_vs_contributor"] = contrib_analytics[
                bucket
            ]
    else:
        response_body = get_default_response(custom_only=True)
        if params["size_start_date"]:
            size_analytics = fetch_size_analytics_custom(cursor, params)
            response_body["Custom"]["organizations_by_size"] = size_analytics

        if params["contrib_start_date"]:
            contrib_analytics = fetch_contrib_analytics_custom(cursor, params)
            response_body["Custom"]["collaborator_vs_contributor"] = contrib_analytics

    return response_body


def lambda_handler(event, context):
    try:
        request_body = parse_event_body(event)
        params = prepare_filter_params(request_body)
        if USE_MOCK_DATA:
            df = load_csv_df()
            response_body = get_analytics_df(df, params)
        else:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            response_body = fetch_analytics_db(cursor, params)

        return build_response(200, response_body)

    except ValueError as e:
        return build_response(400, {"value_error": str(e)})
    except Exception as e:
        return build_response(500, {"error": str(e)})


if __name__ == "__main__":
    test_events = [
        ("No body ({})", {}),
        ("Country Filter (USA)", {"country": "USA"}),
        ("Org Type Filter (non_profit)", {"organization_type": "non_profit"}),
        (
            "Only size Custom range",
            {"size_start_date": "2023-01-01", "size_end_date": "2023-12-30"},
        ),
        (
            "Only contribution Custom range",
            {
                "contribution_start_date": "2023-01-01",
                "contribution_end_date": "2023-12-30",
            },
        ),
        (
            "Both Custom ranges supplied",
            {
                "country": "USA",
                "organization_type": "non_profit",
                "size_start_date": "2023-01-01",
                "size_end_date": "2023-12-30",
                "contribution_start_date": "2023-01-01",
                "contribution_end_date": "2023-12-30",
            },
        ),
    ]

    for i, (label, payload) in enumerate(test_events):
        print("=" * 80)
        print(f"TEST {i}: {label}")
        res = lambda_handler(payload, None)
        print(f"Status: {res['statusCode']}")
        print(json.dumps(json.loads(res["body"]), indent=2))
