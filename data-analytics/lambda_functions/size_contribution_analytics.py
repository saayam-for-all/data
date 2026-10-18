"""
Size & Contribution Analytics API (Organization Analytics dashboard).

Returns the data for the "Size & Contribution" tab, which has two charts:

* ``organizations_by_size``: organization count per ``org_size`` value.
* ``collaborator_vs_contributor``: ``count(is_collaborator)`` and
  ``count(is_contributor)``, each with its percentage of the bucket's total
  organizations. The two flags are independent (an organization can be both,
  or neither), so the two rows are not expected to add up to the total.

Response shape (same pattern as the Growth & Location API and the volunteer-side
reference implementation, except that both Custom ranges are honoured together):

* No Custom date params: ``7D``, ``30D``, ``1Y``, ``All`` and an empty ``Custom``.
* Any Custom date params: ``Custom`` only. ``size_start_date``/``size_end_date``
  populate ``organizations_by_size`` and ``contribution_start_date``/
  ``contribution_end_date`` populate ``collaborator_vs_contributor``. The pairs
  are independent and may be sent together.

Both charts are window-scoped snapshots: each bucket counts only organizations
created inside its own window, after the ``country`` and ``organization_type``
filters.

Data source:

* ``USE_MOCK_DATA=true``: pandas reads ``organizations.csv``, ``states.csv`` and
  ``countries.csv`` from ``MOCK_DATA_DIR``.
* Otherwise: Postgres through psycopg2. psycopg2 is an optional import, so this
  file still runs standalone with ``USE_MOCK_DATA=true`` when it isn't installed.
"""

import json
import logging
import os
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional, Tuple

import pandas as pd

try:  # Only the real-database path needs psycopg2.
    import psycopg2
    from psycopg2 import sql as pg_sql
except ImportError:
    psycopg2 = None
    pg_sql = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Same default folder as growth_location_analytics.py; override with MOCK_DATA_DIR.
DEFAULT_MOCK_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "mock-data-generation",
)
DEFAULT_DB_SCHEMA = "virginia_dev_saayam_rdbms"

# Real-database table names (the lookup tables are singular in the database).
ORG_TABLE = "organizations"
STATE_TABLE = "state"
COUNTRY_TABLE = "country"

ORG_REQUIRED_COLUMNS = ("org_id", "org_size", "org_type", "state_id", "created_at")
ORG_FLAG_COLUMNS = ("is_collaborator", "is_contributor")  # missing -> counted as 0
COUNTRY_LABEL_COLUMNS = ("country_code", "country_name")  # country filter matches either

# Fixed buckets are calendar-day windows ending today, matching
# growth_location_analytics.py (7D = today plus the 6 days before it).
# None means no date filter.
FIXED_WINDOWS = {"7D": 7, "30D": 30, "1Y": 365, "All": None}

ORGANIZATION_TYPES = ("non_profit", "for_profit")
CHART_KEYS = ("organizations_by_size", "collaborator_vs_contributor")
FLAG_ROWS = (("Collaborator", "is_collaborator"), ("Contributor", "is_contributor"))
TRUTHY_VALUES = {"true", "t", "1", "1.0", "yes", "y"}
DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

RESPONSE_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

DateRange = Tuple[date, date]


class RequestValidationError(ValueError):
    """The request is invalid. Reported to the caller as HTTP 400."""


class DataSourceError(RuntimeError):
    """The data source is missing or misconfigured. Logged, reported as HTTP 500."""


# ---------------------------------------------------------------------------
# Request parsing and validation
# ---------------------------------------------------------------------------


