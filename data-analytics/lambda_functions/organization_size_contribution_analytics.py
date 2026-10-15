import json
import os
from datetime import date, datetime, timedelta

import pandas as pd

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None


FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
DB_SCHEMA = os.getenv("ORG_ANALYTICS_SCHEMA", "virginia_dev_saayam_rdbms")
ORGANIZATIONS_TABLE = os.getenv("ORGANIZATIONS_TABLE", f"{DB_SCHEMA}.organizations")
STATES_TABLE = os.getenv("STATES_TABLE", f"{DB_SCHEMA}.states")
COUNTRIES_TABLE = os.getenv("COUNTRIES_TABLE", f"{DB_SCHEMA}.countries")


def parse_event_body(event):
    if not event:
        return {}

    body = event.get("body") if isinstance(event, dict) else None
    if body is None:
        return event if isinstance(event, dict) else {}
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def empty_bucket():
    return {
        "organizations_by_size": [],
        "collaborator_vs_contributor": [],
    }


def parse_date(value, field_name):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be in YYYY-MM-DD format")


def validate_date_pair(params, start_key, end_key):
    start_value = params.get(start_key)
    end_value = params.get(end_key)
    has_start = start_value not in (None, "")
    has_end = end_value not in (None, "")

    if has_start != has_end:
        raise ValueError(f"{start_key} and {end_key} must be supplied together")
    if not has_start:
        return None

    start_date = parse_date(start_value, start_key)
    end_date = parse_date(end_value, end_key)
    if start_date > end_date:
        raise ValueError(f"{start_key} must be on or before {end_key}")
    return start_date, end_date


def normalize_filter_value(value):
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def is_all_filter(value):
    return value in (None, "") or normalize_filter_value(value) in {"all", "all_countries", "all_organizations"}


def normalize_bool_series(series):
    if series is None:
        return pd.Series(dtype=bool)
    return series.fillna(False).map(
        lambda value: str(value).strip().lower() in {"true", "t", "1", "yes", "y"}
    )


def load_mock_data(mock_data_dir):
    org_path = os.path.join(mock_data_dir, "organizations.csv")
    states_path = first_existing_path(mock_data_dir, ("states.csv", "state.csv"))
    countries_path = first_existing_path(mock_data_dir, ("countries.csv", "country.csv"))

    organizations = pd.read_csv(org_path)
    states = pd.read_csv(states_path)
    countries = pd.read_csv(countries_path)

    return prepare_mock_dataframe(organizations, states, countries)


def first_existing_path(directory, filenames):
    for filename in filenames:
        path = os.path.join(directory, filename)
        if os.path.exists(path):
            return path
    raise FileNotFoundError(f"Missing one of: {', '.join(filenames)} in {directory}")


def prepare_mock_dataframe(organizations, states, countries):
    orgs = organizations.copy()
    states_df = states.copy()
    countries_df = countries.copy()

    for frame in (orgs, states_df, countries_df):
        frame.columns = [str(column).strip() for column in frame.columns]

    if "state_id" in orgs.columns and "state_id" in states_df.columns:
        orgs = orgs.merge(states_df[["state_id", "country_id"]], on="state_id", how="left")

    country_columns = ["country_id"]
    for optional_column in ("country_code", "country_name"):
        if optional_column in countries_df.columns:
            country_columns.append(optional_column)
    if "country_id" in orgs.columns and "country_id" in countries_df.columns:
        orgs = orgs.merge(countries_df[country_columns], on="country_id", how="left")

    required_defaults = {
        "org_size": None,
        "org_type": None,
        "is_collaborator": False,
        "created_at": None,
    }
    for column, default in required_defaults.items():
        if column not in orgs.columns:
            orgs[column] = default
    if "is_contributor" not in orgs.columns:
        orgs["is_contributor"] = False

    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce").dt.date
    orgs["is_collaborator"] = normalize_bool_series(orgs["is_collaborator"])
    orgs["is_contributor"] = normalize_bool_series(orgs["is_contributor"])
    return orgs


def apply_common_filters(df, country, organization_type):
    filtered = df.copy()

    if not is_all_filter(country):
        country_value = normalize_filter_value(country)
        country_mask = pd.Series(False, index=filtered.index)
        if "country_code" in filtered.columns:
            country_mask = country_mask | filtered["country_code"].fillna("").map(normalize_filter_value).eq(country_value)
        if "country_name" in filtered.columns:
            country_mask = country_mask | filtered["country_name"].fillna("").map(normalize_filter_value).eq(country_value)
        filtered = filtered[country_mask]

    if not is_all_filter(organization_type):
        type_value = normalize_filter_value(organization_type)
        filtered = filtered[filtered["org_type"].fillna("").map(normalize_filter_value).eq(type_value)]

    return filtered


