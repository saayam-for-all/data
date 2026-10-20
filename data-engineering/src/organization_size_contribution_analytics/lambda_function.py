"""Build the Organization Analytics Size and Contribution dashboard data."""

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

try:
    import psycopg2
except ImportError:  # pragma: no cover - optional in local mock mode
    psycopg2 = None


FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
CHART_KEYS = ("organizations_by_size", "collaborator_vs_contributor")
ORG_TYPE_ALIASES = {
    "non_profit": "non_profit",
    "nonprofit": "non_profit",
    "non-profit": "non_profit",
    "for_profit": "for_profit",
    "forprofit": "for_profit",
    "for-profit": "for_profit",
}


def _empty_charts() -> dict[str, list[dict[str, Any]]]:
    """Return the two empty chart payloads."""
    return {key: [] for key in CHART_KEYS}


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Build an API Gateway-compatible response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def _parse_body(event: Any) -> dict[str, Any]:
    """Parse an API Gateway event body into a dictionary."""
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    raw_body = event.get("body")
    if raw_body is None:
        return event
    if isinstance(raw_body, str):
        parsed = json.loads(raw_body)
    else:
        parsed = raw_body
    if not isinstance(parsed, dict):
        raise ValueError("request body must be an object")
    return parsed


def _parse_date_pair(body: dict[str, Any], start_key: str, end_key: str) -> Optional[tuple[date, date]]:
    """Validate and parse one optional inclusive date range."""
    has_start = start_key in body
    has_end = end_key in body
    if not has_start and not has_end:
        return None
    if not has_start or not has_end or body[start_key] is None or body[end_key] is None:
        raise ValueError(f"{start_key} and {end_key} must be supplied together")
    try:
        start = date.fromisoformat(str(body[start_key]))
        end = date.fromisoformat(str(body[end_key]))
    except ValueError as error:
        raise ValueError(f"{start_key} and {end_key} must use YYYY-MM-DD") from error
    if start > end:
        raise ValueError(f"{start_key} must not be after {end_key}")
    return start, end


def _normalize_org_type(value: Any) -> Optional[str]:
    """Normalize an organization type filter or reject it."""
    if value is None or str(value).upper() == "ALL":
        return None
    normalized = ORG_TYPE_ALIASES.get(str(value).strip().lower())
    if normalized is None:
        raise ValueError("organization_type must be non_profit, for_profit, or ALL")
    return normalized


def _normalize_text(value: Any) -> str:
    """Normalize a CSV value for case-insensitive comparisons."""
    return str(value).strip().casefold()


def _read_csv(data_dir: Path, names: tuple[str, ...]) -> pd.DataFrame:
    """Read the first available CSV filename from a list of aliases."""
    for name in names:
        path = data_dir / name
        if path.exists():
            return pd.read_csv(path)
    raise FileNotFoundError(f"None of {names} exists in {data_dir}")


def load_organizations_from_csv(data_dir: str | os.PathLike[str]) -> pd.DataFrame:
    """Load organizations with country values joined through state records."""
    root = Path(data_dir)
    organizations = _read_csv(root, ("organizations.csv",))
    states = _read_csv(root, ("states.csv", "state.csv"))
    countries = _read_csv(root, ("countries.csv", "country.csv"))
    states = states[["state_id", "country_id"]].drop_duplicates("state_id")
    country_columns = ["country_id"]
    if "country_code" in countries.columns:
        country_columns.append("country_code")
    if "country_name" in countries.columns:
        country_columns.append("country_name")
    countries = countries[country_columns].drop_duplicates("country_id")
    joined = organizations.merge(states, on="state_id", how="left")
    return joined.merge(countries, on="country_id", how="left")


def _truthy_series(series: pd.Series) -> pd.Series:
    """Convert boolean-like CSV values to a boolean Series."""
    return series.astype(str).str.strip().str.casefold().isin(("true", "1", "yes", "t"))


def _filtered_frame(data: pd.DataFrame, body: dict[str, Any]) -> pd.DataFrame:
    """Apply shared country and organization type filters."""
    filtered = data.copy()
    country = body.get("country")
    if country is not None and str(country).upper() != "ALL":
        target = _normalize_text(country)
        country_matches = pd.Series(False, index=filtered.index)
        for column in ("country_code", "country_name"):
            if column in filtered.columns:
                country_matches |= filtered[column].map(_normalize_text).eq(target)
        filtered = filtered[country_matches]
    organization_type = _normalize_org_type(body.get("organization_type"))
    if organization_type is not None:
        values = filtered["org_type"].map(_normalize_text).str.replace("-", "_", regex=False)
        filtered = filtered[values.isin((organization_type, organization_type.replace("_", "")))]
    return filtered