def parse_event(event) -> dict:
    """Return the request parameters from an API Gateway event or a direct invocation."""
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise RequestValidationError("Request must be a JSON object")
    if "body" not in event:
        return event  # Direct invocation: parameters are at the top level.

    body = event["body"]
    if body is None or (isinstance(body, str) and not body.strip()):
        return {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise RequestValidationError("Request body must be valid JSON") from None
    if not isinstance(body, dict):
        raise RequestValidationError("Request body must be a JSON object")
    return body


def normalize_label(value) -> Optional[str]:
    """Case- and separator-insensitive form used to compare filter values with data.

    "non_profit", "Non-Profit" and "NON PROFIT" all become "NON PROFIT";
    "UNITED_STATES_OF_AMERICA" and "United States of America" match each other.
    """
    if value is None or pd.isna(value):
        return None
    normalized = " ".join(str(value).replace("_", " ").replace("-", " ").upper().split())
    return normalized or None


def _parse_label_filter(params: dict, key: str, allowed: Optional[set] = None,
                        expected: str = "") -> Optional[str]:
    """Validate a text filter. Returns its normalized value, or None for ALL/absent."""
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RequestValidationError(f"{key} must be {expected}")
    normalized = normalize_label(value)
    if normalized is None:  # e.g. "-" or "_": nothing left after normalizing
        raise RequestValidationError(f"{key} must be {expected}")
    if normalized == "ALL":
        return None
    if allowed is not None and normalized not in allowed:
        raise RequestValidationError(f"{key} must be {expected}")
    return normalized


def _parse_date_range(params: dict, start_key: str, end_key: str) -> Optional[DateRange]:
    """Validate one Custom date pair the same way growth_location_analytics.py does.

    Both halves absent -> None. Otherwise both must be YYYY-MM-DD calendar dates
    with start <= end; anything else raises RequestValidationError.
    """
    start, end = params.get(start_key), params.get(end_key)
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise RequestValidationError(f"{start_key} and {end_key} must be provided together")

    parsed = []
    for key, value in ((start_key, start), (end_key, end)):
        if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
            raise RequestValidationError(f"{key} must be a date in YYYY-MM-DD format")
        try:
            parsed.append(datetime.strptime(value, "%Y-%m-%d").date())
        except ValueError:
            raise RequestValidationError(f"{key} is not a valid calendar date") from None

    if parsed[0] > parsed[1]:
        raise RequestValidationError(f"{start_key} must be on or before {end_key}")
    return parsed[0], parsed[1]


def parse_filters(params: dict) -> dict:
    """Validate every supported filter. Unknown keys are ignored."""
    organization_types = {normalize_label(value) for value in ORGANIZATION_TYPES}
    return {
        "country": _parse_label_filter(
            params, "country", expected="a country name, a country code, or ALL"
        ),
        "organization_type": _parse_label_filter(
            params,
            "organization_type",
            allowed=organization_types,
            expected=f"one of: {', '.join(ORGANIZATION_TYPES)}, ALL",
        ),
        "size_range": _parse_date_range(params, "size_start_date", "size_end_date"),
        "contribution_range": _parse_date_range(
            params, "contribution_start_date", "contribution_end_date"
        ),
    }


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def use_mock_data() -> bool:
    """True when USE_MOCK_DATA is set to true/1/yes."""
    return os.environ.get("USE_MOCK_DATA", "").strip().lower() in {"true", "1", "yes"}


def load_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Return (organizations joined to their country labels, countries lookup)."""
    if use_mock_data():
        return load_mock_data(os.environ.get("MOCK_DATA_DIR") or DEFAULT_MOCK_DATA_DIR)
    return load_db_data()


def _read_csv(path: str, expected_columns) -> pd.DataFrame:
    """Read a CSV with every column as text (keeps IDs like '233.10' intact)."""
    try:
        return pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    except FileNotFoundError:
        raise DataSourceError(
            f"Mock data file not found: {path}. Point MOCK_DATA_DIR at the folder "
            "holding organizations.csv, states.csv and countries.csv."
        ) from None
    except pd.errors.EmptyDataError:  # A 0-byte file means "no rows".
        return pd.DataFrame(columns=list(expected_columns))


def _require_columns(frame: pd.DataFrame, required, source: str) -> None:
    """Raise DataSourceError naming any required columns that are missing."""
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise DataSourceError(f"{source} is missing required column(s): {', '.join(missing)}")


def _clean_ids(values: pd.Series, integer: bool = False) -> pd.Series:
    """Trim text IDs; integer IDs also lose a stray '.0' suffix ('233.0' -> '233')."""
    cleaned = values.str.strip()
    if integer:
        cleaned = cleaned.str.replace(r"\.0+$", "", regex=True)
    return cleaned


def load_mock_data(data_dir: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load the three mock CSVs and join organizations.state_id -> states -> countries."""
    orgs = _read_csv(
        os.path.join(data_dir, "organizations.csv"), ORG_REQUIRED_COLUMNS + ORG_FLAG_COLUMNS
    )
    states = _read_csv(os.path.join(data_dir, "states.csv"), ("state_id", "country_id"))
    countries = _read_csv(
        os.path.join(data_dir, "countries.csv"), ("country_id",) + COUNTRY_LABEL_COLUMNS
    )

    _require_columns(orgs, ORG_REQUIRED_COLUMNS, "organizations.csv")
    _require_columns(states, ("state_id", "country_id"), "states.csv")
    _require_columns(countries, ("country_id",), "countries.csv")
    labels = [column for column in COUNTRY_LABEL_COLUMNS if column in countries.columns]
    if not labels:
        raise DataSourceError("countries.csv needs a country_code or country_name column")

    # De-duplicate the lookups so a repeated row can't multiply organizations in the join.
    states = states.assign(
        state_id=_clean_ids(states["state_id"]),
        country_id=_clean_ids(states["country_id"], integer=True),
    )
    states = states.dropna(subset=["state_id"]).drop_duplicates("state_id")
    countries = countries.assign(country_id=_clean_ids(countries["country_id"], integer=True))
    countries = countries.dropna(subset=["country_id"]).drop_duplicates("country_id")

    orgs = orgs.drop(columns=["country_id", *COUNTRY_LABEL_COLUMNS], errors="ignore")
    orgs = orgs.assign(state_id=_clean_ids(orgs["state_id"]))
    orgs = orgs.merge(states[["state_id", "country_id"]], on="state_id", how="left")
    orgs = orgs.merge(countries[["country_id", *labels]], on="country_id", how="left")
    return orgs, countries[labels]


def get_db_connection():
    """Open a read-only, autocommit Postgres connection from environment variables.

    Uses the same variable names as data-engineering/.env.example (DB_HOST,
    DB_PORT, DB_NAME, DB_USER, DB_PASSWORD), plus DB_SSLMODE (default "require").
    If the team's other analytics Lambdas connect differently (e.g. via SSM
    Parameter Store), swap the body of this function; nothing else depends on it.
    """
    if psycopg2 is None:
        raise DataSourceError(
            "psycopg2 is not installed. Install it, or set USE_MOCK_DATA=true to read local CSVs."
        )
    missing = [name for name in ("DB_HOST", "DB_NAME", "DB_USER") if not os.environ.get(name)]
    if missing:
        raise DataSourceError(f"Missing database setting(s): {', '.join(missing)}")

    connection = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ.get("DB_PASSWORD"),
        sslmode=os.environ.get("DB_SSLMODE", "require"),
        connect_timeout=10,
    )
    # Autocommit avoids leaving a failed transaction open; read-only is a safety net.
    connection.set_session(readonly=True, autocommit=True)
    return connection


