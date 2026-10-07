"""Organization Size & Contribution dashboard API (issue #376).

Run locally with USE_MOCK_DATA=true and MOCK_DATA_DIR pointing to a consistent
set of organizations.csv, states.csv and countries.csv (singular lookup names
are also accepted). No CSV data is bundled with this function.

Without custom dates, return 7D/30D/1Y/All and an empty Custom. With either date
pair, return Custom only, computing each requested chart independently.
7D/30D include today; 1Y starts on the first day of the month 11 months ago.
All has no date restriction. Custom endpoints include the entire final day.
Timestamps are interpreted in UTC. Size labels are returned as stored.

PostgreSQL mode uses DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD and optionally
DB_SCHEMA (default virginia_dev_saayam_rdbms). The tables are organizations,
state and country. psycopg2 is optional for local CSV use. Both backends share
validation, filtering and chart calculations; no AWS services are invoked.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd

try:
    import psycopg2
except ImportError:
    psycopg2 = None


ORG_COLUMNS = (
    "org_id",
    "org_size",
    "is_collaborator",
    "org_type",
    "state_id",
    "created_at",
)
CHARTS = ("organizations_by_size", "collaborator_vs_contributor")
HEADERS = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}


class RequestError(ValueError):
    """Invalid request input, reported as HTTP 400."""


class DataError(ValueError):
    """Invalid source data or configuration, reported as HTTP 500."""


def parse_body(event):
    """Accept direct Lambda events and API Gateway object/JSON bodies."""
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise RequestError("Request must be a JSON object")
    body = event.get("body", event)
    if body is None or body == "":
        return {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RequestError("Request body must contain valid JSON") from exc
    if not isinstance(body, dict):
        raise RequestError("Request body must be a JSON object")
    return body


def parse_range(body, prefix):
    """Validate one independent pair of inclusive YYYY-MM-DD dates."""
    keys = (f"{prefix}_start_date", f"{prefix}_end_date")
    if not any(key in body for key in keys):
        return None
    parsed = []
    for key in keys:
        value = body.get(key)
        try:
            if not isinstance(value, str):
                raise ValueError
            day = date.fromisoformat(value)
            if day.isoformat() != value:
                raise ValueError
        except ValueError as exc:
            raise RequestError(
                f"{keys[0]} and {keys[1]} must both be valid YYYY-MM-DD dates"
            ) from exc
        parsed.append(day)
    if parsed[0] > parsed[1]:
        raise RequestError(f"{keys[0]} must not be after {keys[1]}")
    return tuple(parsed)


def normalize_type(value):
    """Compare canonical and legacy type spellings without changing output."""
    return (
        str(value).strip().casefold().replace("-", "").replace("_", "").replace(" ", "")
    )


def parse_filters(body):
    """Reject malformed filters before accessing any data source."""
    values = []
    for key in ("country", "organization_type"):
        value = body.get(key, "ALL")
        if not isinstance(value, str) or not value.strip():
            raise RequestError(f"{key} must be a non-empty string")
        values.append(value.strip())
    country, org_type = values
    org_type = normalize_type(org_type)
    if org_type not in ("all", "nonprofit", "forprofit"):
        raise RequestError("organization_type must be non_profit, for_profit or ALL")
    return country.casefold(), org_type


def require_columns(frame, columns, label):
    """Report missing source columns as a data error, not a request error."""
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise DataError(f"{label} is missing columns: {', '.join(missing)}")


def read_csv(directory, names, empty_columns=None):
    """Read one local table, accepting singular/plural lookup filenames."""
    for name in names:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            try:
                return pd.read_csv(path, dtype="string")
            except pd.errors.EmptyDataError:
                if empty_columns is not None:
                    return pd.DataFrame(columns=empty_columns)
                raise DataError(f"{name} has no header") from None
    raise DataError(f"Missing CSV file: {' or '.join(names)}")


def load_mock_tables():
    """Load local-only fixtures from the configured directory."""
    directory = os.getenv("MOCK_DATA_DIR")
    if not directory:
        raise DataError("Set MOCK_DATA_DIR when USE_MOCK_DATA=true")
    return (
        read_csv(directory, ("organizations.csv",), ORG_COLUMNS),
        read_csv(directory, ("states.csv", "state.csv")),
        read_csv(directory, ("countries.csv", "country.csv")),
    )


def load_postgres_tables():
    """Read the analytics columns, handling older contributor-less tables."""
    if psycopg2 is None:
        raise DataError("psycopg2 is required when USE_MOCK_DATA=false")
    schema = os.getenv("DB_SCHEMA", "virginia_dev_saayam_rdbms")
    # Only a simple identifier may be interpolated; values use bind parameters.
    if not schema.isascii() or not schema.isidentifier():
        raise DataError("DB_SCHEMA must be a simple SQL identifier")
    required = ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD")
    if any(not os.getenv(key) for key in required):
        raise DataError("Set DB_HOST, DB_NAME, DB_USER and DB_PASSWORD")
    connection = psycopg2.connect(
        host=os.environ["DB_HOST"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        port=os.getenv("DB_PORT", "5432"),
        connect_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s",
                (schema, "organizations"),
            )
            columns = {row[0] for row in cursor.fetchall()}
            contributor = "is_contributor" if "is_contributor" in columns else "FALSE"
            queries = (
                f"SELECT org_id, org_size, is_collaborator, org_type, state_id, "
                f'created_at, {contributor} AS is_contributor FROM "{schema}".organizations',
                f'SELECT state_id, country_id FROM "{schema}".state',
                f'SELECT country_id, country_code, country_name FROM "{schema}".country',
            )
            frames = []
            for query in queries:
                cursor.execute(query)
                names = [column[0] for column in cursor.description]
                frames.append(pd.DataFrame(cursor.fetchall(), columns=names))
            return tuple(frames)
    finally:
        connection.close()


def boolean_flags(series):
    """Parse CSV/database flags explicitly; a string 'false' is not truthy."""
    values = series.astype("string").str.strip().str.casefold().fillna("false")
    true_values = ("true", "t", "1", "1.0", "yes", "y")
    false_values = ("false", "f", "0", "0.0", "no", "n", "")
    if not values.isin(true_values + false_values).all():
        raise DataError(f"Invalid boolean in {series.name}")
    return values.isin(true_values)


def prepare_data(organizations, states, countries):
    """Validate and join tables without inventing geography or duplicating orgs."""
    require_columns(organizations, ORG_COLUMNS, "organizations")
    require_columns(states, ("state_id", "country_id"), "states")
    require_columns(countries, ("country_id",), "countries")
    country_fields = [
        key for key in ("country_code", "country_name") if key in countries
    ]
    if not country_fields:
        raise DataError("countries needs country_code or country_name")
    orgs = organizations[
        list(ORG_COLUMNS)
        + (["is_contributor"] if "is_contributor" in organizations else [])
    ].copy()
    states = states[["state_id", "country_id"]].copy()
    countries = countries[["country_id", *country_fields]].copy()
    for frame, keys in (
        (orgs, ("org_id", "state_id")),
        (states, ("state_id", "country_id")),
        (countries, ("country_id",)),
    ):
        for key in keys:
            frame[key] = frame[key].astype("string").str.strip()
    for frame, key in (
        (orgs, "org_id"),
        (states, "state_id"),
        (countries, "country_id"),
    ):
        if (
            frame[key].isna().any()
            or frame[key].eq("").any()
            or frame[key].duplicated().any()
        ):
            raise DataError(f"{key} must contain unique, non-empty values")
    sizes = orgs["org_size"].astype("string")
    if sizes.isna().any() or sizes.str.strip().eq("").any():
        raise DataError("organizations has missing org_size values")
    orgs["org_size"] = sizes  # Preserve raw categories, including their casing.
    timestamps = pd.to_datetime(
        orgs["created_at"], format="mixed", errors="coerce", utc=True
    )
    if timestamps.isna().any():
        raise DataError("organizations has missing or invalid created_at values")
    orgs["created_day"] = timestamps.dt.date
    if "is_contributor" not in orgs:
        orgs["is_contributor"] = False
    for key in ("is_collaborator", "is_contributor"):
        orgs[key] = boolean_flags(orgs[key])
    orgs = orgs.merge(states, on="state_id", how="left", validate="many_to_one")
    return orgs.merge(countries, on="country_id", how="left", validate="many_to_one")


def apply_filters(frame, country, org_type):
    """Apply shared country/type filters before selecting chart windows."""
    if country != "all":
        matches = pd.Series(False, index=frame.index)
        for key in ("country_code", "country_name"):
            if key in frame:
                matches |= (
                    frame[key]
                    .astype("string")
                    .str.strip()
                    .str.casefold()
                    .eq(country)
                    .fillna(False)
                )
        frame = frame[matches]
    if org_type != "all":
        frame = frame[frame["org_type"].map(normalize_type).eq(org_type)]
    return frame


def fixed_windows(today):
    """Return exact calendar windows following the reviewer clarification."""
    month_index = today.year * 12 + today.month - 1 - 11
    year_start = date(month_index // 12, month_index % 12 + 1, 1)
    return {
        "7D": (today - timedelta(days=6), today),
        "30D": (today - timedelta(days=29), today),
        "1Y": (year_start, today),
        "All": (None, None),
    }


def window(frame, bounds):
    """Select whole UTC calendar dates, inclusive of both endpoints."""
    start, end = bounds
    if start is None:
        return frame
    return frame[frame["created_day"].between(start, end)]


def size_chart(frame):
    """Emit only observed raw sizes, in deterministic label order."""
    counts = frame.groupby("org_size", sort=True, observed=True).size()
    return [{"size": str(size), "count": int(count)} for size, count in counts.items()]


def contribution_chart(frame):
    """Count independent flags against the same filtered organization total."""
    total = len(frame)
    if not total:
        return []
    result = []
    for label, key in (
        ("Collaborator", "is_collaborator"),
        ("Contributor", "is_contributor"),
    ):
        count = int(frame[key].sum())
        result.append(
            {"type": label, "count": count, "percentage": round(count * 100 / total, 1)}
        )
    return result


def build_analytics(frame, size_range, contribution_range, today):
    """Build fixed snapshots or independently requested Custom charts."""
    if size_range is not None or contribution_range is not None:
        return {
            "Custom": {
                CHARTS[0]: size_chart(window(frame, size_range)) if size_range else [],
                CHARTS[1]: (
                    contribution_chart(window(frame, contribution_range))
                    if contribution_range
                    else []
                ),
            }
        }
    result = {}
    for bucket, bounds in fixed_windows(today).items():
        selected = window(frame, bounds)
        result[bucket] = {
            CHARTS[0]: size_chart(selected),
            CHARTS[1]: contribution_chart(selected),
        }
    result["Custom"] = {key: [] for key in CHARTS}
    return result


def response(status, body):
    """Serialize a standard API Gateway response."""
    return {
        "statusCode": status,
        "headers": HEADERS.copy(),
        "body": json.dumps(body, allow_nan=False),
    }


def lambda_handler(event, context):
    """Validate the request, load a single data snapshot and calculate charts."""
    try:
        body = parse_body(event)
        country, org_type = parse_filters(body)
        size_range = parse_range(body, "size")
        contribution_range = parse_range(body, "contribution")
    except RequestError as exc:
        return response(400, {"error": str(exc)})
    try:
        mode = os.getenv("USE_MOCK_DATA", "false").strip().lower()
        if mode not in ("true", "false"):
            raise DataError("USE_MOCK_DATA must be true or false")
        tables = load_mock_tables() if mode == "true" else load_postgres_tables()
        frame = apply_filters(prepare_data(*tables), country, org_type)
        return response(
            200,
            build_analytics(
                frame, size_range, contribution_range, datetime.now(timezone.utc).date()
            ),
        )
    except Exception as exc:
        print(f"Size & Contribution analytics failed: {type(exc).__name__}: {exc}")
        return response(
            500, {"error": "Unable to load or calculate organization analytics"}
        )


if __name__ == "__main__":
    os.environ.setdefault("USE_MOCK_DATA", "true")
    # Historical example windows also exercise the repository mock dataset.
    size_dates = {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"}
    contribution_dates = {
        "contribution_start_date": "2025-01-01",
        "contribution_end_date": "2025-12-31",
    }
    for label, event in (
        ("No body", {}),
        ("Country", {"country": "USA"}),
        ("Organization type", {"organization_type": "non_profit"}),
        ("Size Custom", size_dates),
        ("Contribution Custom", contribution_dates),
        ("Both Custom ranges", {**size_dates, **contribution_dates}),
    ):
        result = lambda_handler(event, None)
        print(
            json.dumps(
                {
                    "scenario": label,
                    "request": event,
                    "statusCode": result["statusCode"],
                    "body": json.loads(result["body"]),
                }
            )
        )
