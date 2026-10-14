import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None


USE_MOCK_DATA = os.getenv("USE_MOCK_DATA", "true").lower() == "true"
MOCK_DATA_DIR = os.getenv("MOCK_DATA_DIR", ".")


# -------------------------------------------------------------------
# RESPONSE HELPERS
# -------------------------------------------------------------------


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _error(message, status_code=400):
    return _response(status_code, {"error": message})


# -------------------------------------------------------------------
# EVENT PARSING
# -------------------------------------------------------------------


def _parse_event(event):
    """
    Supports:
      lambda_handler({})
      lambda_handler({"country": "USA"})
      API Gateway style:
      lambda_handler({"body": "{\"country\": \"USA\"}"})
    """

    if not event:
        return {}

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        body = body.strip()

        if not body:
            return {}

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("Request body must contain valid JSON.")

        if not isinstance(parsed, dict):
            raise ValueError("Request body must be a JSON object.")

        return parsed

    raise ValueError("Unsupported request body format.")


# -------------------------------------------------------------------
# DATE VALIDATION
# -------------------------------------------------------------------


def _parse_date(value, field_name):
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.")


def _validate_date_pair(params, start_field, end_field):
    """
    Returns:
        None
        OR
        (start_datetime, end_datetime_exclusive)

    Using an exclusive upper bound avoids accidentally excluding
    records created later during the end date.
    """

    start_value = params.get(start_field)
    end_value = params.get(end_field)

    if start_value is None and end_value is None:
        return None

    if start_value is None or end_value is None:
        raise ValueError(f"{start_field} and {end_field} must be supplied together.")

    start = _parse_date(start_value, start_field)
    end = _parse_date(end_value, end_field)

    if start > end:
        raise ValueError(f"{start_field} cannot be after {end_field}.")

    # End date should include the entire calendar day.
    end_exclusive = end + timedelta(days=1)

    return start, end_exclusive


# -------------------------------------------------------------------
# BOOLEAN NORMALIZATION
# -------------------------------------------------------------------


def _normalize_boolean(value):
    if pd.isna(value):
        return False

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value == 1

    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "t"}

    return False


# -------------------------------------------------------------------
# MOCK DATA LOADING
# -------------------------------------------------------------------


def _load_mock_data():
    organizations_path = os.path.join(MOCK_DATA_DIR, "organizations.csv")
    states_path = os.path.join(MOCK_DATA_DIR, "states.csv")
    countries_path = os.path.join(MOCK_DATA_DIR, "countries.csv")

    organizations = pd.read_csv(organizations_path)
    states = pd.read_csv(states_path)
    countries = pd.read_csv(countries_path)

    required_org_columns = {
        "org_id",
        "org_size",
        "is_collaborator",
        "org_type",
        "state_id",
        "created_at",
    }

    missing_org_columns = required_org_columns - set(organizations.columns)

    if missing_org_columns:
        raise ValueError(
            "organizations.csv is missing required columns: "
            + ", ".join(sorted(missing_org_columns))
        )

    if "state_id" not in states.columns:
        raise ValueError("states.csv is missing required column: state_id")

    if "country_id" not in states.columns:
        raise ValueError("states.csv is missing required column: country_id")

    if "country_id" not in countries.columns:
        raise ValueError("countries.csv is missing required column: country_id")

    if (
        "country_code" not in countries.columns
        and "country_name" not in countries.columns
    ):
        raise ValueError("countries.csv must contain country_code or country_name.")

    # Requirement says missing is_contributor must degrade gracefully.
    if "is_contributor" not in organizations.columns:
        organizations["is_contributor"] = False

    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"], errors="coerce", utc=True
    )

    organizations["is_collaborator"] = organizations["is_collaborator"].apply(
        _normalize_boolean
    )

    organizations["is_contributor"] = organizations["is_contributor"].apply(
        _normalize_boolean
    )

    df = organizations.merge(
        states[["state_id", "country_id"]], on="state_id", how="left"
    )

    country_columns = ["country_id"]

    if "country_code" in countries.columns:
        country_columns.append("country_code")

    if "country_name" in countries.columns:
        country_columns.append("country_name")

    df = df.merge(countries[country_columns], on="country_id", how="left")

    return df


# -------------------------------------------------------------------
# DATABASE LOADING
# -------------------------------------------------------------------