def _window(data: pd.DataFrame, start: Optional[date], end: Optional[date]) -> pd.DataFrame:
    """Return organizations created in an inclusive date window."""
    dates = pd.to_datetime(data["created_at"], errors="coerce").dt.date
    valid = dates.notna()
    if start is not None:
        valid &= dates >= start
    if end is not None:
        valid &= dates <= end
    return data[valid]


def _size_chart(data: pd.DataFrame) -> list[dict[str, Any]]:
    """Build organization counts grouped by observed organization size."""
    if data.empty or "org_size" not in data.columns:
        return []
    grouped = data.dropna(subset=["org_size"]).groupby("org_size", sort=False).size()
    return [{"size": size, "count": int(count)} for size, count in grouped.items()]


def _contribution_chart(data: pd.DataFrame) -> list[dict[str, Any]]:
    """Build independent collaborator and contributor counts and percentages."""
    total = len(data)
    if total == 0:
        return []
    collaborator = int(_truthy_series(data["is_collaborator"]).sum()) if "is_collaborator" in data else 0
    contributor = int(_truthy_series(data["is_contributor"]).sum()) if "is_contributor" in data else 0

    def row(label: str, count: int) -> dict[str, Any]:
        percentage = round((count / total) * 100, 1) if total else 0.0
        return {"type": label, "count": count, "percentage": percentage}

    return [row("Collaborator", collaborator), row("Contributor", contributor)]


def build_response(data: pd.DataFrame, body: dict[str, Any], today: Optional[date] = None) -> dict[str, Any]:
    """Build the fixed-bucket or Custom-only analytics response."""
    filtered = _filtered_frame(data, body)
    size_range = _parse_date_pair(body, "size_start_date", "size_end_date")
    contribution_range = _parse_date_pair(body, "contribution_start_date", "contribution_end_date")
    if size_range or contribution_range:
        charts = _empty_charts()
        if size_range:
            charts["organizations_by_size"] = _size_chart(_window(filtered, *size_range))
        if contribution_range:
            charts["collaborator_vs_contributor"] = _contribution_chart(_window(filtered, *contribution_range))
        return {"Custom": charts}

    current = today or datetime.now().date()
    ranges: dict[str, tuple[Optional[date], Optional[date]]] = {
        "7D": (current - timedelta(days=6), current),
        "30D": (current - timedelta(days=29), current),
        "1Y": (current - timedelta(days=364), current),
        "All": (None, None),
    }
    response = {}
    for bucket in FIXED_BUCKETS:
        bucket_data = _window(filtered, *ranges[bucket])
        response[bucket] = {
            "organizations_by_size": _size_chart(bucket_data),
            "collaborator_vs_contributor": _contribution_chart(bucket_data),
        }
    response["Custom"] = _empty_charts()
    return response


def _db_connection():
    """Create a PostgreSQL connection from environment variables."""
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required for database mode")
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        database=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def load_organizations_from_db() -> pd.DataFrame:
    """Load organizations and country fields from PostgreSQL."""
    connection = _db_connection()
    try:
        query = """
            SELECT o.*, c.country_code, c.country_name
            FROM organizations o
            LEFT JOIN states s ON o.state_id = s.state_id
            LEFT JOIN countries c ON s.country_id = c.country_id
        """
        return pd.read_sql_query(query, connection)
    finally:
        connection.close()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle an Organization Analytics Size and Contribution request."""
    try:
        body = _parse_body(event)
        _normalize_org_type(body.get("organization_type"))
        _parse_date_pair(body, "size_start_date", "size_end_date")
        _parse_date_pair(body, "contribution_start_date", "contribution_end_date")
        if os.getenv("USE_MOCK_DATA", "true").lower() == "true":
            data = load_organizations_from_csv(os.getenv("MOCK_DATA_DIR", "."))
        else:
            data = load_organizations_from_db()
        return _response(200, build_response(data, body))
    except (ValueError, json.JSONDecodeError) as error:
        return _response(400, {"error": str(error)})
    except Exception as error:
        return _response(500, {"error": str(error)})


if __name__ == "__main__":
    print(json.dumps(json.loads(lambda_handler({}, None)["body"]), indent=2))