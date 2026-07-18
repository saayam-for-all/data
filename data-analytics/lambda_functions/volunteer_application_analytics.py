import json
import psycopg2
import pandas as pd
from datetime import datetime, timedelta
import os
import boto3

REAL_TABLE_STATE_VIRGINIA = "virginia_dev_saayam_rdbms.state"
REAL_TABLE_USERS_VIRGINIA = "virginia_dev_saayam_rdbms.users"
REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA = "virginia_dev_saayam_rdbms.volunteer_details"
REAL_TABLE_CITY_VIRGINIA = "virginia_dev_saayam_rdbms.city"
REAL_TABLE_USER_SKILL_VIRGINIA = "virginia_dev_saayam_rdbms.user_skills"
REAL_TABLE_VOLUNTEER_LOCATIONS_VIRGINIA = "virginia_dev_saayam_rdbms.volunteer_locations"
REAL_TABLE_USER_LOCATIONS_VIRGINIA = "virginia_dev_saayam_rdbms.user_locations"
REAL_TABLE_COUNTRY_VIRGINIA = "virginia_dev_saayam_rdbms.country"
REAL_TABLE_HELP_CATEGORIES_VIRGINIA = "virginia_dev_saayam_rdbms.help_categories"

REAL_TABLE_STATE_IRELAND = "ireland_dev_saayam_rdbms.state"
REAL_TABLE_USERS_IRELAND = "ireland_dev_saayam_rdbms.users"
REAL_TABLE_VOLUNTEER_DETAILS_IRELAND = "ireland_dev_saayam_rdbms.volunteer_details"
REAL_TABLE_CITY_IRELAND = "ireland_dev_saayam_rdbms.city"
REAL_TABLE_USER_SKILLS_IRELAND = "ireland_dev_saayam_rdbms.user_skills"
REAL_TABLE_VOLUNTEER_LOCATIONS_IRELAND = "ireland_dev_saayam_rdbms.volunteer_locations"
REAL_TABLE_USER_LOCATIONS_IRELAND = "ireland_dev_saayam_rdbms.user_locations"
REAL_TABLE_COUNTRY_IRELAND = "ireland_dev_saayam_rdbms.country"
REAL_TABLE_HELP_CATEGORIES_IRELAND = "ireland_dev_saayam_rdbms.help_categories"


def build_date_filter_trend(time_range, start_date=None, end_date=None):
    if time_range == "7D":
        return "AND vd.created_at >= CURRENT_DATE - INTERVAL '7 days'"
    elif time_range == "30D":
        return "AND vd.created_at >= CURRENT_DATE - INTERVAL '30 days'"
    elif time_range == "1Y":
        return "AND vd.created_at >= CURRENT_DATE - INTERVAL '1 year'"
    elif time_range == "All":
        return ""
    elif time_range == "Custom":
        if start_date and end_date:
            return f"AND vd.created_at BETWEEN '{start_date}' AND '{end_date}'"
    return ""


def build_date_filter_location(time_range_location, location_start_date=None, location_end_date=None):
    if time_range_location == "7D":
        return "AND vd.created_at >= CURRENT_DATE - INTERVAL '7 days'"
    elif time_range_location == "30D":
        return "AND vd.created_at >= CURRENT_DATE - INTERVAL '30 days'"
    elif time_range_location == "1Y":
        return "AND vd.created_at >= CURRENT_DATE - INTERVAL '1 year'"
    elif time_range_location == "All":
        return ""
    elif time_range_location == "Custom":
        if location_start_date and location_end_date:
            return f"AND vd.created_at BETWEEN '{location_start_date}' AND '{location_end_date}'"
    return ""


def get_grouping(time_range):
    if time_range in ("7D", "30D", "Custom"):
        return "day"
    elif time_range in ("1Y", "All"):
        return "month"
    return "month"


def parse_event_body(event):
    if not event:
        return {}

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body

    return {}


