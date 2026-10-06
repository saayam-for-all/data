"""Standalone Size & Contribution analytics Lambda for issue #376."""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    psycopg2 = None
    sql = None


LOGGER = logging.getLogger(__name__)
ORG_COLUMNS = (
    "org_id", "org_size", "is_collaborator", "org_type", "state_id", "created_at"
)
STATE_COLUMNS = ("state_id", "country_id")
COUNTRY_COLUMNS = ("country_id",)
FILTERS = {
    "country", "organization_type", "size_start_date", "size_end_date",
    "contribution_start_date", "contribution_end_date",
}


class InputError(ValueError):
    """The caller supplied an invalid filter or request body."""


class DataError(ValueError):
    """The configured data source cannot produce reliable analytics."""


def utc_now() -> datetime:
    """Read the clock once per invocation for consistent bucket boundaries."""
    return datetime.now(timezone.utc)


def build_response(status_code: int, body: dict) -> dict:
    """Return an API Gateway proxy response with a JSON-encoded body."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, allow_nan=False),
    }


def parse_request(event: dict | None) -> dict:
    """Accept a direct Lambda payload or an API Gateway JSON body."""
    if event is None:
        event = {}
    if not isinstance(event, dict):
        raise InputError("The event must be an object.")
    if event.get("isBase64Encoded"):
        raise InputError("Send a plain JSON body, not base64-encoded content.")
    body = event.get("body", event)
    if body is None or body == "":
        body = {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError as exc:
            raise InputError("The body must contain valid JSON.") from exc
    if not isinstance(body, dict):
        raise InputError("The body must be a JSON object.")
    unknown = sorted(str(key) for key in set(body) - FILTERS)
    if unknown:
        raise InputError("Unsupported filter(s): " + ", ".join(unknown))
    return body


def parse_text_filter(filters: dict, name: str) -> str:
    """Validate scalar filters; omitted filters select all organizations."""
    value = filters.get(name, "ALL")
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{name} must be a non-empty string.")
    value = value.strip().casefold()
    if name == "organization_type" and value not in {
        "all", "non_profit", "for_profit"
    }:
        raise InputError("organization_type must be non_profit, for_profit or ALL.")
    return value


def parse_date_range(filters: dict, prefix: str) -> tuple | None:
    """Validate an independent pair and return inclusive calendar dates."""
    start_key, end_key = f"{prefix}_start_date", f"{prefix}_end_date"
    if start_key not in filters and end_key not in filters:
        return None
    if start_key not in filters or end_key not in filters:
        raise InputError(f"{start_key} and {end_key} must be supplied together.")
    dates = []
    for key in (start_key, end_key):
        value = filters[key]
        try:
            if not isinstance(value, str):
                raise ValueError
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
            if parsed.isoformat() != value:
                raise ValueError
        except ValueError as exc:
            raise InputError(f"{key} must be a valid YYYY-MM-DD date.") from exc
        dates.append(parsed)
    if dates[0] > dates[1]:
        raise InputError(f"{start_key} must be on or before {end_key}.")
    return tuple(dates)


def require_columns(frame: pd.DataFrame, required: tuple, label: str) -> None:
    """Reject incompatible schemas instead of returning partial analytics."""
    missing = set(required) - set(frame.columns)
    if missing:
        raise DataError(f"{label} is missing columns: {', '.join(sorted(missing))}.")


def read_mock_table(directory: str, name: str, required: tuple,
                    legacy_name: str | None = None) -> pd.DataFrame:
    """Load CSV identifiers as strings, including leading zeroes."""
    path = os.path.join(directory, f"{name}.csv")
    if not os.path.isfile(path) and legacy_name:
        path = os.path.join(directory, f"{legacy_name}.csv")
    try:
        # Keep literal identifiers such as the country code NA intact.
        frame = pd.read_csv(path, dtype="string", keep_default_na=False)
    except pd.errors.EmptyDataError as exc:
        if name != "organizations":
            raise DataError(f"{name}.csv must contain a header.") from exc
        frame = pd.DataFrame(columns=required)
    except FileNotFoundError as exc:
        raise DataError(f"Missing {name}.csv; check MOCK_DATA_DIR.") from exc
    except pd.errors.ParserError as exc:
        raise DataError(f"{name}.csv is not a valid CSV table.") from exc
    require_columns(frame, required, name)
    return frame


def read_db_table(connection, schema: str, table: str, required: tuple,
                  optional: tuple = ()) -> pd.DataFrame:
    """Select only analytics columns, allowing the optional contributor flag."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s",
            (schema, table),
        )
        available = {row[0] for row in cursor.fetchall()}
        missing = set(required) - available
        if missing:
            raise DataError(
                f"{table} is missing columns: {', '.join(sorted(missing))}."
            )
        columns = list(required) + [c for c in optional if c in available]
        query = sql.SQL("SELECT {} FROM {}.{}").format(
            sql.SQL(", ").join(sql.Identifier(c) for c in columns),
            sql.Identifier(schema), sql.Identifier(table),
        )
        cursor.execute(query)
        return pd.DataFrame.from_records(cursor.fetchall(), columns=columns)


