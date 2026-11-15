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


_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = (
    os.environ.get("MOCK_DATA_DIR")
    or (os.path.join(_HERE, "mock_data") if os.path.isdir(os.path.join(_HERE, "mock_data")) else None)
    or os.path.join(_HERE, "..", "sql")
)

USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "true").strip().lower() in ("true", "1", "t", "yes")

VALID_TYPES = ("for_profit", "non_profit")


class ValidationError(Exception):
    pass


def _minus_one_year(now):
    try:
        return now.replace(year=now.year - 1)
    except ValueError:
        return now.replace(year=now.year - 1, day=28)


def load_organizations(data_dir=DATA_DIR):
    def find(*names):
        for name in names:
            path = os.path.join(data_dir, name)
            if os.path.exists(path):
                return path
        raise FileNotFoundError(f"None of {names} found in {data_dir}")

    orgs = pd.read_csv(find("organizations.csv"), dtype=str)
    states = pd.read_csv(find("states.csv", "state.csv"), dtype=str)
    countries = pd.read_csv(find("countries.csv", "country.csv"), dtype=str)

    for df in (orgs, states, countries):
        df.columns = [c.strip().lower() for c in df.columns]

    for col in ("org_id", "state_id", "org_rating", "org_type", "created_at"):
        if col not in orgs.columns:
            orgs[col] = pd.Series(dtype="object")

    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce")
    orgs = orgs[orgs["created_at"].notna()].copy()
    orgs["org_rating"] = pd.to_numeric(orgs["org_rating"], errors="coerce").astype("Int64")
    orgs["org_type"] = orgs["org_type"].astype(str).str.strip().str.lower()

    for df, col in ((orgs, "state_id"), (states, "state_id"), (states, "country_id"), (countries, "country_id")):
        df[col] = df[col].astype(str).str.strip()

    orgs = orgs.merge(states[["state_id", "country_id"]], on="state_id", how="left")
    orgs = orgs.merge(countries[["country_id", "country_code"]], on="country_id", how="left")
    orgs["country_code"] = orgs["country_code"].fillna("Unknown")
    return orgs


def build_response(orgs, custom, country=None, now=None):
    now = now or datetime.now()

    if country:
        orgs = orgs[orgs["country_code"] == country]

    def window(start, end):
        w = orgs
        if start is not None:
            w = w[w["created_at"] >= start]
        if end is not None:
            w = w[w["created_at"] <= end]
        return w

    def rating_distribution(start, end):
        ratings = window(start, end)["org_rating"].dropna()
        if ratings.empty:
            return []
        counts = ratings.astype(int).value_counts().sort_index()
        return [{"rating": int(rating), "count": int(count)} for rating, count in counts.items()]

    def organization_mix_trend(start, end, monthly):
        fmt = "%Y-%m" if monthly else "%Y-%m-%d"
        result = {}
        for org_type in VALID_TYPES:
            of_type = orgs[orgs["org_type"] == org_type]
            in_window = window(start, end)
            in_window = in_window[in_window["org_type"] == org_type]
            if in_window.empty:
                result[org_type] = []
                continue
            visible = set(in_window["created_at"].dt.strftime(fmt))

            per_period = of_type["created_at"].dt.strftime(fmt).value_counts().sort_index()
            cumulative = per_period.cumsum()
            result[org_type] = [
                {"period": period, "count": int(count)}
                for period, count in cumulative.items() if period in visible
            ]
        return result

    fixed = {
        "7D": (now - timedelta(days=7), now, False),
        "30D": (now - timedelta(days=30), now, False),
        "1Y": (_minus_one_year(now), now, True),
        "All": (None, None, True),
    }
    response = {
        bucket: {"rating_distribution": rating_distribution(start, end),
                 "organization_mix_trend": organization_mix_trend(start, end, monthly)}
        for bucket, (start, end, monthly) in fixed.items()
    }

    rat_s, rat_e = custom["rat_start"], custom["rat_end"]
    typ_s, typ_e = custom["typ_start"], custom["typ_end"]
    response["Custom"] = {
        "rating_distribution": (rating_distribution(rat_s, rat_e) if rat_s and rat_e else []),
        "organization_mix_trend": (organization_mix_trend(typ_s, typ_e, monthly=False)
                                   if typ_s and typ_e else {t: [] for t in VALID_TYPES}),
    }
    return response