def lambda_handler(event, context):
    conn_V = None
    cursor_V = None
    conn_I = None
    cursor_I = None

    safe_response = {
        "volunteer_activity_trend": {
            "new_volunteers": [],
            "active_volunteers": [],
            "total_volunteers": []
        },
        "volunteers_by_location": []
    }

    try:
        VIRGINIA_DB_CONFIG = get_db_config('Virginia')
        IRELAND_DB_CONFIG = get_db_config('Ireland')
        conn_V = psycopg2.connect(**VIRGINIA_DB_CONFIG)
        cursor_V = conn_V.cursor()
        print("Virginia database connected successfully.")
        conn_I = psycopg2.connect(**IRELAND_DB_CONFIG)
        cursor_I = conn_I.cursor()
        print("Ireland database connected successfully.")

        request_body = parse_event_body(event)
        country = request_body.get("country", "All Countries")
        chart_type = request_body.get("chart_type", "Bar Chart")
        skill = request_body.get("skill", "All Skills")
        time_range = request_body.get("time_range", "All")
        start_date = request_body.get("start_date", None)
        end_date = request_body.get("end_date", None)
        time_range_location = request_body.get("time_range_location", "All")
        location_start_date = request_body.get("location_start_date", None)
        location_end_date = request_body.get("location_end_date", None)

        date_filter_trend = build_date_filter_trend(time_range, start_date, end_date)
        grouping = get_grouping(time_range)
        date_filter_location = build_date_filter_location(time_range_location, location_start_date, location_end_date)

        volunteer_activity_trend_virginia = get_volunteer_activity_trend(
            cursor_V, REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA,
            date_filter_trend, grouping
        )
        volunteers_by_location_virginia = get_volunteers_by_location(
            cursor_V, REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA,
            REAL_TABLE_COUNTRY_VIRGINIA, REAL_TABLE_USER_SKILL_VIRGINIA,
            REAL_TABLE_HELP_CATEGORIES_VIRGINIA, country, chart_type, skill,
            date_filter_location
        )

        volunteer_activity_trend_ireland = get_volunteer_activity_trend(
            cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND,
            date_filter_trend, grouping
        )
        volunteers_by_location_ireland = get_volunteers_by_location(
            cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND,
            REAL_TABLE_COUNTRY_IRELAND, REAL_TABLE_USER_SKILLS_IRELAND,
            REAL_TABLE_HELP_CATEGORIES_IRELAND, country, chart_type, skill,
            date_filter_location
        )

        response_data = {
            "volunteer_activity_trend": merge_volunteer_activity_trend(
                volunteer_activity_trend_virginia, volunteer_activity_trend_ireland
            ),
            "volunteers_by_location": merge_volunteer_by_location(
                volunteers_by_location_virginia, volunteers_by_location_ireland
            )
        }

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
            },
            "body": json.dumps(response_data)
        }

    except Exception as e:
        print("ERROR:", str(e))
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "Content-Type,Authorization",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
            },
            "body": json.dumps(safe_response)
        }
    finally:
        if cursor_V:
            cursor_V.close()
        if conn_V:
            conn_V.close()
        print("Virginia Database connection closed")

        if cursor_I:
            cursor_I.close()
        if conn_I:
            conn_I.close()
        print("Ireland Database connection closed")


def get_volunteer_activity_trend(cursor, users, volunteer_details, date_filter, grouping):
    try:
        if grouping == "day":
            trunc_expr = "TO_CHAR(DATE_TRUNC('day', vd.created_at), 'YYYY-MM-DD')"
        else:
            trunc_expr = "TO_CHAR(DATE_TRUNC('month', vd.created_at), 'YYYY-MM')"

        query1 = f"""
        SELECT {trunc_expr} AS period,
        COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        {date_filter}
        GROUP BY 1
        ORDER BY 1 ASC
        """
        cursor.execute(query1)
        new_volunteers = cursor.fetchall()
        new_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in new_volunteers]

        query2 = f"""
        SELECT {trunc_expr} AS period,
        COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        AND u.user_status_id = 1
        {date_filter}
        GROUP BY 1
        ORDER BY 1 ASC
        """
        cursor.execute(query2)
        active_volunteers = cursor.fetchall()
        active_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in active_volunteers]

        query3 = f"""
        SELECT period, SUM(count) OVER (ORDER BY period) AS count
        FROM (
            SELECT {trunc_expr} AS period,
            COUNT(DISTINCT u.user_id) AS count
            FROM {users} u
            JOIN {volunteer_details} vd ON u.user_id = vd.user_id
            WHERE vd.created_at IS NOT NULL
            {date_filter}
            GROUP BY 1
        ) sub
        ORDER BY period ASC
        """
        cursor.execute(query3)
        total_volunteers = cursor.fetchall()
        total_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in total_volunteers]

        return {
            "new_volunteers": new_volunteers_final,
            "active_volunteers": active_volunteers_final,
            "total_volunteers": total_volunteers_final
        }

    except Exception as e:
        print("Error in get_volunteer_activity_trend:", str(e))
        return {
            "new_volunteers": [],
            "active_volunteers": [],
            "total_volunteers": []
        }


