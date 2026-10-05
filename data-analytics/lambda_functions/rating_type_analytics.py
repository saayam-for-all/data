"""Rating and type analytics for the organization dashboard."""

import json
import os
from datetime import datetime, timedelta, timezone

import pandas as pd

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    psycopg2 = None
    sql = None


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": body,
    }


def _empty_bucket():
    return {
        "rating_distribution": [],
        "organization_mix_trend": {"non_profit": [], "for_profit": []},
    }


def _payload(event):
    if event is None:
        return {}
    if not isinstance(event, dict):
        raise ValueError("Request must be an object.")

    body = event.get("body", event)
    if body is None or body == "":
        return {}
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must contain valid JSON.") from exc
    if not isinstance(body, dict):
        raise ValueError("Request body must be an object.")
    return body


def _date_pair(params, prefix):
    start_key = prefix + "_start_date"
    end_key = prefix + "_end_date"
    has_start = start_key in params
    has_end = end_key in params

    if not has_start and not has_end:
        return None
    if not has_start or not has_end:
        raise ValueError(f"Both {start_key} and {end_key} are required.")

    dates = []
    for key in (start_key, end_key):
        value = params[key]
        if not isinstance(value, str):
            raise ValueError(f"{key} must use YYYY-MM-DD format.")
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(f"{key} must be a valid YYYY-MM-DD date.") from exc
        if parsed.isoformat() != value:
            raise ValueError(f"{key} must use YYYY-MM-DD format.")
        dates.append(parsed)

    if dates[0] > dates[1]:
        raise ValueError(f"{start_key} must not be after {end_key}.")
    return tuple(dates)


def _require_columns(frame, columns, table):
    missing = set(columns) - set(frame.columns)
    if missing:
        raise RuntimeError(f"{table} is missing columns: {sorted(missing)}")


def _load_mock():
    data_dir = os.environ.get("MOCK_DATA_DIR") or os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "sql")
    )

    def read_file(names, empty_columns):
        for name in names:
            path = os.path.join(data_dir, name)
            if os.path.isfile(path):
                try:
                    return pd.read_csv(path, dtype="string")
                except pd.errors.EmptyDataError:
                    return pd.DataFrame(columns=empty_columns)
        raise FileNotFoundError(f"None of {names} found in {data_dir}")

    organizations = read_file(
        ("organizations.csv",),
        ("org_id", "org_rating", "org_type", "state_id", "created_at"),
    )
    states = read_file(
        ("states.csv", "state.csv"), ("state_id", "country_id")
    )
    countries = read_file(
        ("countries.csv", "country.csv"),
        ("country_id", "country_code", "country_name"),
    )

    _require_columns(
        organizations,
        ("org_id", "org_rating", "org_type", "state_id", "created_at"),
        "organizations.csv",
    )
    _require_columns(states, ("state_id", "country_id"), "states.csv")
    _require_columns(countries, ("country_id",), "countries.csv")

    if "country_code" not in countries and "country_name" not in countries:
        raise RuntimeError("countries.csv needs country_code or country_name.")
    for column in ("country_code", "country_name"):
        if column not in countries:
            countries[column] = ""

    for frame, column in (
        (organizations, "state_id"),
        (states, "state_id"),
        (states, "country_id"),
        (countries, "country_id"),
    ):
        frame[column] = frame[column].astype("string").str.strip()

    states = states.dropna(subset=["state_id"])
    countries = countries.dropna(subset=["country_id"])

    return (
        organizations.merge(
            states[["state_id", "country_id"]], on="state_id", how="left"
        )
        .merge(
            countries[["country_id", "country_code", "country_name"]],
            on="country_id",
            how="left",
        )
    )


def _load_postgres():
    if psycopg2 is None:
        raise RuntimeError(
            "psycopg2 is required when USE_MOCK_DATA is not true."
        )

    config = {}
    for option, variable in (
        ("host", "DB_HOST"),
        ("dbname", "DB_NAME"),
        ("user", "DB_USER"),
        ("password", "DB_PASSWORD"),
        ("port", "DB_PORT"),
    ):
        if os.environ.get(variable):
            config[option] = os.environ[variable]

    schema = os.environ.get(
        "DB_SCHEMA", "virginia_dev_saayam_rdbms"
    )
    query = sql.SQL(
        "SELECT o.org_id, o.org_rating, o.org_type, o.state_id, "
        "o.created_at, c.country_code, c.country_name "
        "FROM {} AS o "
        "LEFT JOIN {} AS s ON o.state_id = s.state_id "
        "LEFT JOIN {} AS c ON s.country_id = c.country_id"
    ).format(
        sql.Identifier(schema, "organizations"),
        sql.Identifier(schema, "states"),
        sql.Identifier(schema, "countries"),
    )

    connection = psycopg2.connect(**config)
    try:
        with connection.cursor() as cursor:
            cursor.execute(query)
            columns = [item[0] for item in cursor.description]
            return pd.DataFrame(cursor.fetchall(), columns=columns)
    finally:
        connection.close()


