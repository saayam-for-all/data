"""Size and contribution analytics for organizations (issue #376)."""

import json
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd

try:
    import psycopg2
except ImportError:  # Mock CSV mode does not need a database driver.
    psycopg2 = None


BUCKETS = ("7D", "30D", "1Y", "All")
CHARTS = ("organizations_by_size", "collaborator_vs_contributor")
ORG_TYPES = ("non_profit", "for_profit")


class AnalyticsDataError(Exception):
    """Report malformed source data without treating it as a bad request."""


def _require_columns(frame, columns, filename):
    """Report missing CSV columns before attempting a merge or calculation."""
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"{filename} is missing required columns: {', '.join(missing)}")


def load_mock_organizations():
    """Load and join local organization, state, and country CSVs."""
    data_dir = os.getenv("MOCK_DATA_DIR")
    if not data_dir:
        raise ValueError("MOCK_DATA_DIR must point to the directory containing the CSVs")

    organizations = pd.read_csv(
        os.path.join(data_dir, "organizations.csv"), dtype={"state_id": "string"}
    )
    states = pd.read_csv(
        os.path.join(data_dir, "states.csv"),
        dtype={"state_id": "string", "country_id": "string"},
    )
    countries = pd.read_csv(os.path.join(data_dir, "countries.csv"), dtype={"country_id": "string"})
    _require_columns(
        organizations,
        ("org_id", "org_size", "org_type", "state_id", "created_at", "is_collaborator"),
        "organizations.csv",
    )
    _require_columns(states, ("state_id", "country_id"), "states.csv")
    _require_columns(countries, ("country_id",), "countries.csv")
    country_fields = [
        column for column in ("country_code", "country_name") if column in countries
    ]
    if not country_fields:
        raise ValueError("countries.csv must contain country_code or country_name")

    joined = organizations.merge(
        states[["state_id", "country_id"]], on="state_id", how="inner", validate="many_to_one"
    )
    if len(joined) != len(organizations):
        raise AnalyticsDataError("organizations.csv has state_id values missing from states.csv")
    joined = joined.merge(
        countries[["country_id", *country_fields]],
        on="country_id", how="inner", validate="many_to_one",
    )
    if len(joined) != len(organizations):
        raise AnalyticsDataError("states.csv has country_id values missing from countries.csv")
    for column in ("country_code", "country_name"):
        if column not in joined:
            joined[column] = pd.NA
    return _prepare_organizations(joined, source="organizations.csv")


def load_database_organizations():
    """Read joined Postgres data across the documented naming variants."""
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required when USE_MOCK_DATA is false")
    schema = os.getenv("ORG_ANALYTICS_SCHEMA", "virginia_dev_saayam_rdbms")
    if not schema.isidentifier():
        raise ValueError("ORG_ANALYTICS_SCHEMA must be a valid SQL identifier")
    connection = psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
        database=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name IN "
                "('organizations', 'states', 'state', 'countries', 'country')",
                (schema,),
            )
            available = {}
            for table, column in cursor.fetchall():
                available.setdefault(table, set()).add(column)

            organizations = available.get("organizations", set())
            state_choice = next(
                (
                    (table, key)
                    for table in ("states", "state")
                    for key in ("state_id", "state_code")
                    if key in organizations
                    and key in available.get(table, set())
                    and "country_id" in available.get(table, set())
                ),
                None,
            )
            country_table = next(
                (
                    table for table in ("countries", "country")
                    if "country_id" in available.get(table, set())
                    and {"country_code", "country_name"} & available.get(table, set())
                ),
                None,
            )
            if not state_choice or not country_table:
                raise RuntimeError("Database needs joinable state and country lookup tables")
            state_table, state_key = state_choice
            size_column = next(
                (name for name in ("org_size", "size") if name in organizations), None
            )
            required = {"org_id", "org_type", "created_at", "is_collaborator"}
            if not required.issubset(organizations) or not size_column:
                raise RuntimeError("Database organizations table lacks required analytics columns")
            contributor = "o.is_contributor" if "is_contributor" in organizations else "FALSE"
            country_columns = available[country_table]
            country_code = "c.country_code" if "country_code" in country_columns else "NULL"
            country_name = "c.country_name" if "country_name" in country_columns else "NULL"
            cursor.execute(
                f"SELECT o.org_id, o.{size_column} AS org_size, o.org_type, o.created_at, "
                f"o.is_collaborator, {contributor} AS is_contributor, "
                f"{country_code} AS country_code, {country_name} AS country_name "
                f"FROM {schema}.organizations o "
                f"JOIN {schema}.{state_table} s ON o.{state_key} = s.{state_key} "
                f"JOIN {schema}.{country_table} c ON s.country_id = c.country_id"
            )
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
    finally:
        connection.close()
    return _prepare_organizations(pd.DataFrame(rows, columns=columns), source="database organizations")


