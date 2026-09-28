"""
Size & Contribution Analytics API for the Organization Dashboard (Issue #376).

Standalone Lambda function that retrieves and aggregates organization analytics:
1. Organizations by Size (organization counts by size category).
2. Collaborators vs Contributors (collaborator count vs contributor count independently).

Response behavior:
- When neither Custom date range pair is supplied:
  Returns exactly 5 top-level keys: "7D", "30D", "1Y", "All", "Custom" (with Custom charts empty).
- When either or both Custom date range pairs are supplied:
  Returns only the "Custom" top-level key (no fixed buckets).
  - size_start_date / size_end_date populates organizations_by_size.
  - contribution_start_date / contribution_end_date populates collaborator_vs_contributor.
  - Both can be supplied together and both get evaluated independently.
"""

import os
import json
from datetime import datetime, date, timedelta, timezone
import pandas as pd

# Optional PostgreSQL driver for production path
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

# Default search directories for mock CSVs
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mock-data-generation")
SQL_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sql")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def parse_event_body(event):
    """Safely extract payload dictionary from Lambda event or API Gateway body."""
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise ValueError("Event must be a dictionary.")
    
    body = event.get("body")
    if body is None:
        return event

    if isinstance(body, str):
        try:
            parsed = json.loads(body)
            if not isinstance(parsed, dict):
                raise ValueError("Body must be a JSON object.")
            return parsed
        except json.JSONDecodeError:
            raise ValueError("Invalid JSON in request body.")
    if isinstance(body, dict):
        return body

    raise ValueError("Invalid request body type.")