def _load_database_data():
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is not installed. Install it or use USE_MOCK_DATA=true."
        )

    connection = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )

    query = """
        SELECT
            o.org_id,
            o.org_size,
            o.is_collaborator,
            o.is_contributor,
            o.org_type,
            o.state_id,
            o.created_at,
            s.country_id,
            c.country_code,
            c.country_name
        FROM organizations o
        LEFT JOIN states s
            ON o.state_id = s.state_id
        LEFT JOIN countries c
            ON s.country_id = c.country_id
    """

    try:
        df = pd.read_sql_query(query, connection)
    finally:
        connection.close()

    if "is_contributor" not in df.columns:
        df["is_contributor"] = False

    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)

    df["is_collaborator"] = df["is_collaborator"].apply(_normalize_boolean)

    df["is_contributor"] = df["is_contributor"].apply(_normalize_boolean)

    return df


def _load_data():
    if USE_MOCK_DATA:
        return _load_mock_data()

    return _load_database_data()


# -------------------------------------------------------------------
# GLOBAL FILTERS
# -------------------------------------------------------------------


def _apply_country_filter(df, country):
    if not country:
        return df

    country = str(country).strip()

    if not country or country.upper() == "ALL":
        return df

    conditions = []

    if "country_code" in df.columns:
        conditions.append(
            df["country_code"]
            .fillna("")
            .astype(str)
            .str.casefold()
            .eq(country.casefold())
        )

    if "country_name" in df.columns:
        conditions.append(
            df["country_name"]
            .fillna("")
            .astype(str)
            .str.casefold()
            .eq(country.casefold())
        )

    if not conditions:
        return df.iloc[0:0].copy()

    mask = conditions[0]

    for condition in conditions[1:]:
        mask = mask | condition

    return df[mask].copy()


def _apply_organization_type_filter(df, organization_type):
    if not organization_type:
        return df

    organization_type = str(organization_type).strip()

    if not organization_type or organization_type.upper() == "ALL":
        return df

    valid_values = {"non_profit", "for_profit"}

    normalized = organization_type.casefold()

    if normalized not in valid_values:
        raise ValueError(
            "organization_type must be 'non_profit', 'for_profit', or 'ALL'."
        )

    return df[
        df["org_type"].fillna("").astype(str).str.casefold().eq(normalized)
    ].copy()


def _apply_global_filters(df, params):
    df = _apply_country_filter(df, params.get("country", "ALL"))

    df = _apply_organization_type_filter(df, params.get("organization_type", "ALL"))

    return df


# -------------------------------------------------------------------
# DATE FILTERING
# -------------------------------------------------------------------


def _to_utc_timestamp(value):
    """
    Convert either a naive or timezone-aware datetime/Timestamp
    into a UTC pandas Timestamp.
    """
    timestamp = pd.Timestamp(value)

    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")

    return timestamp.tz_convert("UTC")


def _filter_date_range(df, start=None, end_exclusive=None):
    if df.empty:
        return df.copy()

    result = df

    if start is not None:
        start_utc = _to_utc_timestamp(start)

        result = result[result["created_at"] >= start_utc]

    if end_exclusive is not None:
        end_utc = _to_utc_timestamp(end_exclusive)

        result = result[result["created_at"] < end_utc]

    return result.copy()


# -------------------------------------------------------------------
# SIZE CHART
# -------------------------------------------------------------------


def _organizations_by_size(df):
    if df.empty:
        return []

    working = df[df["org_size"].notna()].copy()

    if working.empty:
        return []

    counts = working.groupby("org_size", dropna=True).size().reset_index(name="count")

    result = []

    for _, row in counts.iterrows():
        result.append({"size": str(row["org_size"]), "count": int(row["count"])})

    return result


# -------------------------------------------------------------------
# CONTRIBUTION CHART
# -------------------------------------------------------------------


def _collaborator_vs_contributor(df):
    total = len(df)

    if total == 0:
        return []

    collaborator_count = int(
        df["is_collaborator"].fillna(False).apply(_normalize_boolean).sum()
    )

    if "is_contributor" in df.columns:
        contributor_count = int(
            df["is_contributor"].fillna(False).apply(_normalize_boolean).sum()
        )
    else:
        contributor_count = 0

    collaborator_percentage = round(collaborator_count / total * 100, 1)

    contributor_percentage = round(contributor_count / total * 100, 1)

    return [
        {
            "type": "Collaborator",
            "count": collaborator_count,
            "percentage": collaborator_percentage,
        },
        {
            "type": "Contributor",
            "count": contributor_count,
            "percentage": contributor_percentage,
        },
    ]