def load_tables() -> tuple:
    """Read local CSVs or a consistent, read-only PostgreSQL snapshot."""
    mode = os.environ.get("USE_MOCK_DATA", "true").strip().casefold()
    if mode not in {"true", "false"}:
        raise DataError("USE_MOCK_DATA must be true or false.")
    if mode == "true":
        directory = os.environ.get(
            "MOCK_DATA_DIR", os.path.join(os.path.dirname(__file__), "mock_data")
        )
        return (
            read_mock_table(directory, "organizations", ORG_COLUMNS),
            read_mock_table(directory, "states", STATE_COLUMNS, "state"),
            read_mock_table(directory, "countries", COUNTRY_COLUMNS, "country"),
        )
    if psycopg2 is None:
        raise DataError("PostgreSQL mode requires psycopg2 to be installed.")
    settings = {
        "host": os.environ.get("DB_HOST"),
        "dbname": os.environ.get("DB_NAME"),
        "user": os.environ.get("DB_USER"),
        "password": os.environ.get("DB_PASSWORD"),
    }
    if not all(settings.values()):
        raise DataError("Set DB_HOST, DB_NAME, DB_USER and DB_PASSWORD.")
    settings.update(
        port=os.environ.get("DB_PORT", "5432"),
        sslmode=os.environ.get("DB_SSLMODE", "require"),
        connect_timeout=10,
    )
    schema = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")
    connection = psycopg2.connect(**settings)
    try:
        connection.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with connection:
            return (
                read_db_table(
                    connection, schema,
                    os.environ.get("DB_ORGANIZATIONS_TABLE", "organizations"),
                    ORG_COLUMNS, ("is_contributor",),
                ),
                read_db_table(
                    connection, schema,
                    os.environ.get("DB_STATES_TABLE", "state"), STATE_COLUMNS,
                ),
                read_db_table(
                    connection, schema,
                    os.environ.get("DB_COUNTRIES_TABLE", "country"),
                    COUNTRY_COLUMNS, ("country_code", "country_name"),
                ),
            )
    finally:
        connection.close()


def normalize_flag(values: pd.Series, name: str) -> pd.Series:
    """Parse booleans explicitly; the string 'False' must never count as true."""
    tokens = values.astype("string").str.strip().str.casefold().fillna("")
    mapping = {
        "true": True, "t": True, "1": True, "1.0": True,
        "false": False, "f": False, "0": False, "0.0": False, "": False,
    }
    if not tokens.isin(mapping).all():
        raise DataError(f"{name} contains an invalid boolean value.")
    return tokens.map(mapping).astype(bool)


def prepare_organizations(tables: tuple) -> pd.DataFrame:
    """Validate rows and join geography without dropping unlocated orgs."""
    organizations, states, countries = [frame.copy() for frame in tables]
    for frame, required, label, key in (
        (organizations, ORG_COLUMNS, "organizations", "org_id"),
        (states, STATE_COLUMNS, "states", "state_id"),
        (countries, COUNTRY_COLUMNS, "countries", "country_id"),
    ):
        require_columns(frame, required, label)
        for column in set(frame.columns) & {"org_id", "state_id", "country_id"}:
            frame[column] = frame[column].astype("string").str.strip()
        if frame[key].isna().any() or frame[key].eq("").any():
            raise DataError(f"{label}.{key} must not be empty.")
        if frame[key].duplicated().any():
            raise DataError(f"{label}.{key} must be unique.")
    geography = [c for c in ("country_code", "country_name") if c in countries]
    if not geography:
        raise DataError("countries needs country_code or country_name.")
    organizations = organizations[
        list(ORG_COLUMNS) + (["is_contributor"] if "is_contributor" in organizations else [])
    ]
    organizations["created_at"] = pd.to_datetime(
        organizations["created_at"], format="mixed", utc=True, errors="coerce"
    )
    if organizations["created_at"].isna().any():
        raise DataError("organizations.created_at contains a missing or invalid timestamp.")
    if organizations["org_size"].isna().any() or (
        organizations["org_size"].astype("string").str.strip().eq("").any()
    ):
        raise DataError("organizations.org_size must not be empty.")
    for flag in ("is_collaborator", "is_contributor"):
        if flag not in organizations:
            organizations[flag] = False
        organizations[flag] = normalize_flag(organizations[flag], flag)
    # Older checked-in fixtures use Non-Profit/For-Profit labels.
    organizations["org_type"] = (
        organizations["org_type"].astype("string").str.strip().str.casefold()
        .str.replace("-", "_", regex=False)
    )
    return (
        organizations.merge(
            states[list(STATE_COLUMNS)], on="state_id", how="left",
            validate="many_to_one",
        ).merge(
            countries[["country_id"] + geography], on="country_id", how="left",
            validate="many_to_one",
        )
    )


