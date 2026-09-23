"""Standalone Size & Contribution Analytics Lambda (Saayam data issue #376).

Local run (from the repo root):
    USE_MOCK_DATA=true python data-analytics/lambda_functions/size_contribution_analytics.py

When MOCK_DATA_DIR is unset, this reads the repository's existing
``data-analytics/sql`` CSVs. The supplied mock CSVs are never modified.
Production reads PostgreSQL with an optional psycopg2 dependency.
"""

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # CSV testing does not require PostgreSQL client libraries.
    psycopg2 = None
    RealDictCursor = None


DEFAULT_MOCK_DATA_DIR = Path(__file__).resolve().parent.parent / "sql"
BUCKETS = ("7D", "30D", "1Y", "All")
TRUE_TOKENS = frozenset({"TRUE", "T", "YES", "Y", "1", "1.0"})
VALID_TYPES = frozenset({"non_profit", "for_profit"})


class ValidationError(ValueError):
    """An invalid request parameter, returned as HTTP 400."""


def today():
    """Current date; this small wrapper makes fixed windows deterministic in tests."""
    return date.today()


def response(status_code, payload):
    """Build an API Gateway-compatible, JSON-serialized Lambda response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(payload),
    }


def parse_event(event):
    """Accept plain Lambda dicts, JSON/dict API Gateway bodies, or query params."""
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise ValidationError("Request must be a JSON object.")
    if "body" not in event:
        return event

    query = event.get("queryStringParameters") or {}
    if not isinstance(query, dict):
        raise ValidationError("queryStringParameters must be an object.")
    body = event["body"]
    if body is None or body == "":
        body = {}
    elif isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValidationError("Request body must contain valid JSON.") from exc
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object.")
    return {**query, **body}


def parse_date_pair(params, start_key, end_key):
    """Require both dates if either key is supplied; dates and endpoints inclusive."""
    supplied = start_key in params or end_key in params
    if not supplied:
        return None
    start_value, end_value = params.get(start_key), params.get(end_key)
    if not isinstance(start_value, str) or not isinstance(end_value, str):
        raise ValidationError(f"Supply both {start_key} and {end_key} as YYYY-MM-DD strings.")
    try:
        # isocalendar-style YYYY-MM-DD only, not timestamps or undelimited dates.
        if (len(start_value) != 10 or len(end_value) != 10
                or start_value[4] != "-" or start_value[7] != "-"
                or end_value[4] != "-" or end_value[7] != "-"):
            raise ValueError("Incorrect date format")
        start = datetime.strptime(start_value, "%Y-%m-%d").date()
        end = datetime.strptime(end_value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError(f"{start_key} and {end_key} must use valid YYYY-MM-DD dates.") from exc
    if start > end:
        raise ValidationError(f"{start_key} must be on or before {end_key}.")
    return start, end


def parse_filters(params):
    """Validate country and organization-type filters without silently ignoring bad input."""
    country = params.get("country", "ALL")
    org_type = params.get("organization_type", "ALL")
    if not isinstance(country, str) or not country.strip():
        raise ValidationError("country must be a non-empty country name, code, or ALL.")
    if not isinstance(org_type, str) or not org_type.strip():
        raise ValidationError("organization_type must be non_profit, for_profit, or ALL.")
    country = country.strip().upper()
    org_type = org_type.strip().lower().replace("-", "_").replace(" ", "_")
    if org_type not in VALID_TYPES and org_type != "all":
        raise ValidationError("organization_type must be non_profit, for_profit, or ALL.")
    return country, org_type


def find_csv(directory, candidates):
    """Find singular/plural CSV names, including case-insensitive variants."""
    for filename in candidates:
        path = directory / filename
        if path.is_file():
            return path
    if directory.is_dir():
        wanted = {name.lower() for name in candidates}
        for path in directory.iterdir():
            if path.is_file() and path.name.lower() in wanted:
                return path
    raise FileNotFoundError(f"Expected one of {candidates!r} in {directory}")


def normalized_flags(series):
    """Turn pandas bool, numeric, and textual TRUE/FALSE values into true booleans."""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0).ne(0)
    return series.astype(str).str.strip().str.upper().isin(TRUE_TOKENS)


def load_mock_data():
    """Read and left-join CSV data using the repository's state/country lookup."""
    directory = Path(os.getenv("MOCK_DATA_DIR") or DEFAULT_MOCK_DATA_DIR)
    orgs = pd.read_csv(find_csv(directory, ("organizations.csv",)))
    states = pd.read_csv(find_csv(directory, ("states.csv", "state.csv")))
    countries = pd.read_csv(find_csv(directory, ("countries.csv", "country.csv")))

    required_org = {"org_id", "org_size", "is_collaborator", "org_type", "state_id", "created_at"}
    required_states = {"state_id", "country_id"}
    required_countries = {"country_id"}
    for frame, required, label in (
        (orgs, required_org, "organizations.csv"),
        (states, required_states, "states.csv/state.csv"),
        (countries, required_countries, "countries.csv/country.csv"),
    ):
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{label} missing required columns: {', '.join(sorted(missing))}")
    if "country_code" not in countries and "country_name" not in countries:
        raise ValueError("country CSV must contain country_code or country_name")

    # Use separate lookup frames so duplicate non-key columns cannot add suffixes.
    states = states[["state_id", "country_id"]].copy()
    countries = countries[[c for c in ("country_id", "country_code", "country_name") if c in countries]].copy()
    for df in (states, orgs):
        df["state_id"] = df["state_id"].astype(str).str.strip().str.upper()
    for df in (states, countries):
        df["country_id"] = pd.to_numeric(df["country_id"], errors="coerce").astype("Int64")
    if states["state_id"].duplicated().any() or countries["country_id"].duplicated().any():
        raise ValueError("Country/state lookup keys must be unique")

    lookup = states.merge(countries, how="left", on="country_id", validate="many_to_one")
    merged = orgs.merge(lookup, how="left", on="state_id", validate="many_to_one")
    for col in ("country_code", "country_name"):
        if col not in merged:
            merged[col] = ""
    return normalize_organizations(merged)