def parse_and_validate_date_pair(params, start_key, end_key):
    """
    Validate and parse start_date and end_date pair.
    Returns (start_date, end_date) as date objects, or (None, None) if neither is provided.
    Raises ValueError if only one is provided, format is invalid, or start > end.
    """
    start_str = params.get(start_key)
    end_str = params.get(end_key)

    if start_str is None and end_str is None:
        return None, None

    if start_str is None or end_str is None:
        raise ValueError(f"Both {start_key} and {end_key} must be provided together.")

    if not isinstance(start_str, str) or not isinstance(end_str, str):
        raise ValueError(f"Invalid date format for {start_key}/{end_key}. Use YYYY-MM-DD.")

    start_str = start_str.strip()
    end_str = end_str.strip()

    try:
        start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format for {start_key}: '{start_str}'. Use YYYY-MM-DD.")

    try:
        end_date = datetime.strptime(end_str, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format for {end_key}: '{end_str}'. Use YYYY-MM-DD.")

    if start_date > end_date:
        raise ValueError(f"{start_key} cannot be after {end_key}.")

    return start_date, end_date


def _find_csv(search_dirs, candidate_names):
    """Locate the first matching CSV filename in search directories."""
    for d in search_dirs:
        if not d or not os.path.isdir(d):
            continue
        for name in candidate_names:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def prepare_dataframe(df):
    """Normalize organization types, boolean flags, and created_at timestamps."""
    frame = df.copy()

    # Normalize created_at
    if "created_at" in frame.columns:
        frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce")
    else:
        frame["created_at"] = pd.NaT

    # Normalize is_collaborator (True/False boolean)
    if "is_collaborator" in frame.columns:
        frame["is_collaborator"] = (
            frame["is_collaborator"]
            .astype(str)
            .str.strip()
            .str.lower()
            .isin(["true", "1", "t", "yes"])
        )
    else:
        frame["is_collaborator"] = False

    # Normalize is_contributor (gracefully handles missing column -> False)
    if "is_contributor" in frame.columns:
        frame["is_contributor"] = (
            frame["is_contributor"]
            .astype(str)
            .str.strip()
            .str.lower()
            .isin(["true", "1", "t", "yes"])
        )
    else:
        frame["is_contributor"] = False

    # Default country columns if absent
    if "country_code" not in frame.columns:
        frame["country_code"] = "USA"
    else:
        frame["country_code"] = frame["country_code"].fillna("USA")

    if "country_name" not in frame.columns:
        frame["country_name"] = "UNITED_STATES_OF_AMERICA"
    else:
        frame["country_name"] = frame["country_name"].fillna("UNITED_STATES_OF_AMERICA")

    return frame


def load_mock_data(mock_data_dir=None):
    """
    Load organizations, states, and countries CSVs, joining:
    organizations.state_id -> states.country_id -> countries.country_code.
    """
    search_dirs = []
    if mock_data_dir:
        search_dirs.append(mock_data_dir)
    env_dir = os.environ.get("MOCK_DATA_DIR")
    if env_dir:
        search_dirs.append(env_dir)

    search_dirs.extend([
        DEFAULT_DATA_DIR,
        SQL_DATA_DIR,
        os.getcwd(),
        os.path.join(os.getcwd(), "data-analytics", "sql"),
        os.path.join(os.getcwd(), "data-analytics", "mock-data-generation"),
    ])

    orgs_path = _find_csv(search_dirs, ["organizations.csv", "organization.csv"])
    states_path = _find_csv(search_dirs, ["states.csv", "state.csv"])
    countries_path = _find_csv(search_dirs, ["countries.csv", "country.csv"])

    if not orgs_path:
        raise FileNotFoundError("organizations.csv not found in search directories.")

    orgs_df = pd.read_csv(orgs_path, dtype={"org_id": str, "state_id": str})

    if states_path and countries_path:
        states_df = pd.read_csv(states_path, dtype={"state_id": str, "country_id": str})
        countries_df = pd.read_csv(countries_path, dtype={"country_id": str})

        # Known mock-data defect fix: state.csv sets country_id=1 for US states,
        # but in country.csv country_id=1 is Afghanistan and country_id=233 is USA.
        if "233" in countries_df["country_id"].astype(str).values and "state_code" in states_df.columns:
            us_mask = (states_df["country_id"].astype(str) == "1") & (states_df["state_code"].astype(str).str.startswith("US-"))
            states_df.loc[us_mask, "country_id"] = "233"

        merged = orgs_df.merge(states_df[["state_id", "country_id"]], on="state_id", how="left")

        country_cols = ["country_id"]
        if "country_code" in countries_df.columns:
            country_cols.append("country_code")
        elif "code" in countries_df.columns:
            countries_df["country_code"] = countries_df["code"]
            country_cols.append("country_code")

        if "country_name" in countries_df.columns:
            country_cols.append("country_name")
        elif "name" in countries_df.columns:
            countries_df["country_name"] = countries_df["name"]
            country_cols.append("country_name")

        merged = merged.merge(countries_df[country_cols], on="country_id", how="left")
    else:
        merged = orgs_df.copy()

    return prepare_dataframe(merged)


def load_database_data():
    """PostgreSQL database path for production execution when USE_MOCK_DATA is false."""
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required when USE_MOCK_DATA is false.")

    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    dbname = os.environ.get("DB_NAME", "saayam")
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASSWORD", "")
    schema = os.environ.get("ORG_ANALYTICS_SCHEMA", "virginia_dev_saayam_rdbms")

    conn = psycopg2.connect(
        host=host,
        port=port,
        dbname=dbname,
        user=user,
        password=password
    )
    try:
        query = f"""
            SELECT 
                o.org_id,
                o.org_size,
                o.org_type,
                o.created_at,
                o.is_collaborator,
                COALESCE(o.is_contributor, FALSE) AS is_contributor,
                COALESCE(c.country_code, 'USA') AS country_code,
                COALESCE(c.country_name, 'UNITED_STATES_OF_AMERICA') AS country_name
            FROM {schema}.organizations o
            LEFT JOIN {schema}.state s ON o.state_id = s.state_id
            LEFT JOIN {schema}.country c ON s.country_id = c.country_id
        """
        df = pd.read_sql(query, conn)
        return prepare_dataframe(df)
    finally:
        conn.close()


def apply_filters(df, country="ALL", organization_type="ALL"):
    """Filter by country name / code and organization type."""
    filtered = df.copy()

    # Validate and filter organization_type
    if organization_type is not None:
        norm_type = str(organization_type).strip().lower().replace("-", "_").replace(" ", "_")
        if norm_type not in ["all", "non_profit", "for_profit"]:
            raise ValueError("organization_type must be non_profit, for_profit, or ALL")
        if norm_type != "all" and not filtered.empty and "org_type" in filtered.columns:
            org_type_series = (
                filtered["org_type"]
                .astype(str)
                .str.strip()
                .str.lower()
                .str.replace("-", "_", regex=False)
                .str.replace(" ", "_", regex=False)
            )
            filtered = filtered[org_type_series == norm_type]

    # Filter country
    if country is not None:
        norm_country = str(country).strip().lower().replace("-", "_").replace(" ", "_")
        if norm_country not in ["", "all"] and not filtered.empty:
            usa_aliases = ["usa", "us", "united_states", "united_states_of_america"]
            c_code = filtered["country_code"].astype(str).str.strip().str.lower()
            c_name = (
                filtered["country_name"]
                .astype(str)
                .str.strip()
                .str.lower()
                .str.replace("-", "_", regex=False)
                .str.replace(" ", "_", regex=False)
            )
            if norm_country in usa_aliases:
                filtered = filtered[c_code.isin(["usa", "us"]) | c_name.isin(usa_aliases)]
            else:
                filtered = filtered[(c_code == norm_country) | (c_name == norm_country)]

    return filtered


def filter_by_window(df, time_range, start_date=None, end_date=None, reference_date=None):
    """Filter records by window: 7D, 30D, 1Y, All, or Custom."""
    if df.empty:
        return df.copy()

    valid_df = df.dropna(subset=["created_at"]).copy()
    if valid_df.empty:
        return valid_df

    dates = valid_df["created_at"].dt.date
    today = reference_date or date.today()
    if isinstance(today, datetime):
        today = today.date()

    if time_range == "7D":
        start = today - timedelta(days=7)
        end = today
        return valid_df[(dates >= start) & (dates <= end)]
    elif time_range == "30D":
        start = today - timedelta(days=30)
        end = today
        return valid_df[(dates >= start) & (dates <= end)]
    elif time_range == "1Y":
        start = today - timedelta(days=365)
        end = today
        return valid_df[(dates >= start) & (dates <= end)]
    elif time_range == "All":
        return valid_df[dates <= today]
    elif time_range == "Custom":
        if start_date is None or end_date is None:
            return valid_df.iloc[0:0]
        return valid_df[(dates >= start_date) & (dates <= end_date)]
    else:
        raise ValueError(f"Unsupported time_range: {time_range}")


def calculate_organizations_by_size(window_df):
    """
    Compute organization counts by size category.
    Returns flat array of {"size": ..., "count": ...} using raw enum values present in the data.
    Returns empty array if no organizations in window.
    """
    if window_df.empty:
        return []

    valid = window_df.dropna(subset=["org_size"])
    if valid.empty:
        return []

    counts = valid.groupby("org_size", observed=True, sort=False).size()
    return [{"size": size, "count": int(count)} for size, count in counts.items()]


def calculate_collaborator_vs_contributor(window_df):
    """
    Compute collaborator and contributor counts independently against the total organizations in the window.
    Returns exactly 2 rows ([Collaborator, Contributor]), or empty array if no organizations in window.
    """
    if window_df.empty:
        return []

    total = len(window_df)
    collaborator_count = int(window_df["is_collaborator"].sum())

    if "is_contributor" in window_df.columns:
        contributor_count = int(window_df["is_contributor"].sum())
    else:
        contributor_count = 0

    collab_percentage = round((collaborator_count / total) * 100, 1)
    contrib_percentage = round((contributor_count / total) * 100, 1)

    return [
        {"type": "Collaborator", "count": collaborator_count, "percentage": collab_percentage},
        {"type": "Contributor", "count": contributor_count, "percentage": contrib_percentage}
    ]


def generate_analytics(df, size_start=None, size_end=None, contribution_start=None, contribution_end=None, reference_date=None):
    """Assemble final analytics dictionary based on which custom params were supplied."""
    has_size_custom = (size_start is not None and size_end is not None)
    has_contrib_custom = (contribution_start is not None and contribution_end is not None)

    # When either or both Custom pairs are supplied: response has exactly 1 top-level key, "Custom"
    if has_size_custom or has_contrib_custom:
        custom_data = {
            "organizations_by_size": [],
            "collaborator_vs_contributor": []
        }

        if has_size_custom:
            size_window_df = filter_by_window(
                df, "Custom", start_date=size_start, end_date=size_end, reference_date=reference_date
            )
            custom_data["organizations_by_size"] = calculate_organizations_by_size(size_window_df)

        if has_contrib_custom:
            contrib_window_df = filter_by_window(
                df, "Custom", start_date=contribution_start, end_date=contribution_end, reference_date=reference_date
            )
            custom_data["collaborator_vs_contributor"] = calculate_collaborator_vs_contributor(contrib_window_df)

        return {"Custom": custom_data}

    # When neither Custom pair is supplied: return 7D, 30D, 1Y, All, plus empty Custom
    response = {}
    for bucket in ["7D", "30D", "1Y", "All"]:
        window_df = filter_by_window(df, bucket, reference_date=reference_date)
        response[bucket] = {
            "organizations_by_size": calculate_organizations_by_size(window_df),
            "collaborator_vs_contributor": calculate_collaborator_vs_contributor(window_df)
        }

    response["Custom"] = {
        "organizations_by_size": [],
        "collaborator_vs_contributor": []
    }

    return response


def lambda_handler(event, context=None, reference_date=None, df_override=None):
    """Main AWS Lambda handler entrypoint."""
    try:
        body = parse_event_body(event)

        country = body.get("country", "ALL")
        organization_type = body.get("organization_type", "ALL")

        # Validate date ranges
        size_start, size_end = parse_and_validate_date_pair(body, "size_start_date", "size_end_date")
        contrib_start, contrib_end = parse_and_validate_date_pair(body, "contribution_start_date", "contribution_end_date")

        # Determine reference date
        if reference_date is None:
            env_ref = os.environ.get("REFERENCE_DATE")
            if env_ref:
                reference_date = datetime.strptime(env_ref.strip(), "%Y-%m-%d").date()
            else:
                reference_date = date.today()

        # Load data
        if df_override is not None:
            df = prepare_dataframe(df_override)
        elif os.environ.get("USE_MOCK_DATA", "true").strip().lower() == "false":
            df = load_database_data()
        else:
            df = load_mock_data()

        # Apply filters
        filtered_df = apply_filters(df, country=country, organization_type=organization_type)

        # Generate response payload
        payload = generate_analytics(
            filtered_df,
            size_start=size_start,
            size_end=size_end,
            contribution_start=contrib_start,
            contribution_end=contrib_end,
            reference_date=reference_date
        )

        return {
            "statusCode": 200,
            "headers": CORS_HEADERS,
            "body": json.dumps(payload)
        }

    except ValueError as exc:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(exc)})
        }
    except Exception as exc:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": f"Internal server error: {str(exc)}"})
        }


