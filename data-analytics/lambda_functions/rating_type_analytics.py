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

logger = logging.getLogger(__name__)


def parse_range(payload, prefix):
    keys = (f"{prefix}_start_date", f"{prefix}_end_date")
    if not any(key in payload for key in keys):
        return None
    dates = []
    for key in keys:
        value = payload.get(key)
        try:
            if not isinstance(value, str):
                raise TypeError
            parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if parsed.date().isoformat() != value:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key} must be a valid YYYY-MM-DD date") from exc
        dates.append(parsed)
    if dates[0] > dates[1]:
        raise ValueError(f"{keys[0]} must not be after {keys[1]}")
    try:
        return pd.Timestamp(dates[0]), pd.Timestamp(dates[1] + timedelta(days=1))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{keys[1]} is outside the supported date range") from exc


def parse_request(event):
    if not isinstance(event, dict):
        raise TypeError("Request must be a JSON object")
    payload = event.get("body", event)
    if payload is None or payload == "":
        payload = {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise TypeError("Request body must be a JSON object")
    allowed = {
        "country",
        "rating_start_date",
        "rating_end_date",
        "type_start_date",
        "type_end_date",
    }
    if set(payload) - allowed:
        raise ValueError("Unsupported filter in request")
    country = payload.get("country", "ALL")
    if not isinstance(country, str) or not country.strip():
        raise ValueError("country must be a non-empty country name, code, or ALL")
    return (
        country.strip().casefold(),
        parse_range(payload, "rating"),
        parse_range(payload, "type"),
    )


def load_tables():
    mode = os.environ.get("USE_MOCK_DATA", "true").lower()
    if mode == "true":
        directory = os.environ.get(
            "MOCK_DATA_DIR", os.path.join(os.path.dirname(__file__), "mock_data")
        )
        return tuple(
            pd.read_csv(os.path.join(directory, f"{name}.csv"), dtype="string")
            for name in ("organizations", "states", "countries")
        )
    if mode != "false":
        raise ValueError("USE_MOCK_DATA must be true or false")
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required when USE_MOCK_DATA=false")
    schema = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")
    tables = (
        (
            os.environ.get("DB_ORGANIZATIONS_TABLE", "organizations"),
            "org_id, org_rating, org_type, state_id, created_at",
        ),
        (os.environ.get("DB_STATES_TABLE", "state"), "state_id, country_id"),
        (os.environ.get("DB_COUNTRIES_TABLE", "country"), "*"),
    )
    connection = psycopg2.connect(
        os.environ.get("DATABASE_URL", ""),
        connect_timeout=10,
        sslmode=os.environ.get("PGSSLMODE", "require"),
    )
    try:
        connection.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with connection.cursor() as cursor:
            frames = []
            for table, columns in tables:
                query = sql.SQL("SELECT {} FROM {}.{}").format(
                    sql.SQL(columns), sql.Identifier(schema), sql.Identifier(table)
                )
                cursor.execute(query)
                frames.append(
                    pd.DataFrame(
                        cursor.fetchall(),
                        columns=[column[0] for column in cursor.description],
                    )
                )
            return tuple(frames)
    finally:
        connection.close()


def load_data():
    organizations, states, countries = load_tables()
    organizations = organizations[
        ["org_id", "org_rating", "org_type", "state_id", "created_at"]
    ].copy()
    states = states[["state_id", "country_id"]].copy()
    country_columns = [
        column
        for column in ("country_code", "country_name")
        if column in countries.columns
    ]
    if not country_columns:
        raise ValueError("Country data must contain country_code or country_name")
    countries = countries[["country_id", *country_columns]].copy()
    for frame, keys in (
        (organizations, ("state_id",)),
        (states, ("state_id", "country_id")),
        (countries, ("country_id",)),
    ):
        for key in keys:
            frame[key] = frame[key].astype("string").str.strip()
    if organizations.org_id.isna().any() or organizations.org_id.duplicated().any():
        raise ValueError("Organization IDs must be present and unique")
    organizations["created_at"] = pd.to_datetime(
        organizations.created_at, format="ISO8601", utc=True
    )
    organizations["org_rating"] = pd.to_numeric(organizations.org_rating)
    organizations["org_type"] = (
        organizations.org_type.astype("string")
        .str.strip()
        .str.lower()
        .str.replace("-", "_", regex=False)
    )
    if organizations.created_at.isna().any():
        raise ValueError("Organizations must have valid creation dates")
    if not organizations.org_rating.isin([1, 2, 3, 4, 5]).all():
        raise ValueError("Organization ratings must be integers from 1 to 5")
    if not organizations.org_type.isin(["non_profit", "for_profit"]).all():
        raise ValueError("Organization types must be non_profit or for_profit")
    organizations["org_rating"] = organizations.org_rating.astype(int)
    for frame, key in ((states, "state_id"), (countries, "country_id")):
        if frame[key].isna().any():
            raise ValueError(f"{key} lookup keys must be present")
    return organizations.merge(
        states, on="state_id", how="left", validate="many_to_one"
    ).merge(countries, on="country_id", how="left", validate="many_to_one")


def select_window(data, window):
    if window is None:
        return data
    start, end = window
    return data.loc[(data.created_at >= start) & (data.created_at < end)]


def rating_distribution(data):
    return [
        {"rating": int(rating), "count": int(count)}
        for rating, count in data.groupby("org_rating", sort=True).size().items()
    ]


def organization_mix_trend(data, window, monthly=False):
    selected = select_window(data, window)
    if window is not None:
        data = data.loc[data.created_at < window[1]]
    result = {}
    period_format = "%Y-%m" if monthly else "%Y-%m-%d"
    for org_type in ("non_profit", "for_profit"):
        history = data.loc[data.org_type == org_type, "created_at"]
        activity = selected.loc[selected.org_type == org_type, "created_at"]
        cumulative = (
            history.dt.strftime(period_format).value_counts().sort_index().cumsum()
        )
        periods = sorted(activity.dt.strftime(period_format).unique())
        result[org_type] = [
            {"period": period, "count": int(cumulative.loc[period])}
            for period in periods
        ]
    return result


def empty_bucket():
    return {
        "rating_distribution": [],
        "organization_mix_trend": {"non_profit": [], "for_profit": []},
    }


def build_analytics(
    data, country="all", rating_range=None, type_range=None, today=None
):
    if country != "all":
        matches = pd.Series(False, index=data.index)
        for column in ("country_code", "country_name"):
            if column in data.columns:
                matches |= (
                    data[column]
                    .astype("string")
                    .str.strip()
                    .str.casefold()
                    .eq(country)
                    .fillna(False)
                )
        data = data.loc[matches]
    if rating_range is not None or type_range is not None:
        custom = empty_bucket()
        if rating_range is not None:
            custom["rating_distribution"] = rating_distribution(
                select_window(data, rating_range)
            )
        if type_range is not None:
            custom["organization_mix_trend"] = organization_mix_trend(data, type_range)
        return {"Custom": custom}
    today = pd.Timestamp.now(tz="UTC") if today is None else pd.Timestamp(today)
    today = (
        today.tz_localize("UTC") if today.tzinfo is None else today.tz_convert("UTC")
    )
    end = today.normalize() + pd.Timedelta(days=1)
    windows = {
        "7D": (end - pd.Timedelta(days=7), end),
        "30D": (end - pd.Timedelta(days=30), end),
        "1Y": (end - pd.DateOffset(years=1), end),
        "All": None,
    }
    result = {
        key: {
            "rating_distribution": rating_distribution(select_window(data, window)),
            "organization_mix_trend": organization_mix_trend(
                data, window, monthly=key in ("1Y", "All")
            ),
        }
        for key, window in windows.items()
    }
    result["Custom"] = empty_bucket()
    return result


def response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    try:
        country, rating_range, type_range = parse_request(event)
    except (TypeError, ValueError, OverflowError) as exc:
        return response(400, {"error": str(exc)})
    try:
        return response(
            200, build_analytics(load_data(), country, rating_range, type_range)
        )
    except Exception:
        logger.exception("Unable to compute rating and type analytics")
        return response(500, {"error": "Unable to load analytics data"})


if __name__ == "__main__":
    rating = {"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"}
    org_type = {"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"}
    for sample in ({}, {"country": "USA"}, rating, org_type, {**rating, **org_type}):
        print(
            json.dumps(
                {"event": sample, "response": lambda_handler(sample, None)}, indent=2
            )
        )