def lambda_handler(event, context=None):
    def valid_range(start, end, sf, ef):
        if start is None and end is None:
            return None, None
        if start is None or end is None:
            raise ValidationError(f"Both '{sf}' and '{ef}' must be provided together.")
        try:
            s, e = datetime.strptime(start, "%Y-%m-%d"), datetime.strptime(end, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise ValidationError(f"Invalid date in '{sf}'/'{ef}'. Expected YYYY-MM-DD.")
        if s > e:
            raise ValidationError(f"'{sf}' ({start}) must not be after '{ef}' ({end}).")
        return s, e

    try:
        event = event or {}
        body = event.get("body")
        if isinstance(body, str):
            body = json.loads(body) if body else {}
        params = dict(body) if isinstance(body, dict) else {}
        for key in ("rating_start_date", "rating_end_date",
                    "type_start_date", "type_end_date", "country"):
            if key in event:
                params[key] = event[key]

        rat_s, rat_e = valid_range(params.get("rating_start_date"), params.get("rating_end_date"),
                                   "rating_start_date", "rating_end_date")
        typ_s, typ_e = valid_range(params.get("type_start_date"), params.get("type_end_date"),
                                   "type_start_date", "type_end_date")
        country = params.get("country") or None

        if USE_MOCK_DATA:
            orgs = load_organizations()
        else:
            orgs = load_organizations_from_db()

        result = build_response(orgs, {
            "rat_start": rat_s, "rat_end": rat_e, "typ_start": typ_s, "typ_end": typ_e,
        }, country=country)
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"},
                "body": json.dumps(result)}
    except (ValidationError, json.JSONDecodeError) as exc:
        message = "Request body is not valid JSON." if isinstance(exc, json.JSONDecodeError) else str(exc)
        return {"statusCode": 400, "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": message})}


def load_organizations_from_db():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed; set USE_MOCK_DATA=true for standalone runs.")

    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        port=os.environ.get("DB_PORT", "5432"),
    )
    try:
        query = """
            SELECT o.org_id,
                   o.org_rating,
                   LOWER(o.org_type) AS org_type,
                   o.created_at,
                   COALESCE(c.country_code, 'Unknown') AS country_code
            FROM organizations o
            LEFT JOIN states s    ON o.state_id = s.state_id
            LEFT JOIN countries c ON s.country_id = c.country_id
        """
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
    finally:
        conn.close()

    orgs = pd.DataFrame(rows, columns=["org_id", "org_rating", "org_type", "created_at", "country_code"])
    orgs["created_at"] = pd.to_datetime(orgs["created_at"], errors="coerce")
    orgs = orgs[orgs["created_at"].notna()].copy()
    orgs["org_rating"] = pd.to_numeric(orgs["org_rating"], errors="coerce").astype("Int64")
    orgs["org_type"] = orgs["org_type"].astype(str).str.strip().str.lower()
    orgs["country_code"] = orgs["country_code"].fillna("Unknown")
    return orgs


if __name__ == "__main__":
    scenarios = {
        "no body": {},
        "rating custom only": {"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30"},
        "type custom only": {"type_start_date": "2026-01-01", "type_end_date": "2026-06-30"},
        "both ranges": {"rating_start_date": "2026-01-01", "rating_end_date": "2026-06-30",
                        "type_start_date": "2025-01-01", "type_end_date": "2025-12-31"},
        "country filter": {"country": "USA"},
        "bad date format": {"rating_start_date": "01-01-2026", "rating_end_date": "2026-06-30"},
        "start after end": {"type_start_date": "2026-06-30", "type_end_date": "2026-01-01"},
    }
    print(f"Data dir: {DATA_DIR}  (USE_MOCK_DATA={USE_MOCK_DATA})")
    for label, event in scenarios.items():
        resp = lambda_handler(event)
        print(f"\n--- {label} (HTTP {resp['statusCode']}) ---")
        print(json.dumps(json.loads(resp["body"]), indent=2))