# -------------------------------------------------------------------
# CHART SNAPSHOT
# -------------------------------------------------------------------


def _build_snapshot(df):
    return {
        "organizations_by_size": _organizations_by_size(df),
        "collaborator_vs_contributor": _collaborator_vs_contributor(df),
    }


# -------------------------------------------------------------------
# FIXED TIME WINDOWS
# -------------------------------------------------------------------


def _get_fixed_windows(now=None):
    """
    7D  = current timestamp minus 7 days
    30D = current timestamp minus 30 days

    1Y follows 12 calendar months:
    current month + previous 11 months.

    All = no lower bound.
    """

    if now is None:
        now = datetime.now(timezone.utc)

    now_ts = pd.Timestamp(now)

    if now_ts.tzinfo is None:
        now_ts = now_ts.tz_localize("UTC")
    else:
        now_ts = now_ts.tz_convert("UTC")

    seven_day_start = now_ts - pd.Timedelta(days=7)
    thirty_day_start = now_ts - pd.Timedelta(days=30)

    current_month_start = pd.Timestamp(
        year=now_ts.year, month=now_ts.month, day=1, tz="UTC"
    )

    one_year_start = current_month_start - pd.DateOffset(months=11)

    return {
        "7D": seven_day_start,
        "30D": thirty_day_start,
        "1Y": one_year_start,
        "All": None,
    }


def _build_fixed_response(df, now=None):
    windows = _get_fixed_windows(now)

    result = {}

    for bucket_name, start in windows.items():
        if bucket_name == "All":
            bucket_df = df.copy()
        else:
            bucket_df = _filter_date_range(df, start=start)

        result[bucket_name] = _build_snapshot(bucket_df)

    result["Custom"] = {"organizations_by_size": [], "collaborator_vs_contributor": []}

    return result


# -------------------------------------------------------------------
# CUSTOM RESPONSE
# -------------------------------------------------------------------


def _build_custom_response(df, size_range, contribution_range):
    result = {
        "Custom": {"organizations_by_size": [], "collaborator_vs_contributor": []}
    }

    if size_range is not None:
        size_start, size_end = size_range

        size_df = _filter_date_range(df, start=size_start, end_exclusive=size_end)

        result["Custom"]["organizations_by_size"] = _organizations_by_size(size_df)

    if contribution_range is not None:
        contribution_start, contribution_end = contribution_range

        contribution_df = _filter_date_range(
            df, start=contribution_start, end_exclusive=contribution_end
        )

        result["Custom"]["collaborator_vs_contributor"] = _collaborator_vs_contributor(
            contribution_df
        )

    return result


# -------------------------------------------------------------------
# LAMBDA HANDLER
# -------------------------------------------------------------------


def lambda_handler(event, context=None):
    try:
        params = _parse_event(event)

        size_range = _validate_date_pair(params, "size_start_date", "size_end_date")

        contribution_range = _validate_date_pair(
            params, "contribution_start_date", "contribution_end_date"
        )

        df = _load_data()

        df = _apply_global_filters(df, params)

        has_custom_range = size_range is not None or contribution_range is not None

        if has_custom_range:
            result = _build_custom_response(
                df, size_range=size_range, contribution_range=contribution_range
            )
        else:
            result = _build_fixed_response(df)

        return _response(200, result)

    except ValueError as exc:
        return _error(str(exc), status_code=400)

    except Exception as exc:
        print(f"Size & Contribution Analytics error: {exc}")

        return _error("Internal server error.", status_code=500)


# -------------------------------------------------------------------
# LOCAL MANUAL TESTING
# -------------------------------------------------------------------

if __name__ == "__main__":
    sample_events = [
        {"name": "No filters", "event": {}},
        {"name": "Country filter", "event": {"country": "USA"}},
        {
            "name": "Organization type filter",
            "event": {"organization_type": "non_profit"},
        },
        {
            "name": "Size custom range",
            "event": {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"},
        },
        {
            "name": "Contribution custom range",
            "event": {
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2025-12-31",
            },
        },
        {
            "name": "Both custom ranges",
            "event": {
                "size_start_date": "2026-01-01",
                "size_end_date": "2026-06-30",
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2025-12-31",
            },
        },
    ]

    for sample in sample_events:
        print("=" * 80)
        print(sample["name"])

        response = lambda_handler(sample["event"], None)

        print(json.dumps(response, indent=2))
