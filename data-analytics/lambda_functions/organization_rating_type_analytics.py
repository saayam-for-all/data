import json
import os
from datetime import datetime, timedelta

import pandas as pd

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "false").lower() == "true"
MOCK_DATA_DIR = os.environ.get("MOCK_DATA_DIR", ".")

ORGS_FILE = "organizations.csv"
STATES_FILE = "states.csv"
COUNTRIES_FILE = "countries.csv"

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
ORG_TABLE = "organizations"
STATE_TABLE = "state"
COUNTRY_TABLE = "country"

DATA_COLUMNS = [
    "org_id", "org_rating", "org_type", "state_id",
    "created_at", "country_name", "country_code",
]


def normalize_orgs(df):
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["org_type"] = (
        df["org_type"].astype(str).str.strip().str.lower().str.replace("-", "_")
    )
    return df


def load_mock_data():
    orgs = pd.read_csv(
        os.path.join(MOCK_DATA_DIR, ORGS_FILE),
        usecols=["org_id", "org_rating", "org_type", "state_id", "created_at"],
    )
    states = pd.read_csv(
        os.path.join(MOCK_DATA_DIR, STATES_FILE),
        usecols=["state_id", "country_id"],
    )
    countries = pd.read_csv(
        os.path.join(MOCK_DATA_DIR, COUNTRIES_FILE),
        usecols=["country_id", "country_name", "country_code"],
    )

    orgs = normalize_orgs(orgs)

    df = orgs.merge(states, on="state_id", how="left")
    df = df.merge(countries, on="country_id", how="left")
    return df


def get_db_connection():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed.")
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        database=os.environ.get("DB_NAME", "saayam_local"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
        port=os.environ.get("DB_PORT", "5432"),
    )