def _table_columns(cursor, schema: str, table: str) -> set:
    """Column names of schema.table, or DataSourceError if the table isn't visible."""
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (schema, table),
    )
    columns = {row[0] for row in cursor.fetchall()}
    if not columns:
        raise DataSourceError(f"Table {schema}.{table} was not found or is not readable")
    return columns


def _fetch_frame(cursor) -> pd.DataFrame:
    """Turn the cursor's current result set into a DataFrame."""
    return pd.DataFrame(cursor.fetchall(), columns=[column[0] for column in cursor.description])


def load_db_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Load the same two frames as load_mock_data, from Postgres.

    All filtering and aggregation then runs through the same pandas code as the
    mock path, so the CSV tests exercise the production logic. Column names are
    checked first so a schema mismatch fails with a clear message instead of a
    SQL error, and missing flag columns are read as NULL (counted as 0).
    """
    schema = os.environ.get("ORG_ANALYTICS_SCHEMA") or DEFAULT_DB_SCHEMA
    connection = get_db_connection()
    try:
        with connection.cursor() as cursor:
            org_columns = _table_columns(cursor, schema, ORG_TABLE)
            missing = [column for column in ORG_REQUIRED_COLUMNS if column not in org_columns]
            if missing:
                raise DataSourceError(
                    f"{schema}.{ORG_TABLE} is missing required column(s): {', '.join(missing)}"
                )
            state_columns = _table_columns(cursor, schema, STATE_TABLE)
            missing = [c for c in ("state_id", "country_id") if c not in state_columns]
            if missing:
                raise DataSourceError(
                    f"{schema}.{STATE_TABLE} is missing required column(s): {', '.join(missing)}"
                )
            country_columns = _table_columns(cursor, schema, COUNTRY_TABLE)
            labels = [column for column in COUNTRY_LABEL_COLUMNS if column in country_columns]
            if "country_id" not in country_columns or not labels:
                raise DataSourceError(
                    f"{schema}.{COUNTRY_TABLE} needs country_id and country_code or country_name"
                )

            def column(alias: str, name: str):
                return pg_sql.SQL("{}.{}").format(pg_sql.Identifier(alias), pg_sql.Identifier(name))

            select_list = [column("o", name) for name in ORG_REQUIRED_COLUMNS]
            for flag in ORG_FLAG_COLUMNS:
                select_list.append(
                    column("o", flag)
                    if flag in org_columns
                    else pg_sql.SQL("NULL AS {}").format(pg_sql.Identifier(flag))
                )
            select_list.extend(column("c", label) for label in labels)

            cursor.execute(
                pg_sql.SQL(
                    "SELECT {columns} FROM {orgs} AS o "
                    "LEFT JOIN {states} AS s ON s.state_id = o.state_id "
                    "LEFT JOIN {countries} AS c ON c.country_id = s.country_id"
                ).format(
                    columns=pg_sql.SQL(", ").join(select_list),
                    orgs=pg_sql.Identifier(schema, ORG_TABLE),
                    states=pg_sql.Identifier(schema, STATE_TABLE),
                    countries=pg_sql.Identifier(schema, COUNTRY_TABLE),
                )
            )
            orgs = _fetch_frame(cursor)

            cursor.execute(
                pg_sql.SQL("SELECT {labels} FROM {countries}").format(
                    labels=pg_sql.SQL(", ").join(pg_sql.Identifier(label) for label in labels),
                    countries=pg_sql.Identifier(schema, COUNTRY_TABLE),
                )
            )
            countries = _fetch_frame(cursor)
        return orgs, countries
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Transformation
# ---------------------------------------------------------------------------


def _to_timestamps(values: pd.Series) -> pd.Series:
    """Parse created_at into naive UTC timestamps; unparseable values become NaT."""
    try:
        parsed = pd.to_datetime(values, errors="coerce", utc=True, format="ISO8601")
    except (TypeError, ValueError):  # pandas < 2.0 has no format="ISO8601"
        parsed = pd.to_datetime(values, errors="coerce", utc=True)
    return parsed.dt.tz_convert(None)


def _to_bool(values: pd.Series) -> pd.Series:
    """Read TRUE/true/1/yes (text, bool or number) as True; anything else as False."""
    return values.astype(str).str.strip().str.lower().isin(TRUTHY_VALUES)


def prepare_organizations(orgs: pd.DataFrame) -> pd.DataFrame:
    """Normalize types once so every bucket works from the same clean frame."""
    orgs = orgs[orgs["org_id"].isna() | ~orgs.duplicated(subset="org_id")].copy()
    orgs["created_at"] = _to_timestamps(orgs["created_at"])
    for flag in ORG_FLAG_COLUMNS:
        orgs[flag] = _to_bool(orgs[flag]) if flag in orgs.columns else False

    undated = int(orgs["created_at"].isna().sum())
    if undated:
        logger.warning(
            "%d organization(s) have a missing or unparseable created_at; "
            "they are only counted in the 'All' bucket.",
            undated,
        )
    return orgs


def _label_matches(frame: pd.DataFrame, target: str) -> pd.Series:
    """Rows whose country_code or country_name matches the normalized target."""
    mask = pd.Series(False, index=frame.index)
    for column in COUNTRY_LABEL_COLUMNS:
        if column in frame.columns:
            mask |= frame[column].map(normalize_label) == target
    return mask


def apply_filters(orgs: pd.DataFrame, countries: pd.DataFrame, country: Optional[str],
                  organization_type: Optional[str]) -> pd.DataFrame:
    """Apply the country / organization_type filters (None means ALL)."""
    if country is not None:
        if not _label_matches(countries, country).any():
            raise RequestValidationError("country does not match any known country name or code")
        orgs = orgs[_label_matches(orgs, country)]
    if organization_type is not None:
        orgs = orgs[orgs["org_type"].map(normalize_label) == organization_type]
    return orgs


def _created_between(orgs: pd.DataFrame, start: Optional[pd.Timestamp] = None,
                     end_exclusive: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    """Organizations created in [start, end_exclusive). Undated rows never match."""
    mask = pd.Series(True, index=orgs.index)
    if start is not None:
        mask &= orgs["created_at"] >= start
    if end_exclusive is not None:
        mask &= orgs["created_at"] < end_exclusive
    return orgs[mask]


def fixed_window(orgs: pd.DataFrame, days: Optional[int], today: pd.Timestamp) -> pd.DataFrame:
    """Organizations in a fixed bucket: the last `days` calendar days, or all of them."""
    if days is None:
        return orgs
    return _created_between(orgs, start=today - pd.Timedelta(days=days - 1))


def custom_window(orgs: pd.DataFrame, date_range: DateRange) -> pd.DataFrame:
    """Organizations created between two dates, both ends inclusive."""
    start, end = date_range
    return _created_between(
        orgs,
        start=pd.Timestamp(start),
        end_exclusive=pd.Timestamp(end) + pd.Timedelta(days=1),
    )


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------


def percentage(count: int, total: int) -> float:
    """count / total as a percentage, rounded half-up to 1 decimal (2/3 -> 66.7)."""
    if not total:
        return 0.0
    share = Decimal(count) * 100 / Decimal(total)
    return float(share.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def organizations_by_size(window: pd.DataFrame) -> List[dict]:
    """One row per org_size value present in the window, using the raw value.

    Sizes aren't hardcoded or zero-filled. Rows are ordered by count (largest
    first, ties alphabetical), like the location chart in Growth & Location.
    Organizations with no size are reported as size null, so the counts always
    add up to the window's total.
    """
    if window.empty:
        return []
    rows = []
    for size, count in window["org_size"].value_counts(dropna=False).items():
        label = None if pd.isna(size) else (size if isinstance(size, str) else str(size))
        rows.append({"size": label, "count": int(count)})
    rows.sort(key=lambda row: (-row["count"], row["size"] is None, row["size"] or ""))
    return rows


def collaborator_vs_contributor(window: pd.DataFrame) -> List[dict]:
    """Exactly two rows, each counted independently against the window's total.

    An organization can be both a collaborator and a contributor (or neither),
    so the counts and percentages are not expected to add up to the total.
    """
    total = len(window)
    if total == 0:
        return []
    rows = []
    for label, column in FLAG_ROWS:
        count = int(window[column].sum())
        rows.append({"type": label, "count": count, "percentage": percentage(count, total)})
    return rows


def empty_bucket() -> Dict[str, list]:
    """A bucket with both charts empty."""
    return {key: [] for key in CHART_KEYS}


def build_bucket(window: pd.DataFrame) -> Dict[str, list]:
    """Both charts computed from the same window."""
    return {
        "organizations_by_size": organizations_by_size(window),
        "collaborator_vs_contributor": collaborator_vs_contributor(window),
    }


def build_fixed_response(orgs: pd.DataFrame, today: pd.Timestamp) -> dict:
    """All four fixed buckets plus an empty Custom bucket."""
    response = {
        key: build_bucket(fixed_window(orgs, days, today))
        for key, days in FIXED_WINDOWS.items()
    }
    response["Custom"] = empty_bucket()
    return response


def build_custom_response(orgs: pd.DataFrame, size_range: Optional[DateRange],
                          contribution_range: Optional[DateRange]) -> dict:
    """Custom only. Each chart is filled from its own range, independently of the other."""
    custom = empty_bucket()
    if size_range is not None:
        custom["organizations_by_size"] = organizations_by_size(custom_window(orgs, size_range))
    if contribution_range is not None:
        custom["collaborator_vs_contributor"] = collaborator_vs_contributor(
            custom_window(orgs, contribution_range)
        )
    return {"Custom": custom}


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def today_utc() -> pd.Timestamp:
    """Midnight today, UTC, as a naive timestamp (comparable with created_at)."""
    return pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()


def _response(status_code: int, body: dict) -> dict:
    """API Gateway proxy response with a JSON string body."""
    return {"statusCode": status_code, "headers": dict(RESPONSE_HEADERS), "body": json.dumps(body)}


def lambda_handler(event, context):
    """Return the Size & Contribution data for the requested filters."""
    try:
        # Validate the request before touching any data.
        filters = parse_filters(parse_event(event))
        orgs, countries = load_data()
        orgs = apply_filters(
            prepare_organizations(orgs), countries, filters["country"], filters["organization_type"]
        )
        if filters["size_range"] is None and filters["contribution_range"] is None:
            body = build_fixed_response(orgs, today_utc())
        else:
            body = build_custom_response(orgs, filters["size_range"], filters["contribution_range"])
        return _response(200, body)
    except RequestValidationError as error:
        return _response(400, {"error": str(error)})
    except Exception:
        logger.exception("Size & Contribution analytics request failed")
        return _response(500, {"error": "Internal server error"})


def format_for_console(value, level: int = 0) -> str:
    """Valid JSON laid out like the spec's examples, with each chart row on one line."""
    pad, inner = "  " * level, "  " * (level + 1)
    if isinstance(value, dict) and any(isinstance(item, (dict, list)) for item in value.values()):
        items = [f"{inner}{json.dumps(key)}: {format_for_console(item, level + 1)}"
                 for key, item in value.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(value, list) and value:
        items = [f"{inner}{format_for_console(item, level + 1)}" for item in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(value)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    os.environ.setdefault("USE_MOCK_DATA", "true")

    samples = [
        ("No body", None),
        ("Country filter", {"country": "USA"}),
        ("Organization type filter", {"organization_type": "non_profit"}),
        (
            "Size Custom range only",
            {"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"},
        ),
        (
            "Contribution Custom range only",
            {"contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"},
        ),
        (
            "Both Custom ranges together",
            {
                "size_start_date": "2026-01-01",
                "size_end_date": "2026-06-30",
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2025-12-31",
            },
        ),
        (
            "All filters together (the spec's example request)",
            {
                "country": "USA",
                "organization_type": "non_profit",
                "size_start_date": "2026-01-01",
                "size_end_date": "2026-06-30",
                "contribution_start_date": "2025-01-01",
                "contribution_end_date": "2025-12-31",
            },
        ),
        ("Invalid: only half of the size pair", {"size_start_date": "2026-01-01"}),
        (
            "Invalid: bad date format",
            {"contribution_start_date": "2025/01/01", "contribution_end_date": "2025-12-31"},
        ),
        (
            "Invalid: start after end",
            {"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"},
        ),
        ("Invalid: unknown organization_type", {"organization_type": "government"}),
    ]

    print(f"MOCK_DATA_DIR = {os.environ.get('MOCK_DATA_DIR') or DEFAULT_MOCK_DATA_DIR}")
    print(f"today (UTC) = {today_utc().date()}")
    for name, params in samples:
        event = {} if params is None else {"body": json.dumps(params)}
        result = lambda_handler(event, None)
        body = json.loads(result["body"])
        print(f"\n=== {name} ===")
        print(f"request: {json.dumps(params or {})}")
        print(f"statusCode: {result['statusCode']} | top-level keys: {list(body)}")
        print(format_for_console(body))
