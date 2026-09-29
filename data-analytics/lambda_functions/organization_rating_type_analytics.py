"""Analytics lambda backing the "Rating & Type" tab of the Organization
Analytics dashboard.

Task 1 scope: mock-data loading (organizations joined up to country) plus the
shared response/shape helpers. Chart aggregation and ``lambda_handler`` are
added by later tasks.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional

import pandas as pd

try:
    import psycopg2
except ImportError:  # psycopg2 is only needed on the real-DB path
    psycopg2 = None

try:
    import boto3
except ImportError:  # boto3 is only needed to read SSM creds for the real DB
    boto3 = None


SCHEMA_NAME = "virginia_dev_saayam_rdbms"

FIXED_BUCKETS = ["7D", "30D", "1Y", "All"]

ORG_TYPES = ["non_profit", "for_profit"]

USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "").strip().lower() == "true"

DEFAULT_MOCK_DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, "sql"
)

MOCK_DATA_DIR = os.environ.get("MOCK_DATA_DIR", DEFAULT_MOCK_DATA_DIR)

ORGANIZATION_COLUMNS = [
    "org_id",
    "org_rating",
    "org_type",
    "created_at",
    "country_code",
    "country_name",
]


def build_response(status_code: int, body: Any) -> Dict[str, Any]:
    """Build an API Gateway proxy response with a JSON-serialized body."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=str)
    }


def empty_chart_payload() -> Dict[str, Any]:
    """Return a fresh, empty payload for one time bucket."""
    return {
        "rating_distribution": [],
        "organization_mix_trend": {"non_profit": [], "for_profit": []}
    }


def normalize_org_type(value: Any) -> Optional[str]:
    """Normalize a raw organization type to "non_profit" / "for_profit".

    Handles the mock-data spellings ("Non-Profit", "For-profit") as well as
    variants that differ only by case, whitespace, hyphens or underscores.
    Returns ``None`` for missing or unrecognized values.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    collapsed = re.sub(r"[\s_-]+", "", str(value).strip().lower())

    if collapsed == "nonprofit":
        return "non_profit"
    if collapsed == "forprofit":
        return "for_profit"
    return None


def _read_csv_any(directory: str, candidates: List[str], **kwargs: Any) -> pd.DataFrame:
    """Read the first CSV among ``candidates`` that exists in ``directory``.

    Raises ``FileNotFoundError`` naming every candidate that was tried when
    none of them exist.
    """
    for name in candidates:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            return pd.read_csv(path, **kwargs)

    tried = ", ".join(candidates)
    raise FileNotFoundError(
        f"None of the expected mock CSV files were found in '{directory}'. Tried: {tried}"
    )


def _empty_organizations_frame() -> pd.DataFrame:
    """Return an empty organizations DataFrame with the canonical columns."""
    empty = pd.DataFrame(columns=ORGANIZATION_COLUMNS)
    empty["org_rating"] = empty["org_rating"].astype("Int64")
    empty["created_at"] = pd.to_datetime(empty["created_at"], errors="coerce")
    return empty


def _clean_key(series: pd.Series) -> pd.Series:
    """Coerce a join key to a stripped string series so "1" and 1 match."""
    return series.astype(str).str.strip()


def load_mock_organizations(mock_dir: Optional[str] = None) -> pd.DataFrame:
    """Load organizations from the mock CSVs, joined out to their country.

    Organizations are LEFT joined to states and then to countries, so rows
    with an unknown state or country are kept with null country fields.
    Ratings are kept only when they are whole numbers in 1..5; rows whose
    ``created_at`` cannot be parsed are dropped.
    """
    directory = mock_dir or MOCK_DATA_DIR

    organizations = _read_csv_any(directory, ["organizations.csv"], dtype=str)
    states = _read_csv_any(directory, ["states.csv", "state.csv"], dtype=str)
    countries = _read_csv_any(directory, ["countries.csv", "country.csv"], dtype=str)

    if organizations.empty:
        return _empty_organizations_frame()

    orgs = organizations.copy()
    orgs["state_id"] = _clean_key(orgs.get("state_id", pd.Series(dtype=str)))

    states = states[["state_id", "country_id"]].copy()
    states["state_id"] = _clean_key(states["state_id"])
    states["country_id"] = _clean_key(states["country_id"])

    countries = countries[["country_id", "country_code", "country_name"]].copy()
    countries["country_id"] = _clean_key(countries["country_id"])

    merged = orgs.merge(states, on="state_id", how="left")
    merged = merged.merge(countries, on="country_id", how="left")

    result = pd.DataFrame({
        "org_id": merged["org_id"].astype(str).str.strip(),
        "org_rating": pd.to_numeric(merged["org_rating"], errors="coerce"),
        "org_type": merged["org_type"].map(normalize_org_type),
        "created_at": pd.to_datetime(merged["created_at"], errors="coerce"),
        "country_code": merged["country_code"],
        "country_name": merged["country_name"]
    })

    ratings = result["org_rating"]
    valid_rating = ratings.notna() & (ratings % 1 == 0) & ratings.between(1, 5)
    result["org_rating"] = ratings.where(valid_rating).astype("Int64")

    result = result[result["created_at"].notna()].reset_index(drop=True)

    if result.empty:
        return _empty_organizations_frame()

    return result[ORGANIZATION_COLUMNS]


def _normalize_country_token(value: Any) -> str:
    """Lowercase a country code/name and treat "_" and " " as equivalent."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"[\s_]+", " ", str(value).strip().lower())


def apply_country_filter(df: pd.DataFrame, country: Optional[str]) -> pd.DataFrame:
    """Filter organizations by country code or country name.

    ``None``, ``""`` and ``"ALL"`` (any case) leave the frame untouched.
    Matching is case-insensitive and treats underscores and spaces as
    equivalent, so "USA", "usa", "United States of America" and
    "UNITED_STATES_OF_AMERICA" all select the same rows. An unrecognized
    country yields an empty DataFrame rather than an error.
    """
    if country is None:
        return df

    wanted = _normalize_country_token(country)
    if wanted in ("", "all"):
        return df

    if df.empty:
        return df

    codes = df["country_code"].map(_normalize_country_token)
    names = df["country_name"].map(_normalize_country_token)

    return df[(codes == wanted) | (names == wanted)]