def load_db_data():
    query = f"""
        SELECT o.org_id, o.org_rating, o.org_type, o.state_id, o.created_at,
               c.country_name, c.country_code
        FROM {SCHEMA_NAME}.{ORG_TABLE} o
        LEFT JOIN {SCHEMA_NAME}.{STATE_TABLE} s ON o.state_id = s.state_id
        LEFT JOIN {SCHEMA_NAME}.{COUNTRY_TABLE} c ON s.country_id = c.country_id;
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    return normalize_orgs(pd.DataFrame(rows, columns=DATA_COLUMNS))


def load_data():
    if USE_MOCK_DATA:
        return load_mock_data()
    return load_db_data()


def filter_by_country(df, country):
    if not country or str(country).strip().upper() == "ALL":
        return df

    target = str(country).strip().upper().replace("_", " ")
    names = (
        df["country_name"].fillna("").astype(str).str.upper().str.replace("_", " ", regex=False)
    )
    codes = df["country_code"].fillna("").astype(str).str.upper()
    return df[(names == target) | (codes == target)]


def parse_date_pair(body, start_key, end_key):
    start_raw = body.get(start_key)
    end_raw = body.get(end_key)

    if start_raw in (None, "") and end_raw in (None, ""):
        return None

    if start_raw in (None, "") or end_raw in (None, ""):
        raise ValueError(f"{start_key} and {end_key} must be supplied together.")

    try:
        start = datetime.strptime(str(start_raw).strip(), "%Y-%m-%d")
        end = datetime.strptime(str(end_raw).strip(), "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{start_key} and {end_key} must be real dates in YYYY-MM-DD format.")

    if start > end:
        raise ValueError(f"{start_key} must not be after {end_key}.")

    return start, end + timedelta(days=1)


def build_rating_distribution(df, start=None, end=None):
    if start is not None:
        df = df[df["created_at"] >= start]
    if end is not None:
        df = df[df["created_at"] < end]

    ratings = pd.to_numeric(df["org_rating"], errors="coerce").dropna().astype(int)
    ratings = ratings[(ratings >= 1) & (ratings <= 5)]
    counts = ratings.value_counts().sort_index()

    return [{"rating": int(r), "count": int(c)} for r, c in counts.items()]


def build_mix_trend(df, start=None, end=None, group="day"):
    if start is not None:
        df = df[df["created_at"] >= start]
    if end is not None:
        df = df[df["created_at"] < end]
    df = df.dropna(subset=["created_at"])

    fmt = "%Y-%m-%d" if group == "day" else "%Y-%m"
    result = {"non_profit": [], "for_profit": []}

    for org_type in result:
        sub = df[df["org_type"] == org_type]
        if sub.empty:
            continue
        periods = sub["created_at"].dt.strftime(fmt)
        counts = periods.value_counts().sort_index().cumsum()
        result[org_type] = [
            {"period": p, "count": int(c)} for p, c in counts.items()
        ]

    return result


def get_today():
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def empty_chart():
    return {
        "rating_distribution": [],
        "organization_mix_trend": {"non_profit": [], "for_profit": []},
    }


def build_analytics(df, rating_range, type_range):
    if rating_range is None and type_range is None:
        today = get_today()
        windows = {
            "7D": (today - timedelta(days=7), "day"),
            "30D": (today - timedelta(days=30), "day"),
            "1Y": (today - pd.DateOffset(years=1), "month"),
            "All": (None, "month"),
        }
        response = {}
        for name, (start, group) in windows.items():
            response[name] = {
                "rating_distribution": build_rating_distribution(df, start, None),
                "organization_mix_trend": build_mix_trend(df, start, None, group),
            }
        response["Custom"] = empty_chart()
        return response

    custom = empty_chart()
    if rating_range is not None:
        custom["rating_distribution"] = build_rating_distribution(df, *rating_range)
    if type_range is not None:
        custom["organization_mix_trend"] = build_mix_trend(df, *type_range, group="day")
    return {"Custom": custom}


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def parse_event_body(event):
    if not isinstance(event, dict):
        return {}
    if "body" not in event:
        return event

    raw = event["body"]
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw

    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("Request body must be valid JSON.")
    if not isinstance(parsed, dict):
        raise ValueError("Request body must be a JSON object.")
    return parsed


def lambda_handler(event, context):
    try:
        body = parse_event_body(event)
        country = body.get("country", "ALL")
        rating_range = parse_date_pair(body, "rating_start_date", "rating_end_date")
        type_range = parse_date_pair(body, "type_start_date", "type_end_date")
    except ValueError as e:
        return build_response(400, {"error": str(e)})

    try:
        df = load_data()
        df = filter_by_country(df, country)
        return build_response(200, build_analytics(df, rating_range, type_range))
    except Exception as e:
        print(f"organization_rating_type_analytics failed: {e}")
        return build_response(500, {"error": "Internal error while building analytics."})


if __name__ == "__main__":
    events = [
        ("no body", {}),
        ("country US", {"country": "US"}),
        ("rating only", {"rating_start_date": "2025-01-01", "rating_end_date": "2025-12-31"}),
        ("type only", {"type_start_date": "2025-01-01", "type_end_date": "2025-12-31"}),
        ("both", {
            "rating_start_date": "2025-01-01", "rating_end_date": "2025-12-31",
            "type_start_date": "2025-01-01", "type_end_date": "2025-12-31",
        }),
        ("half pair", {"rating_start_date": "2025-01-01"}),
        ("bad date", {"type_start_date": "2025/01/01", "type_end_date": "2025-12-31"}),
        ("start after end", {"type_start_date": "2025-12-31", "type_end_date": "2025-01-01"}),
        ("string body", {"body": '{"country": "US"}'}),
        ("broken json", {"body": "{oops"}),
    ]
    for label, ev in events:
        print(f"=== {label}: {json.dumps(ev)}")
        res = lambda_handler(ev, None)
        print("status:", res["statusCode"])
        print(json.dumps(json.loads(res["body"]), indent=2))