def filter_by_date_window(df, start_date=None, end_date=None):
    filtered = df[df["created_at"].notna()]
    if start_date:
        filtered = filtered[filtered["created_at"] >= start_date]
    if end_date:
        filtered = filtered[filtered["created_at"] <= end_date]
    return filtered


def fixed_bucket_window(bucket):
    today = date.today()
    if bucket == "7D":
        return today - timedelta(days=7), today
    if bucket == "30D":
        return today - timedelta(days=30), today
    if bucket == "1Y":
        return today - timedelta(days=365), today
    if bucket == "All":
        return None, None
    raise ValueError(f"Unsupported bucket: {bucket}")


def organizations_by_size(df):
    if df.empty:
        return []
    counts = (
        df[df["org_size"].notna()]
        .groupby("org_size", dropna=True)
        .size()
        .reset_index(name="count")
        .sort_values(["count", "org_size"], ascending=[False, True])
    )
    return [{"size": row["org_size"], "count": int(row["count"])} for _, row in counts.iterrows()]


def collaborator_vs_contributor(df):
    total = len(df)
    if total == 0:
        return []

    collaborator_count = int(df["is_collaborator"].sum()) if "is_collaborator" in df.columns else 0
    contributor_count = int(df["is_contributor"].sum()) if "is_contributor" in df.columns else 0
    return [
        {
            "type": "Collaborator",
            "count": collaborator_count,
            "percentage": round((collaborator_count / total) * 100, 1),
        },
        {
            "type": "Contributor",
            "count": contributor_count,
            "percentage": round((contributor_count / total) * 100, 1),
        },
    ]


def build_bucket(df, start_date=None, end_date=None):
    window_df = filter_by_date_window(df, start_date, end_date)
    return {
        "organizations_by_size": organizations_by_size(window_df),
        "collaborator_vs_contributor": collaborator_vs_contributor(window_df),
    }


def build_mock_response(params):
    size_range = validate_date_pair(params, "size_start_date", "size_end_date")
    contribution_range = validate_date_pair(params, "contribution_start_date", "contribution_end_date")

    mock_data_dir = os.getenv("MOCK_DATA_DIR", ".")
    df = load_mock_data(mock_data_dir)
    df = apply_common_filters(
        df,
        params.get("country", "ALL"),
        params.get("organization_type", "ALL"),
    )

    if size_range or contribution_range:
        custom = empty_bucket()
        if size_range:
            custom["organizations_by_size"] = organizations_by_size(filter_by_date_window(df, *size_range))
        if contribution_range:
            custom["collaborator_vs_contributor"] = collaborator_vs_contributor(filter_by_date_window(df, *contribution_range))
        return {"Custom": custom}

    response = {}
    for bucket in FIXED_BUCKETS:
        response[bucket] = build_bucket(df, *fixed_bucket_window(bucket))
    response["Custom"] = empty_bucket()
    return response


def get_db_connection():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required when USE_MOCK_DATA is not true")

    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode=os.getenv("DB_SSLMODE", "require"),
    )


def build_date_sql(bucket=None, start_date=None, end_date=None):
    if bucket == "7D":
        return "AND o.created_at::date BETWEEN CURRENT_DATE - INTERVAL '7 days' AND CURRENT_DATE", []
    if bucket == "30D":
        return "AND o.created_at::date BETWEEN CURRENT_DATE - INTERVAL '30 days' AND CURRENT_DATE", []
    if bucket == "1Y":
        return "AND o.created_at::date BETWEEN CURRENT_DATE - INTERVAL '1 year' AND CURRENT_DATE", []
    if start_date and end_date:
        return "AND o.created_at::date BETWEEN %s AND %s", [start_date.isoformat(), end_date.isoformat()]
    return "", []


def build_common_sql(params, sql_params):
    where = ""
    country = params.get("country", "ALL")
    organization_type = params.get("organization_type", "ALL")

    if not is_all_filter(country):
        where += " AND (LOWER(c.country_code) = LOWER(%s) OR LOWER(c.country_name) = LOWER(%s))"
        sql_params.extend([country, country])
    if not is_all_filter(organization_type):
        where += " AND REPLACE(REPLACE(LOWER(o.org_type), '-', '_'), ' ', '_') = %s"
        sql_params.append(normalize_filter_value(organization_type))
    return where