def load_postgres_data():
    """Read the real organizations table via psycopg2; no AWS credentials in code.

    Set DATABASE_URL, or DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD. The
    default schema uses the existing Virginia environment's schema name.
    Column and lookup table names should be verified by the deployment lead.
    """
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed; install it for the PostgreSQL path")
    schema = os.getenv("ORG_ANALYTICS_SCHEMA", "virginia_dev_saayam_rdbms")
    if not schema or not schema[0].isalpha() or not schema.replace("_", "").isalnum():
        raise ValueError("Invalid ORG_ANALYTICS_SCHEMA")
    url = os.getenv("DATABASE_URL")
    conn_params = ({"dsn": url} if url else {
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT", "5432"),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
    })
    conn = psycopg2.connect(**conn_params)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Some older organization tables have no is_contributor column.
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s",
                (schema, "organizations"),
            )
            columns = {row["column_name"] for row in cursor.fetchall()}
            contributor_expr = "o.is_contributor" if "is_contributor" in columns else "FALSE"
            # Names are trusted identifiers; user-supplied filters never become SQL.
            cursor.execute(f"""
                SELECT o.org_id, o.org_size, o.is_collaborator,
                       {contributor_expr} AS is_contributor,
                       o.org_type, o.state_id, o.created_at,
                       c.country_code, c.country_name
                FROM {schema}.organizations AS o
                LEFT JOIN {schema}.state AS s ON o.state_id = s.state_id
                LEFT JOIN {schema}.country AS c ON s.country_id = c.country_id
            """)
            rows = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
    columns = ("org_id", "org_size", "is_collaborator", "is_contributor",
               "org_type", "state_id", "created_at", "country_code", "country_name")
    return normalize_organizations(pd.DataFrame(rows, columns=columns))


def normalize_organizations(frame):
    """Normalize the tracked CSV's `Small`/`Non-Profit` spellings to API enums."""
    frame = frame.copy()
    if "is_contributor" not in frame:
        frame["is_contributor"] = False
    for col in ("country_code", "country_name"):
        if col not in frame:
            frame[col] = ""
        frame[col] = frame[col].fillna("").astype(str).str.strip().str.upper()
    for col in ("org_size", "org_type"):
        frame[col] = frame[col].fillna("unknown").astype(str).str.strip().str.lower()
    frame["org_type"] = frame["org_type"].str.replace("-", "_", regex=False).str.replace(" ", "_", regex=False)
    frame["is_collaborator"] = normalized_flags(frame["is_collaborator"])
    frame["is_contributor"] = normalized_flags(frame["is_contributor"])
    frame["created_at"] = pd.to_datetime(frame["created_at"], errors="coerce")
    dropped = int(frame["created_at"].isna().sum())
    if dropped:
        print(f"WARNING: ignoring {dropped} organizations with invalid created_at")
    return frame.dropna(subset=["created_at"]).reset_index(drop=True)


