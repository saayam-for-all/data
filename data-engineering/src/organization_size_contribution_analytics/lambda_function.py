"""Build the Organization Analytics Size and Contribution dashboard data (#583).

Returns two charts: organizations_by_size and collaborator_vs_contributor.
With no dates the response has 7D/30D/1Y/All and no Custom key.
If start_date and end_date are sent (YYYY-MM-DD, both inclusive), only Custom
is returned, and that one range is used for both charts.
The country and organization_type filters apply to both charts in every case.

Data comes from organizations.csv, states.csv and countries.csv in the
mock_data folder next to this file. No environment variables are needed.
"""

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

MOCK_DATA_DIR = Path(__file__).resolve().parent / "mock_data"

FIXED_BUCKETS = ("7D", "30D", "1Y", "All")
ORG_TYPE_ALIASES = {
    "non_profit": "non_profit",
    "nonprofit": "non_profit",
    "non-profit": "non_profit",
    "for_profit": "for_profit",
    "forprofit": "for_profit",
    "for-profit": "for_profit",
}


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


def _is_blank(value: Any) -> bool:
    """A null or empty/whitespace string counts as not supplied."""
    return value is None or (isinstance(value, str) and not value.strip())


def _parse_date_pair(body: dict[str, Any], start_key: str, end_key: str) -> Optional[tuple[date, date]]:
    """Validate and parse the one optional inclusive Custom date range."""
    start_value, end_value = body.get(start_key), body.get(end_key)
    start_blank, end_blank = _is_blank(start_value), _is_blank(end_value)
    if start_blank and end_blank:
        return None
    if start_blank or end_blank:
        raise ValueError(f"{start_key} and {end_key} must be supplied together")
    try:
        start = date.fromisoformat(str(start_value))
        end = date.fromisoformat(str(end_value))
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


def load_organizations_from_csv(data_dir: str | os.PathLike[str] = MOCK_DATA_DIR) -> pd.DataFrame:
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


def _charts(data: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Build both charts from one window, so they share the same organizations."""
    return {
        "organizations_by_size": _size_chart(data),
        "collaborator_vs_contributor": _contribution_chart(data),
    }


def build_response(data: pd.DataFrame, body: dict[str, Any], today: Optional[date] = None) -> dict[str, Any]:
    """Build the fixed-bucket or Custom-only analytics response."""
    filtered = _filtered_frame(data, body)
    custom_range = _parse_date_pair(body, "start_date", "end_date")
    if custom_range is not None:
        # dates sent: one range drives both charts, and only Custom comes back
        return {"Custom": _charts(_window(filtered, *custom_range))}

    current = today or datetime.now().date()
    ranges: dict[str, tuple[Optional[date], Optional[date]]] = {
        "7D": (current - timedelta(days=6), current),
        "30D": (current - timedelta(days=29), current),
        "1Y": (current - timedelta(days=364), current),
        "All": (None, None),
    }
    return {bucket: _charts(_window(filtered, *ranges[bucket])) for bucket in FIXED_BUCKETS}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle an Organization Analytics Size and Contribution request."""
    try:
        body = _parse_body(event)
        # validated first so bad input is a 400 and never touches the filesystem
        _normalize_org_type(body.get("organization_type"))
        _parse_date_pair(body, "start_date", "end_date")
        data = load_organizations_from_csv()
        return _response(200, build_response(data, body))
    except (ValueError, json.JSONDecodeError) as error:
        return _response(400, {"error": str(error)})
    except Exception as error:
        return _response(500, {"error": str(error)})