if __name__ == "__main__":
    # Reference date inside the sample dataset range (2023-09 to 2026-01)
    # allows realistic smoke verification locally.
    sample_ref_date = date(2026, 1, 15)

    scenarios = [
        ("no_body", {}),
        ("country_filter", {"country": "USA"}),
        ("org_type_filter", {"organization_type": "non_profit"}),
        ("size_custom_only", {
            "size_start_date": "2025-01-01",
            "size_end_date": "2026-01-15"
        }),
        ("contribution_custom_only", {
            "contribution_start_date": "2025-01-01",
            "contribution_end_date": "2026-01-15"
        }),
        ("both_custom_pairs", {
            "size_start_date": "2025-01-01",
            "size_end_date": "2026-01-15",
            "contribution_start_date": "2025-06-01",
            "contribution_end_date": "2026-01-15"
        }),
    ]

    print("=================================================================")
    print("SIZE & CONTRIBUTION ANALYTICS API - LOCAL TEST EXECUTION")
    print("=================================================================\n")

    for name, req in scenarios:
        response = lambda_handler(req, reference_date=sample_ref_date)
        print(f"--- Scenario: {name} ---")
        print(f"Request: {json.dumps(req)}")
        print(f"Status: {response['statusCode']}")
        parsed_body = json.loads(response["body"])
        print(f"Top-level keys: {list(parsed_body.keys())}")
        print(json.dumps(parsed_body, indent=2))
        print("\n" + "-" * 65 + "\n")