def merge_period_data(list1, list2):
    merged = {}
    for row in list1 + list2:
        period = row["period"]
        count = row["count"]
        merged[period] = merged.get(period, 0) + count

    return [
        {"period": period, "count": merged[period]}
        for period in sorted(merged.keys())
    ]


def merge_volunteer_activity_trend(trend_virginia, trend_ireland):
    return {
        "new_volunteers": merge_period_data(
            trend_virginia.get("new_volunteers", []),
            trend_ireland.get("new_volunteers", [])
        ),
        "active_volunteers": merge_period_data(
            trend_virginia.get("active_volunteers", []),
            trend_ireland.get("active_volunteers", [])
        ),
        "total_volunteers": merge_period_data(
            trend_virginia.get("total_volunteers", []),
            trend_ireland.get("total_volunteers", [])
        )
    }


def merge_volunteer_by_location(list1, list2):
    merged = {}
    for row in list1 + list2:
        country = row["country"]
        count = row["count"]
        merged[country] = merged.get(country, 0) + count
    return [
        {"country": country, "count": merged[country]}
        for country in sorted(merged.keys())
    ]


def get_volunteers_by_location(cursor, users, volunteer_details, country_table,
                               user_skills, help_categories, country='All Countries',
                               chart_type="Bar Chart", skill="All Skills",
                               date_filter_location=""):
    try:
        query = f"""
        SELECT
            COALESCE(c.country_code, 'Unknown') AS country,
            COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd
            ON u.user_id = vd.user_id
        LEFT JOIN {country_table} c
            ON u.country_id = c.country_id
        WHERE 1=1
        {date_filter_location}
        """

        params = []

        if country != "All Countries":
            query += " AND UPPER(c.country_code) = %s"
            params.append(country)

        if skill != 'All Skills':
            query += f"""
            AND EXISTS (SELECT 1
            FROM {user_skills} us JOIN
            {help_categories} h ON
            us.cat_id = h.cat_id
            WHERE us.user_id = u.user_id
            AND h.cat_name = %s)"""
            params.append(skill)

        query += """
            GROUP BY COALESCE(c.country_code, 'Unknown')
            ORDER BY count DESC;
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            {"country": row[0], "count": int(row[1])}
            for row in rows
        ]

    except Exception as e:
        print("Error in get_volunteers_by_location:", str(e))
        return []


def get_db_config(db):
    ssm = boto3.client("ssm", region_name="us-east-1")

    if db == "Virginia":
        parameter_name = "/dev/saayam/db/Virginia/Analytics/user"
    elif db == "Ireland":
        parameter_name = "/dev/saayam/db/Ireland/Analytics/user"
    else:
        raise ValueError("Database must be either Virginia or Ireland")

    response = ssm.get_parameter(
        Name=parameter_name,
        WithDecryption=True
    )

    config = response["Parameter"]["Value"]
    config_list = [line.strip() for line in config.splitlines()]

    host = config_list[1].split()[1][1:-2]
    port = int(config_list[5].split()[1][:-1])
    dbname = config_list[4].split()[2][1:-2]
    user = config_list[2].split()[1][1:-2]
    password = config_list[3].split()[1][1:-2]

    return {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
        "password": password
    }


def apply_date_filter_local(df, time_range, start_date=None, end_date=None):
    today = pd.Timestamp.now().normalize()
    if time_range == "7D":
        return df[df["created_at"] >= today - pd.Timedelta(days=7)]
    elif time_range == "30D":
        return df[df["created_at"] >= today - pd.Timedelta(days=30)]
    elif time_range == "1Y":
        return df[df["created_at"] >= today - pd.DateOffset(years=1)]
    elif time_range == "All":
        return df
    elif time_range == "Custom":
        if start_date and end_date:
            return df[
                (df["created_at"] >= pd.Timestamp(start_date))
                & (df["created_at"] <= pd.Timestamp(end_date))
            ]
    return df


def get_volunteer_activity_trend_local(users_df, volunteer_details_df, time_range,
                                       start_date=None, end_date=None):
    merged = users_df.merge(volunteer_details_df, on="user_id", how="inner")
    merged["created_at"] = pd.to_datetime(merged["created_at"])
    merged = merged[merged["created_at"].notna()]
    merged = apply_date_filter_local(merged, time_range, start_date, end_date)

    grouping = get_grouping(time_range)

    if grouping == "day":
        merged["period"] = merged["created_at"].dt.strftime("%Y-%m-%d")
    else:
        merged["period"] = merged["created_at"].dt.strftime("%Y-%m")

    new_volunteers = (
        merged.groupby("period")["user_id"]
        .nunique()
        .reset_index(name="count")
        .sort_values("period")
    )
    new_volunteers_final = [
        {"period": row["period"], "count": int(row["count"])}
        for _, row in new_volunteers.iterrows()
    ]

    active_merged = merged[merged["user_status_id"] == 1]
    active_volunteers = (
        active_merged.groupby("period")["user_id"]
        .nunique()
        .reset_index(name="count")
        .sort_values("period")
    )
    active_volunteers_final = [
        {"period": row["period"], "count": int(row["count"])}
        for _, row in active_volunteers.iterrows()
    ]

    total_df = new_volunteers.copy()
    total_df["count"] = total_df["count"].cumsum()
    total_volunteers_final = [
        {"period": row["period"], "count": int(row["count"])}
        for _, row in total_df.iterrows()
    ]

    return {
        "new_volunteers": new_volunteers_final,
        "active_volunteers": active_volunteers_final,
        "total_volunteers": total_volunteers_final
    }


def get_volunteers_by_location_local(users_df, volunteer_details_df, country_df,
                                     time_range_location, location_start_date=None,
                                     location_end_date=None):
    merged = users_df.merge(volunteer_details_df, on="user_id", how="inner")
    merged["created_at"] = pd.to_datetime(merged["created_at"])
    merged = apply_date_filter_local(merged, time_range_location,
                                     location_start_date, location_end_date)

    country_df["country_id"] = pd.to_numeric(country_df["country_id"], errors="coerce")
    merged["country_id"] = pd.to_numeric(merged["country_id"], errors="coerce")

    merged = merged.merge(country_df[["country_id", "country_code"]], on="country_id", how="left")
    merged["country_code"] = merged["country_code"].fillna("Unknown")

    location_counts = (
        merged.groupby("country_code")["user_id"]
        .nunique()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )

    return [
        {"country": row["country_code"], "count": int(row["count"])}
        for _, row in location_counts.iterrows()
    ]


def run_local():
    sql_dir = os.path.join(os.path.dirname(__file__), "..", "sql")

    users_df = pd.read_csv(os.path.join(sql_dir, "users.csv"))
    volunteer_details_df = pd.read_csv(os.path.join(sql_dir, "volunteer_details.csv"))
    country_df = pd.read_csv(os.path.join(sql_dir, "country.csv"))

    common_ids = set(users_df["user_id"]) & set(volunteer_details_df["user_id"])
    if len(common_ids) == 0:
        print("No matching user_ids between users.csv and volunteer_details.csv.")
        print("Local testing requires consistent test data across CSV files.")
        return

    test_cases = [
        {"time_range": "7D", "time_range_location": "7D"},
        {"time_range": "30D", "time_range_location": "30D"},
        {"time_range": "1Y", "time_range_location": "1Y"},
        {"time_range": "All", "time_range_location": "All"},
        {
            "time_range": "Custom",
            "start_date": "2026-01-01",
            "end_date": "2026-05-31",
            "time_range_location": "Custom",
            "location_start_date": "2026-01-01",
            "location_end_date": "2026-05-31",
        },
    ]

    for test in test_cases:
        time_range = test.get("time_range", "All")
        start_date = test.get("start_date", None)
        end_date = test.get("end_date", None)
        time_range_location = test.get("time_range_location", "All")
        location_start_date = test.get("location_start_date", None)
        location_end_date = test.get("location_end_date", None)

        trend = get_volunteer_activity_trend_local(
            users_df, volunteer_details_df, time_range, start_date, end_date
        )
        location = get_volunteers_by_location_local(
            users_df, volunteer_details_df, country_df,
            time_range_location, location_start_date, location_end_date
        )

        response = {
            "volunteer_activity_trend": trend,
            "volunteers_by_location": location
        }

        print(f"\n=== Test: time_range={time_range}, time_range_location={time_range_location} ===")
        print(json.dumps(response, indent=2))


if __name__ == "__main__":
    run_local()