def filter_organizations(frame, country, org_type):
    """Apply country code/name and organization-type filters to both charts."""
    if country != "ALL":
        frame = frame.loc[(frame["country_code"] == country) | (frame["country_name"] == country)]
    if org_type != "all":
        frame = frame.loc[frame["org_type"] == org_type]
    return frame


def within_window(frame, start=None, end=None):
    """Filter by inclusive calendar dates; end includes all timestamps that day."""
    if start is not None:
        frame = frame.loc[frame["created_at"].dt.normalize() >= pd.Timestamp(start)]
    if end is not None:
        frame = frame.loc[frame["created_at"].dt.normalize() <= pd.Timestamp(end)]
    return frame


def by_size(frame):
    """Return only size categories actually represented in this time window."""
    if frame.empty:
        return []
    counts = frame["org_size"].value_counts()
    return [{"size": str(size), "count": int(count)}
            for size, count in sorted(counts.items(), key=lambda item: item[0])]


def by_contribution(frame):
    """Count collaborator/contributor columns independently, each over all orgs."""
    total = len(frame)
    if total == 0:
        return []
    collab = int(frame["is_collaborator"].sum())
    contrib = int(frame["is_contributor"].sum())
    return [
        {"type": "Collaborator", "count": collab, "percentage": round(100 * collab / total, 1)},
        {"type": "Contributor", "count": contrib, "percentage": round(100 * contrib / total, 1)},
    ]


def blank_charts():
    """Return independent empty arrays, without any extra keys."""
    return {"organizations_by_size": [], "collaborator_vs_contributor": []}


def lambda_handler(event, context):
    """Return four fixed snapshots plus empty Custom, or Custom-only snapshots."""
    try:
        params = parse_event(event)
        country, org_type = parse_filters(params)
        size_range = parse_date_pair(params, "size_start_date", "size_end_date")
        contribution_range = parse_date_pair(params, "contribution_start_date", "contribution_end_date")
    except ValidationError as exc:
        return response(400, {"error": str(exc)})

    try:
        mock_mode = os.getenv("USE_MOCK_DATA", "false").strip().lower() in ("true", "1", "yes")
        frame = load_mock_data() if mock_mode else load_postgres_data()
        frame = filter_organizations(frame, country, org_type)
        if size_range is not None or contribution_range is not None:
            result = blank_charts()
            if size_range is not None:
                result["organizations_by_size"] = by_size(within_window(frame, *size_range))
            if contribution_range is not None:
                result["collaborator_vs_contributor"] = by_contribution(
                    within_window(frame, *contribution_range))
            return response(200, {"Custom": result})

        fixed = {}
        current = today()
        for bucket in BUCKETS:
            window_start = (
                current - timedelta(days={"7D": 7, "30D": 30, "1Y": 365}[bucket])
                if bucket != "All" else None
            )
            window = within_window(frame, window_start)
            fixed[bucket] = {
                "organizations_by_size": by_size(window),
                "collaborator_vs_contributor": by_contribution(window),
            }
        fixed["Custom"] = blank_charts()
        return response(200, fixed)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"ERROR: Size & Contribution data unavailable: {exc}")
        return response(500, {"error": "Could not load organization data."})
    except Exception as exc:  # A database/data issue must not expose a traceback to clients.
        print(f"ERROR: Size & Contribution query failed: {exc}")
        return response(500, {"error": "Could not load organization data."})


if __name__ == "__main__":
    os.environ.setdefault("USE_MOCK_DATA", "true")
    examples = (
        ("no body", {}),
        ("country", {"country": "AFG"}),
        ("organization type", {"organization_type": "non_profit"}),
        ("size Custom", {"size_start_date": "2025-01-01", "size_end_date": "2025-12-31"}),
        ("contribution Custom", {"contribution_start_date": "2025-01-01", "contribution_end_date": "2025-12-31"}),
        ("both Custom ranges", {"size_start_date": "2025-01-01", "size_end_date": "2025-12-31",
                                "contribution_start_date": "2024-01-01", "contribution_end_date": "2024-12-31"}),
        ("invalid date", {"size_start_date": "2025-13-01", "size_end_date": "2025-12-31"}),
    )
    for label, sample in examples:
        result = lambda_handler(sample, None)
        print(f"\n=== {label} ===")
        print(json.dumps({"statusCode": result["statusCode"], "body": json.loads(result["body"])}, indent=2))
