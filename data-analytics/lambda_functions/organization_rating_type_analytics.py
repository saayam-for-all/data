"""Rating Distribution and Profit vs Non-Profit organization analytics."""

import json
import os
import re
from datetime import datetime, timedelta

import pandas as pd

try:
    import psycopg2
except ImportError:  # Optional for local CSV testing.
    psycopg2 = None

SCHEMA = os.environ.get("SAAYAM_SCHEMA", "virginia_dev_saayam_rdbms")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", SCHEMA):
    raise ValueError("SAAYAM_SCHEMA must be a valid SQL schema identifier")

FIXED_WINDOWS = ("7D", "30D", "1Y", "All")
ORG_TYPES = ("non_profit", "for_profit")
FRAME_COLUMNS = ("org_rating", "org_type", "created_at", "country_code", "country_name")
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mock-data-generation")


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body),
    }


def parse_event_body(event):
    if not event:
        return {}
    if not isinstance(event, dict):
        raise ValueError("request must be a JSON object")
    if "body" not in event:
        return event
    body = event["body"]
    if body is None or body == "":
        return event.get("queryStringParameters") or {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("request body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return body


def as_token(value):
    return str(value).strip().upper().replace("-", "_").replace(" ", "_")


def read_country(params):
    country = params.get("country") or "ALL"
    if not isinstance(country, str):
        raise ValueError("country must be a string")
    return as_token(country)


def read_custom_range(params, start_key, end_key):
    """Return a [start, end-exclusive) range; custom end dates are inclusive."""
    start = params.get(start_key)
    end = params.get(end_key)
    if not start and not end:
        return None
    if not start or not end:
        raise ValueError(f"{start_key} and {end_key} have to be sent together")
    try:
        first = datetime.strptime(start, "%Y-%m-%d")
        last = datetime.strptime(end, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValueError(f"{start_key} and {end_key} must be in YYYY-MM-DD format")
    if first > last:
        raise ValueError(f"{start_key} cannot be after {end_key}")
    return pd.Timestamp(first), pd.Timestamp(last) + timedelta(days=1)


def fixed_range(name, today):
    tomorrow = today + pd.Timedelta(days=1)
    days = {"7D": 7, "30D": 30, "1Y": 365}.get(name)
    if days is None:
        return None, None
    return tomorrow - pd.Timedelta(days=days), tomorrow


def tidy(frame):
    frame = frame.copy()
    for column in FRAME_COLUMNS:
        if column not in frame.columns:
            frame[column] = None
    frame["org_rating"] = pd.to_numeric(frame["org_rating"], errors="coerce")
    created = pd.to_datetime(frame["created_at"], errors="coerce", utc=True)
    frame["created_at"] = created.dt.tz_localize(None)
    frame["org_type"] = frame["org_type"].fillna("").map(as_token).str.lower()
    frame["country_code"] = frame["country_code"].fillna("").map(as_token)
    frame["country_name"] = frame["country_name"].fillna("").map(as_token)
    return frame.dropna(subset=["created_at"])[list(FRAME_COLUMNS)]


def read_csv(folder, name):
    try:
        return pd.read_csv(
            os.path.join(folder, name),
            dtype={"state_id": str, "country_id": str},
            keep_default_na=False,
            na_values=[""],
        )
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def load_from_csv(country):
    folder = os.environ.get("MOCK_DATA_DIR", DEFAULT_DATA_DIR)
    orgs = read_csv(folder, "organizations.csv")
    if orgs.empty:
        return tidy(pd.DataFrame(columns=FRAME_COLUMNS))
    required = {"org_rating", "org_type", "state_id", "created_at"}
    missing = required.difference(orgs.columns)
    if missing:
        raise ValueError(f"organizations.csv is missing columns: {', '.join(sorted(missing))}")

    states = read_csv(folder, "states.csv")
    countries = read_csv(folder, "countries.csv")
    for label, frame, columns in (
        ("states.csv", states, {"state_id", "country_id"}),
        ("countries.csv", countries, {"country_id"}),
    ):
        missing = columns.difference(frame.columns)
        if missing:
            raise ValueError(f"{label} is missing columns: {', '.join(sorted(missing))}")
    if not {"country_code", "country_name"}.intersection(countries.columns):
        raise ValueError("countries.csv must include country_code or country_name")
    if "country_code" not in countries.columns:
        countries["country_code"] = ""
    if "country_name" not in countries.columns:
        countries["country_name"] = ""

    states = states[["state_id", "country_id"]].drop_duplicates("state_id")
    countries = countries[["country_id", "country_code", "country_name"]]
    orgs["state_id"] = orgs["state_id"].astype(str)
    orgs = orgs.merge(states, on="state_id", how="left").merge(countries, on="country_id", how="left")
    orgs = tidy(orgs)
    if country != "ALL":
        orgs = orgs[(orgs["country_code"] == country) | (orgs["country_name"] == country)]
    return orgs


def load_from_db(country):
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed; set USE_MOCK_DATA=true to use local CSV files")

    conditions, args = [], []
    if country != "ALL":
        conditions.append(
            "(UPPER(c.country_code::text) = %s "
            "OR UPPER(REPLACE(REPLACE(c.country_name::text, ' ', '_'), '-', '_')) = %s)"
        )
        args.extend((country, country))
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    query = f"""
        SELECT o.org_rating, o.org_type::text AS org_type, o.created_at,
               c.country_code::text AS country_code, c.country_name::text AS country_name
        FROM {SCHEMA}.organizations o
        LEFT JOIN {SCHEMA}.states s ON s.state_id = o.state_id
        LEFT JOIN {SCHEMA}.countries c ON c.country_id = s.country_id
        {where}
    """
    conn = psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ.get("PGPORT", 5432),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )
    try:
        with conn.cursor() as cur:
            cur.execute(query, args)
            names = [description[0] for description in cur.description]
            return tidy(pd.DataFrame(cur.fetchall(), columns=names))
    finally:
        conn.close()


def load_orgs(country):
    if os.environ.get("USE_MOCK_DATA", "false").strip().lower() == "true":
        return load_from_csv(country)
    return load_from_db(country)


def in_window(frame, start, end):
    if start is not None:
        frame = frame[frame["created_at"] >= start]
    if end is not None:
        frame = frame[frame["created_at"] < end]
    return frame


def rating_distribution(orgs):
    if orgs.empty:
        return []
    ratings = orgs["org_rating"].dropna()
    if ratings.empty:
        return []
    counts = ratings.value_counts().sort_index()
    return [{"rating": int(rating), "count": int(count)} for rating, count in counts.items()]


def organization_mix_trend(all_orgs, window_orgs, bucket):
    if window_orgs.empty:
        return {"non_profit": [], "for_profit": []}
    period_format = "%Y-%m-%d" if bucket in ("7D", "30D", "Custom") else "%Y-%m"
    window = window_orgs.copy()
    window["period"] = window["created_at"].dt.strftime(period_format)
    result = {}
    for org_type in ORG_TYPES:
        periods = window.loc[window["org_type"] == org_type, "period"].value_counts().sort_index()
        series = []
        for period in periods.index:
            if period_format == "%Y-%m-%d":
                period_end = pd.Timestamp(period) + pd.Timedelta(days=1)
            else:
                period_end = pd.Timestamp(period) + pd.offsets.MonthBegin(1)
            cumulative_count = int(((all_orgs["org_type"] == org_type) & (all_orgs["created_at"] < period_end)).sum())
            series.append({"period": period, "count": cumulative_count})
        result[org_type] = series
    return result


def empty_charts():
    return {"rating_distribution": [], "organization_mix_trend": {"non_profit": [], "for_profit": []}}


def lambda_handler(event, context):
    try:
        params = parse_event_body(event)
        country = read_country(params)
        rating_range = read_custom_range(params, "rating_start_date", "rating_end_date")
        type_range = read_custom_range(params, "type_start_date", "type_end_date")
    except ValueError as exc:
        return build_response(400, {"error": str(exc)})

    try:
        orgs = load_orgs(country)
        if rating_range or type_range:
            custom = empty_charts()
            if rating_range:
                custom["rating_distribution"] = rating_distribution(in_window(orgs, *rating_range))
            if type_range:
                custom["organization_mix_trend"] = organization_mix_trend(
                    orgs, in_window(orgs, *type_range), "Custom"
                )
            return build_response(200, {"Custom": custom})

        today = pd.Timestamp.now().normalize()
        result = {}
        for name in FIXED_WINDOWS:
            start, end = fixed_range(name, today)
            window = in_window(orgs, start, end)
            result[name] = {
                "rating_distribution": rating_distribution(window),
                "organization_mix_trend": organization_mix_trend(orgs, window, name),
            }
        result["Custom"] = empty_charts()
        return build_response(200, result)
    except Exception as exc:
        print(f"rating/type analytics failed: {exc}")
        return build_response(500, {"error": "could not build rating and type analytics"})


def show(label, event):
    print(f"--- {label} ---")
    response = lambda_handler(event, None)
    print("status:", response["statusCode"])
    print(json.dumps(json.loads(response["body"]), indent=2))
    print()
    return response


if __name__ == "__main__":
    os.environ.setdefault("USE_MOCK_DATA", "true")
    show("no body", {})
    show("country filter", {"body": json.dumps({"country": "USA"})})
    show("rating range only", {"body": json.dumps({"rating_start_date": "2025-01-01", "rating_end_date": "2025-06-30"})})
    show("type range only", {"body": json.dumps({"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"})})
    show("both custom ranges", {"body": json.dumps({
        "rating_start_date": "2025-01-01", "rating_end_date": "2025-06-30",
        "type_start_date": "2025-01-01", "type_end_date": "2025-12-31",
    })})