def filter_organizations(frame: pd.DataFrame, country: str,
                         organization_type: str) -> pd.DataFrame:
    """Apply the shared country and type filters before any time window."""
    if country != "all":
        matches = pd.Series(False, index=frame.index)
        for column in ("country_code", "country_name"):
            if column in frame:
                matches |= (
                    frame[column].astype("string").str.strip().str.casefold()
                    .eq(country).fillna(False)
                )
        frame = frame.loc[matches]
    if organization_type != "all":
        frame = frame.loc[frame["org_type"].eq(organization_type).fillna(False)]
    return frame


def empty_charts() -> dict:
    """Create independent arrays for one empty bucket."""
    return {"organizations_by_size": [], "collaborator_vs_contributor": []}


def size_chart(frame: pd.DataFrame) -> list:
    """Return only observed raw size categories in deterministic order."""
    return [
        {"size": str(size), "count": int(count)}
        for size, count in frame.groupby("org_size", sort=True).size().items()
    ]


def contribution_chart(frame: pd.DataFrame) -> list:
    """Compute two independent shares of the same window's organization total."""
    if frame.empty:
        return []
    return [
        {
            "type": label,
            "count": int(frame[column].sum()),
            "percentage": round(int(frame[column].sum()) * 100 / len(frame), 1),
        }
        for label, column in (
            ("Collaborator", "is_collaborator"), ("Contributor", "is_contributor")
        )
    ]


def custom_window(frame: pd.DataFrame, date_range: tuple) -> pd.DataFrame:
    """Include the entire UTC end date, including fractional seconds."""
    return frame.loc[frame["created_at"].dt.date.between(*date_range)]


def build_analytics(frame: pd.DataFrame, size_range: tuple | None,
                    contribution_range: tuple | None, now: datetime) -> dict:
    """Compute only the charts and windows selected by the request."""
    if size_range is not None or contribution_range is not None:
        charts = empty_charts()
        if size_range is not None:
            charts["organizations_by_size"] = size_chart(custom_window(frame, size_range))
        if contribution_range is not None:
            charts["collaborator_vs_contributor"] = contribution_chart(
                custom_window(frame, contribution_range)
            )
        return {"Custom": charts}
    result = {}
    for key, days in (("7D", 7), ("30D", 30), ("1Y", 365), ("All", None)):
        mask = frame["created_at"].le(now)
        if days is not None:
            mask &= frame["created_at"].ge(now - timedelta(days=days))
        window = frame.loc[mask]
        result[key] = {
            "organizations_by_size": size_chart(window),
            "collaborator_vs_contributor": contribution_chart(window),
        }
    result["Custom"] = empty_charts()
    return result


def lambda_handler(event, context) -> dict:
    """Validate all filters before loading data; never return partial results."""
    try:
        filters = parse_request(event)
        country = parse_text_filter(filters, "country")
        organization_type = parse_text_filter(filters, "organization_type")
        size_range = parse_date_range(filters, "size")
        contribution_range = parse_date_range(filters, "contribution")
    except InputError as exc:
        return build_response(400, {"error": str(exc)})
    try:
        now = utc_now()
        frame = prepare_organizations(load_tables())
        frame = filter_organizations(frame, country, organization_type)
        return build_response(
            200, build_analytics(frame, size_range, contribution_range, now)
        )
    except DataError as exc:
        return build_response(500, {"error": str(exc)})
    except Exception:
        LOGGER.exception("Size & Contribution analytics failed")
        return build_response(500, {"error": "Unable to load organization analytics."})


if __name__ == "__main__":
    current_year = utc_now().year
    size_dates = {
        "size_start_date": f"{current_year}-01-01",
        "size_end_date": f"{current_year}-12-31",
    }
    contribution_dates = {
        "contribution_start_date": f"{current_year - 1}-01-01",
        "contribution_end_date": f"{current_year - 1}-12-31",
    }
    examples = [
        ("No body", {}),
        ("Country filter", {"body": json.dumps({"country": "USA"})}),
        ("Organization type filter", {"organization_type": "non_profit"}),
        ("Size Custom only", size_dates),
        ("Contribution Custom only", contribution_dates),
        ("Both Custom ranges", {**size_dates, **contribution_dates}),
    ]
    failed = False
    for label, event in examples:
        response = lambda_handler(event, None)
        print(f"\n{label}\nRequest: {json.dumps(event)}")
        print(f"HTTP {response['statusCode']}")
        print(json.dumps(json.loads(response["body"]), indent=2))
        failed |= response["statusCode"] != 200
    raise SystemExit(1 if failed else 0)
