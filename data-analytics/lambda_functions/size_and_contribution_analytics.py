import json
import os
from datetime import datetime, timedelta

import pandas as pd

try:
    import psycopg2
except ImportError:
    # not needed when running on the mock csvs
    psycopg2 = None

SCHEMA = os.environ.get("SAAYAM_SCHEMA", "virginia_dev_saayam_rdbms")

# csvs are only used for local testing, they are not part of the PR
DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mock-data-generation")

FIXED_WINDOWS = ["7D", "30D", "1Y", "All"]
ORG_TYPES = ("non_profit", "for_profit")
FRAME_COLUMNS = ["org_size", "org_type", "is_collaborator", "is_contributor",
                 "created_at", "country_code", "country_name"]


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }


def parse_event_body(event):
    if not event:
        return {}
    if "body" not in event:
        # direct invoke, the event itself is the filter dict
        return event
    body = event["body"]
    if body is None or body == "":
        # GET through api gateway sends filters as query params instead
        return event.get("queryStringParameters") or {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            raise ValueError("request body is not valid JSON")
    if not isinstance(body, dict):
        raise ValueError("request body must be a JSON object")
    return body


def as_token(value):
    # "Non-Profit", "non profit" and "NON_PROFIT" should all mean the same thing
    return str(value).strip().upper().replace("-", "_").replace(" ", "_")


def read_filters(params):
    country = params.get("country") or "ALL"
    org_type = params.get("organization_type") or "ALL"
    if not isinstance(country, str) or not isinstance(org_type, str):
        raise ValueError("country and organization_type must be strings")

    country = as_token(country)
    org_type = as_token(org_type).lower()
    if org_type != "all" and org_type not in ORG_TYPES:
        raise ValueError("organization_type must be one of non_profit, for_profit or ALL")
    return country, org_type


def read_custom_range(params, start_key, end_key):
    # returns None when neither date is sent, (start, end_exclusive) otherwise
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
    # end date is inclusive, so the cutoff is the start of the next day
    return pd.Timestamp(first), pd.Timestamp(last) + timedelta(days=1)


def fixed_range(name, today):
    tomorrow = today + timedelta(days=1)
    days = {"7D": 7, "30D": 30, "1Y": 365}.get(name)
    if days is None:
        return None, None
    return tomorrow - timedelta(days=days), tomorrow


def to_flag(series):
    # csv gives "True"/"False" strings, postgres gives real booleans
    return series.astype(str).str.strip().str.lower().isin(["true", "t", "1", "yes"])


def tidy(frame):
    # same cleanup for both sources so the chart code never cares where rows came from
    frame = frame.copy()
    if "is_contributor" not in frame.columns:
        frame["is_contributor"] = False
    for col in FRAME_COLUMNS:
        if col not in frame.columns:
            frame[col] = None
    frame["is_collaborator"] = to_flag(frame["is_collaborator"])
    frame["is_contributor"] = to_flag(frame["is_contributor"])
    created = pd.to_datetime(frame["created_at"], errors="coerce", utc=True)
    frame["created_at"] = created.dt.tz_localize(None)
    return frame.dropna(subset=["created_at"])[FRAME_COLUMNS]


def read_csv(folder, name):
    try:
        return pd.read_csv(os.path.join(folder, name), dtype={"state_id": str},
                           keep_default_na=False, na_values=[""])
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def load_from_csv(country, org_type):
    folder = os.environ.get("MOCK_DATA_DIR", DEFAULT_DATA_DIR)
    orgs = read_csv(folder, "organizations.csv")
    if orgs.empty:
        return tidy(pd.DataFrame(columns=FRAME_COLUMNS))

    states = read_csv(folder, "states.csv")[["state_id", "country_id"]].drop_duplicates("state_id")
    countries = read_csv(folder, "countries.csv")[["country_id", "country_code", "country_name"]]
    orgs["state_id"] = orgs["state_id"].astype(str)
    orgs = orgs.merge(states, on="state_id", how="left").merge(countries, on="country_id", how="left")

    if country != "ALL":
        by_code = orgs["country_code"].fillna("").map(as_token) == country
        by_name = orgs["country_name"].fillna("").map(as_token) == country
        orgs = orgs[by_code | by_name]
    if org_type != "all":
        orgs = orgs[orgs["org_type"].fillna("").map(as_token).str.lower() == org_type]
    return tidy(orgs)


def load_from_db(country, org_type):
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is not installed, set USE_MOCK_DATA=true to run on the csvs")

    # filters run inside postgres so only matching orgs come back over the wire
    conditions, args = [], []
    if country != "ALL":
        conditions.append(
            "(UPPER(c.country_code::text) = %s"
            " OR UPPER(REPLACE(REPLACE(c.country_name::text, ' ', '_'), '-', '_')) = %s)"
        )
        args += [country, country]
    if org_type != "all":
        conditions.append("LOWER(REPLACE(REPLACE(o.org_type::text, ' ', '_'), '-', '_')) = %s")
        args.append(org_type)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    def query(contributor_col):
        return f"""
            SELECT o.org_size::text AS org_size, o.org_type::text AS org_type,
                   o.is_collaborator, {contributor_col} AS is_contributor, o.created_at,
                   c.country_code, c.country_name::text AS country_name
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
        cur = conn.cursor()
        try:
            cur.execute(query("o.is_contributor"), args)
        except Exception as e:
            # 42703 = undefined column, older schemas don't have is_contributor yet
            if getattr(e, "pgcode", None) != "42703":
                raise
            conn.rollback()
            cur.execute(query("FALSE"), args)
        names = [d[0] for d in cur.description]
        return tidy(pd.DataFrame(cur.fetchall(), columns=names))
    finally:
        conn.close()


def load_orgs(country, org_type):
    if os.environ.get("USE_MOCK_DATA", "false").strip().lower() == "true":
        return load_from_csv(country, org_type)
    return load_from_db(country, org_type)


def in_window(df, start, end):
    if start is not None:
        df = df[df["created_at"] >= start]
    if end is not None:
        df = df[df["created_at"] < end]
    return df


def size_chart(orgs):
    if orgs.empty:
        return []
    # whatever sizes show up in the data, nothing hardcoded; blank sizes kept so counts add up
    counts = orgs["org_size"].fillna("unknown").value_counts()
    ordered = sorted(counts.items(), key=lambda item: (-item[1], str(item[0])))
    return [{"size": str(size), "count": int(n)} for size, n in ordered]


def contribution_chart(orgs):
    total = len(orgs)
    if total == 0:
        return []
    # two separate flags, an org can be both or neither, so these don't add up to 100
    rows = []
    for label, col in (("Collaborator", "is_collaborator"), ("Contributor", "is_contributor")):
        n = int(orgs[col].sum())
        rows.append({"type": label, "count": n, "percentage": round(n * 100 / total, 1)})
    return rows


def empty_charts():
    return {"organizations_by_size": [], "collaborator_vs_contributor": []}


def lambda_handler(event, context):
    try:
        params = parse_event_body(event)
        country, org_type = read_filters(params)
        size_range = read_custom_range(params, "size_start_date", "size_end_date")
        contribution_range = read_custom_range(params, "contribution_start_date", "contribution_end_date")
    except ValueError as e:
        return build_response(400, {"error": str(e)})

    try:
        orgs = load_orgs(country, org_type)

        if size_range or contribution_range:
            # custom request: only the Custom key, each chart filled from its own range
            custom = empty_charts()
            if size_range:
                custom["organizations_by_size"] = size_chart(in_window(orgs, *size_range))
            if contribution_range:
                custom["collaborator_vs_contributor"] = contribution_chart(in_window(orgs, *contribution_range))
            return build_response(200, {"Custom": custom})

        today = pd.Timestamp.now().normalize()
        result = {}
        for name in FIXED_WINDOWS:
            window = in_window(orgs, *fixed_range(name, today))
            result[name] = {
                "organizations_by_size": size_chart(window),
                "collaborator_vs_contributor": contribution_chart(window),
            }
        result["Custom"] = empty_charts()
        return build_response(200, result)

    except Exception as e:
        print(f"size/contribution analytics failed: {e}")
        return build_response(500, {"error": "could not build size and contribution analytics"})


def show(label, event):
    print(f"--- {label} ---")
    res = lambda_handler(event, None)
    print("status:", res["statusCode"])
    print(json.dumps(json.loads(res["body"]), indent=2))
    print()
    return res


if __name__ == "__main__":
    os.environ.setdefault("USE_MOCK_DATA", "true")
    print("===== sample events against the mock csvs =====\n")
    show("no body", {})
    show("country filter (USA)", {"body": json.dumps({"country": "USA"})})
    show("country by name (India)", {"body": json.dumps({"country": "India"})})
    show("org type filter (for_profit)", {"body": json.dumps({"organization_type": "for_profit"})})
    show("size range only", {"body": json.dumps({"size_start_date": "2026-01-01", "size_end_date": "2026-06-30"})})
    show("contribution range only", {"body": json.dumps({
        "contribution_start_date": "2025-06-01", "contribution_end_date": "2025-12-31",
    })})
    show("both ranges together", {"body": json.dumps({
        "country": "USA", "organization_type": "non_profit",
        "size_start_date": "2026-01-01", "size_end_date": "2026-06-30",
        "contribution_start_date": "2025-06-01", "contribution_end_date": "2025-12-31",
    })})
    show("only one date of a pair", {"body": json.dumps({"size_start_date": "2026-01-01"})})
    show("bad date format", {"body": json.dumps({"contribution_start_date": "01/01/2025", "contribution_end_date": "2025-12-31"})})
    show("start after end", {"body": json.dumps({"size_start_date": "2026-06-30", "size_end_date": "2026-01-01"})})
    show("unknown org type", {"body": json.dumps({"organization_type": "government"})})