def _prepare(frame):
    _require_columns(
        frame,
        ("org_id", "org_rating", "org_type", "created_at",
         "country_code", "country_name"),
        "organization data",
    )
    frame = frame.copy()
    frame["created_at"] = pd.to_datetime(
        frame["created_at"], errors="coerce", utc=True
    ).dt.tz_convert(None)
    frame["org_rating"] = pd.to_numeric(
        frame["org_rating"], errors="coerce"
    )
    frame["org_type"] = (
        frame["org_type"]
        .astype("string")
        .str.lower()
        .str.replace(r"[^a-z0-9]+", "_", regex=True)
        .str.strip("_")
    )
    return frame


def _by_country(frame, country):
    if not isinstance(country, str) or not country.strip():
        raise ValueError("country must be a non-empty name, code, or ALL.")
    if country.strip().upper() == "ALL":
        return frame

    target = country.strip().casefold()
    code_match = (
        frame["country_code"].astype("string").str.casefold()
        .eq(target).fillna(False)
    )
    name_match = (
        frame["country_name"].astype("string").str.casefold()
        .eq(target).fillna(False)
    )
    return frame.loc[code_match | name_match]


def _window(frame, start, end):
    frame = frame.loc[frame["created_at"].notna()]
    dates = frame["created_at"].dt.date
    keep = dates <= end
    if start is not None:
        keep &= dates >= start
    return frame.loc[keep]


def _rating_distribution(frame, start, end):
    window = _window(frame, start, end)
    ratings = window["org_rating"]
    valid = window.loc[
        ratings.between(1, 5) & ratings.mod(1).eq(0)
    ]
    counts = valid["org_rating"].value_counts().sort_index()
    return [
        {"rating": int(rating), "count": int(count)}
        for rating, count in counts.items()
    ]


def _organization_mix_trend(frame, start, end, daily):
    result = {"non_profit": [], "for_profit": []}
    dated = _window(frame, None, end)
    date_format = "%Y-%m-%d" if daily else "%Y-%m"

    for org_type in result:
        rows = dated.loc[dated["org_type"].eq(org_type)].copy()
        if rows.empty:
            continue

        rows["period"] = rows["created_at"].dt.strftime(date_format)
        cumulative = rows.groupby("period").size().sort_index().cumsum()
        active = rows
        if start is not None:
            active = rows.loc[rows["created_at"].dt.date >= start]

        for period in sorted(active["period"].unique()):
            result[org_type].append(
                {"period": period, "count": int(cumulative.loc[period])}
            )

    return result


def lambda_handler(event, context):
    try:
        params = _payload(event)
        rating_dates = _date_pair(params, "rating")
        type_dates = _date_pair(params, "type")
        country = params.get("country", "ALL")

        use_mock = os.environ.get(
            "USE_MOCK_DATA", "false"
        ).strip().lower() in ("true", "1", "yes")
        data = _prepare(_load_mock() if use_mock else _load_postgres())
        data = _by_country(data, country)

        today = datetime.now(timezone.utc).date()
        if rating_dates is not None or type_dates is not None:
            custom = _empty_bucket()
            if rating_dates is not None:
                custom["rating_distribution"] = _rating_distribution(
                    data, *rating_dates
                )
            if type_dates is not None:
                custom["organization_mix_trend"] = _organization_mix_trend(
                    data, *type_dates, daily=True
                )
            return _response(200, {"Custom": custom})

        starts = {
            "7D": today - timedelta(days=6),
            "30D": today - timedelta(days=29),
            "1Y": today - timedelta(days=365),
            "All": None,
        }
        result = {}
        for bucket, start in starts.items():
            result[bucket] = {
                "rating_distribution": _rating_distribution(
                    data, start, today
                ),
                "organization_mix_trend": _organization_mix_trend(
                    data, start, today, daily=bucket in ("7D", "30D")
                ),
            }
        result["Custom"] = _empty_bucket()
        return _response(200, result)

    except ValueError as exc:
        return _response(400, {"error": str(exc)})
    except Exception as exc:
        print(f"Rating and type analytics failed: {exc}")
        return _response(500, {"error": "Unable to load analytics data."})


if __name__ == "__main__":
    os.environ.setdefault("USE_MOCK_DATA", "true")
    examples = {
        "default": {},
        "country": {"country": "USA"},
        "rating custom": {
            "rating_start_date": "2023-01-01",
            "rating_end_date": "2026-12-31",
        },
        "type custom": {
            "type_start_date": "2023-01-01",
            "type_end_date": "2026-12-31",
        },
        "both custom": {
            "rating_start_date": "2023-01-01",
            "rating_end_date": "2026-12-31",
            "type_start_date": "2024-01-01",
            "type_end_date": "2026-12-31",
        },
    }
    for label, example in examples.items():
        print(label)
        print(json.dumps(lambda_handler(example, None), indent=2))