def fetch_organizations_by_size(cursor, params, bucket=None, start_date=None, end_date=None):
    sql_params = []
    common_where = build_common_sql(params, sql_params)
    date_where, date_params = build_date_sql(bucket, start_date, end_date)
    sql_params.extend(date_params)

    cursor.execute(
        f"""
        SELECT o.org_size AS size, COUNT(*) AS count
        FROM {ORGANIZATIONS_TABLE} o
        LEFT JOIN {STATES_TABLE} s ON o.state_id = s.state_id
        LEFT JOIN {COUNTRIES_TABLE} c ON s.country_id = c.country_id
        WHERE o.created_at IS NOT NULL
        {common_where}
        {date_where}
        GROUP BY o.org_size
        ORDER BY count DESC, o.org_size ASC;
        """,
        sql_params,
    )
    rows = cursor.fetchall()
    return [{"size": row["size"], "count": int(row["count"])} for row in rows if row["size"] is not None]


def fetch_collaborator_vs_contributor(cursor, params, bucket=None, start_date=None, end_date=None):
    sql_params = []
    common_where = build_common_sql(params, sql_params)
    date_where, date_params = build_date_sql(bucket, start_date, end_date)
    sql_params.extend(date_params)

    cursor.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE o.is_collaborator IS TRUE) AS collaborator_count,
            COUNT(*) FILTER (WHERE COALESCE(o.is_contributor, FALSE) IS TRUE) AS contributor_count
        FROM {ORGANIZATIONS_TABLE} o
        LEFT JOIN {STATES_TABLE} s ON o.state_id = s.state_id
        LEFT JOIN {COUNTRIES_TABLE} c ON s.country_id = c.country_id
        WHERE o.created_at IS NOT NULL
        {common_where}
        {date_where};
        """,
        sql_params,
    )
    row = cursor.fetchone()
    total = int(row["total"] or 0)
    if total == 0:
        return []

    collaborator_count = int(row["collaborator_count"] or 0)
    contributor_count = int(row["contributor_count"] or 0)
    return [
        {"type": "Collaborator", "count": collaborator_count, "percentage": round((collaborator_count / total) * 100, 1)},
        {"type": "Contributor", "count": contributor_count, "percentage": round((contributor_count / total) * 100, 1)},
    ]


def build_db_response(params):
    size_range = validate_date_pair(params, "size_start_date", "size_end_date")
    contribution_range = validate_date_pair(params, "contribution_start_date", "contribution_end_date")

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if size_range or contribution_range:
            custom = empty_bucket()
            if size_range:
                custom["organizations_by_size"] = fetch_organizations_by_size(cursor, params, start_date=size_range[0], end_date=size_range[1])
            if contribution_range:
                custom["collaborator_vs_contributor"] = fetch_collaborator_vs_contributor(cursor, params, start_date=contribution_range[0], end_date=contribution_range[1])
            return {"Custom": custom}

        response = {}
        for bucket in FIXED_BUCKETS:
            response[bucket] = {
                "organizations_by_size": fetch_organizations_by_size(cursor, params, bucket=bucket),
                "collaborator_vs_contributor": fetch_collaborator_vs_contributor(cursor, params, bucket=bucket),
            }
        response["Custom"] = empty_bucket()
        return response
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def lambda_handler(event, context):
    params = parse_event_body(event)
    try:
        if os.getenv("USE_MOCK_DATA", "false").lower() == "true":
            response_body = build_mock_response(params)
        else:
            response_body = build_db_response(params)
        return build_response(200, response_body)
    except ValueError as exc:
        return build_response(400, {"error": str(exc)})
    except Exception as exc:
        return build_response(500, {"error": str(exc)})


if __name__ == "__main__":
    sample_events = [
        {},
        {"country": "USA"},
        {"organization_type": "non_profit"},
        {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"},
        {"contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"},
        {
            "size_start_date": "2026-01-01",
            "size_end_date": "2026-06-30",
            "contribution_start_date": "2025-01-01",
            "contribution_end_date": "2025-12-31",
        },
    ]

    for sample_event in sample_events:
        print(json.dumps(sample_event, indent=2))
        print(json.dumps(json.loads(lambda_handler(sample_event, None)["body"]), indent=2))