def _prepare_organizations(frame, source="organizations data"):
    """Validate source values and normalize timestamps and Boolean flags."""
    frame = frame.copy()
    sizes = frame["org_size"].astype("string").str.strip()
    if sizes.isna().any() or sizes.eq("").fillna(False).any():
        raise AnalyticsDataError(f"{source} has missing org_size values")
    if "is_contributor" not in frame:
        frame["is_contributor"] = False
    timestamps = pd.to_datetime(
        frame["created_at"], errors="coerce", format="mixed", utc=True
    )
    if timestamps.isna().any():
        raise AnalyticsDataError(f"{source} has missing or invalid created_at values")
    frame["created_at"] = timestamps.dt.tz_convert(None)
    for column in ("is_collaborator", "is_contributor"):
        values = frame[column].astype("string").str.strip().str.lower()
        valid = ("true", "t", "1", "yes", "false", "f", "0", "no")
        if (values.isna() | ~values.isin(valid)).any():
            raise AnalyticsDataError(f"{source} has missing or invalid {column} values")
        frame[column] = values.isin(("true", "t", "1", "yes"))
    return frame


def filter_organizations(frame, country="ALL", org_type="ALL"):
    """Apply country name/code and organization type filters to both charts."""
    for name, value in (("country", country), ("organization_type", org_type)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    selected_type = org_type.strip().casefold()
    if selected_type not in ("all", *ORG_TYPES):
        raise ValueError("organization_type must be non_profit, for_profit, or ALL")
    result = frame
    if country.strip().upper() != "ALL":
        selected = country.strip().casefold()
        result = result[
            result["country_code"].astype("string").str.casefold().eq(selected).fillna(False)
            | result["country_name"].astype("string").str.casefold().eq(selected).fillna(False)
        ]
    if selected_type != "all":
        result = result[result["org_type"].astype("string").str.casefold().eq(
            selected_type
        ).fillna(False)]
    return result


def _parse_date_pair(body, prefix):
    """Validate a complete ISO date pair before any analytics are calculated."""
    start_key, end_key = f"{prefix}_start_date", f"{prefix}_end_date"
    if start_key not in body and end_key not in body:
        return None
    if start_key not in body or end_key not in body:
        raise ValueError(f"{start_key} and {end_key} must both be provided")
    start_value, end_value = body[start_key], body[end_key]
    parsed = []
    for key, value in ((start_key, start_value), (end_key, end_value)):
        try:
            if not isinstance(value, str):
                raise ValueError
            parsed_date = date.fromisoformat(value)
            if value != parsed_date.isoformat():
                raise ValueError
        except ValueError:
            raise ValueError(f"{key} must be a valid date in YYYY-MM-DD format") from None
        parsed.append(parsed_date)
    if parsed[0] > parsed[1]:
        raise ValueError(f"{start_key} must be on or before {end_key}")
    return tuple(parsed)


def filter_by_window(frame, window, today=None, custom_range=None):
    """Select organizations created within an inclusive date window."""
    if window == "All":
        return frame
    today = today or datetime.now(timezone.utc).date()
    if window == "Custom":
        if custom_range is None:
            raise ValueError("Custom window requires a validated date range")
        start, end = custom_range
    elif window == "7D":
        start, end = today - timedelta(days=7), today
    elif window == "30D":
        start, end = today - timedelta(days=30), today
    elif window == "1Y":
        try:
            start = today.replace(year=today.year - 1)
        except ValueError:  # February 29 in a leap year.
            start = today.replace(year=today.year - 1, day=28)
        end = today
    else:
        raise ValueError(f"Unsupported window: {window}")
    timestamps = frame["created_at"]
    return frame[
        timestamps.ge(pd.Timestamp(start))
        & timestamps.lt(pd.Timestamp(end + timedelta(days=1)))
    ]


def _size_chart(frame):
    """Return one count for each size actually present in the window."""
    return [
        {"size": size, "count": int(count)}
        for size, count in frame.groupby(
            "org_size", observed=True, sort=False
        ).size().items()
    ]


def _contribution_chart(frame):
    """Count collaborator and contributor flags independently."""
    total = len(frame)
    if not total:
        return []
    collaborator_count = int(frame["is_collaborator"].eq(True).sum())
    contributor_count = (
        int(frame["is_contributor"].eq(True).sum()) if "is_contributor" in frame else 0
    )
    return [
        {"type": label, "count": count, "percentage": round(100 * count / total, 1)}
        for label, count in (
            ("Collaborator", collaborator_count),
            ("Contributor", contributor_count),
        )
    ]


def _event_body(event):
    """Accept a direct event or an API Gateway JSON body."""
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise ValueError("event must be a JSON object")
    body = event.get("body", event)
    if body is None:
        return {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("body must contain valid JSON") from None
    if not isinstance(body, dict):
        raise ValueError("body must be a JSON object")
    return body


def _response(status, body):
    """Wrap the analytics data for API Gateway."""
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    """Return fixed buckets or independently selected Custom charts."""
    try:
        body = _event_body(event)
        size_range = _parse_date_pair(body, "size")
        contribution_range = _parse_date_pair(body, "contribution")
        country = body.get("country", "ALL")
        org_type = body.get("organization_type", "ALL")
        if os.getenv("USE_MOCK_DATA", "true").lower() == "true":
            organizations = load_mock_organizations()
        else:
            organizations = load_database_organizations()
        organizations = filter_organizations(organizations, country, org_type)

        if size_range is not None or contribution_range is not None:
            custom = {chart: [] for chart in CHARTS}
            if size_range is not None:
                custom["organizations_by_size"] = _size_chart(
                    filter_by_window(organizations, "Custom", custom_range=size_range)
                )
            if contribution_range is not None:
                custom["collaborator_vs_contributor"] = _contribution_chart(
                    filter_by_window(organizations, "Custom", custom_range=contribution_range)
                )
            return _response(200, {"Custom": custom})

        result = {}
        for bucket in BUCKETS:
            window = filter_by_window(organizations, bucket)
            result[bucket] = {
                "organizations_by_size": _size_chart(window),
                "collaborator_vs_contributor": _contribution_chart(window),
            }
        result["Custom"] = {chart: [] for chart in CHARTS}
        return _response(200, result)
    except AnalyticsDataError as exc:
        return _response(500, {"error": str(exc)})
    except ValueError as exc:
        return _response(400, {"error": str(exc)})
    except (OSError, pd.errors.ParserError) as exc:
        return _response(500, {"error": f"Unable to load analytics data: {exc}"})
    except Exception as exc:
        return _response(500, {"error": f"Unable to calculate analytics: {exc}"})


if __name__ == "__main__":
    examples = (
        {}, {"country": "USA"}, {"organization_type": "non_profit"},
        {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"},
        {"contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"},
        {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
         "contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"},
    )
    for example in examples:
        print(json.dumps(lambda_handler(example, None)))
