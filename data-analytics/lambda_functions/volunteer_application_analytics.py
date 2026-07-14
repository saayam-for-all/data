import json
import sqlite3
import pandas as pd
import os

LOCAL_TESTING = False

if not LOCAL_TESTING:
    import psycopg2
    import boto3

# Local table names (no schema prefix needed for SQLite)
LOCAL_TABLE_USERS = "users"
LOCAL_TABLE_VOLUNTEER_DETAILS = "volunteer_details"
LOCAL_TABLE_COUNTRY = "country"
LOCAL_TABLE_USER_SKILLS = "user_skills"
LOCAL_TABLE_HELP_CATEGORIES = "help_categories"

REAL_TABLE_STATE_VIRGINIA ="virginia_dev_saayam_rdbms.state"
REAL_TABLE_USERS_VIRGINIA ="virginia_dev_saayam_rdbms.users"
REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA ="virginia_dev_saayam_rdbms.volunteer_details"
REAL_TABLE_CITY_VIRGINIA ="virginia_dev_saayam_rdbms.city"
REAL_TABLE_USER_SKILL_VIRGINIA ="virginia_dev_saayam_rdbms.user_skills"
REAL_TABLE_VOLUNTEER_LOCATIONS_VIRGINIA ="virginia_dev_saayam_rdbms.volunteer_locations"
REAL_TABLE_USER_LOCATIONS_VIRGINIA ="virginia_dev_saayam_rdbms.user_locations"
REAL_TABLE_COUNTRY_VIRGINIA ="virginia_dev_saayam_rdbms.country"
REAL_TABLE_HELP_CATEGORIES_VIRGINIA = "virginia_dev_saayam_rdbms.help_categories"

REAL_TABLE_STATE_IRELAND ="ireland_dev_saayam_rdbms.state"
REAL_TABLE_USERS_IRELAND ="ireland_dev_saayam_rdbms.users"
REAL_TABLE_VOLUNTEER_DETAILS_IRELAND ="ireland_dev_saayam_rdbms.volunteer_details"
REAL_TABLE_CITY_IRELAND ="ireland_dev_saayam_rdbms.city"
REAL_TABLE_USER_SKILLS_IRELAND ="ireland_dev_saayam_rdbms.user_skills"
REAL_TABLE_VOLUNTEER_LOCATIONS_IRELAND ="ireland_dev_saayam_rdbms.volunteer_locations"
REAL_TABLE_USER_LOCATIONS_IRELAND ="ireland_dev_saayam_rdbms.user_locations"
REAL_TABLE_COUNTRY_IRELAND ="ireland_dev_saayam_rdbms.country"
REAL_TABLE_HELP_CATEGORIES_IRELAND = "ireland_dev_saayam_rdbms.help_categories"

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

def build_date_filter_trend(time_range, start_date=None, end_date=None):
    if time_range == "7D":
        if LOCAL_TESTING:
            return "vd.created_at >= DATE('now', '-7 days')"
        return "vd.created_at >= CURRENT_DATE - INTERVAL '7 days'"
    elif time_range == "30D":
        if LOCAL_TESTING:
            return "vd.created_at >= DATE('now', '-30 days')"
        return "vd.created_at >= CURRENT_DATE - INTERVAL '30 days'"
    elif time_range == "1Y":
        if LOCAL_TESTING:
            return "vd.created_at >= DATE('now', '-1 year')"
        return "vd.created_at >= CURRENT_DATE - INTERVAL '1 year'"
    elif time_range == "Custom" and start_date and end_date:
        return f"vd.created_at BETWEEN '{start_date}' AND '{end_date}'"
    else:
        return "1=1"

def build_date_filter_location(time_range, start_date=None, end_date=None):
    if time_range == "7D":
        if LOCAL_TESTING:
            return "vd.created_at >= DATE('now', '-7 days')"
        return "vd.created_at >= CURRENT_DATE - INTERVAL '7 days'"
    elif time_range == "30D":
        if LOCAL_TESTING:
            return "vd.created_at >= DATE('now', '-30 days')"
        return "vd.created_at >= CURRENT_DATE - INTERVAL '30 days'"
    elif time_range == "1Y":
        if LOCAL_TESTING:
            return "vd.created_at >= DATE('now', '-1 year')"
        return "vd.created_at >= CURRENT_DATE - INTERVAL '1 year'"
    elif time_range == "Custom" and start_date and end_date:
        return f"vd.created_at BETWEEN '{start_date}' AND '{end_date}'"
    else:
        return "1=1"

def get_grouping(time_range):
    if time_range in ("7D", "30D", "Custom"):
        return "TO_CHAR(vd.created_at, 'YYYY-MM-DD')"
    else:
        return "TO_CHAR(DATE_TRUNC('month', vd.created_at), 'YYYY-MM')"

def setup_local_db():
    """Load CSVs into an in-memory SQLite DB for local testing."""
    conn = sqlite3.connect(":memory:")

    def pg_date_trunc(unit, dt_str):
        if dt_str is None:
            return None
        from datetime import datetime
        dt = datetime.fromisoformat(str(dt_str).strip())
        if unit == 'month':
            return dt.replace(day=1).strftime('%Y-%m-%d')
        return dt.strftime('%Y-%m-%d')

    def pg_to_char(dt_str, fmt):
        if dt_str is None:
            return None
        from datetime import datetime
        dt = datetime.fromisoformat(str(dt_str).strip())
        if 'YYYY-MM-DD' in fmt:
            return dt.strftime('%Y-%m-%d')
        elif 'YYYY-MM' in fmt:
            return dt.strftime('%Y-%m')
        return dt.strftime('%Y-%m-%d')

    conn.create_function("DATE_TRUNC", 2, pg_date_trunc)
    conn.create_function("TO_CHAR", 2, pg_to_char)

    base = os.path.join(os.path.dirname(__file__), "..", "sql")
    pd.read_csv(f"{base}/users.csv").to_sql("users", conn, if_exists="replace", index=False)
    pd.read_csv(f"{base}/volunteer_details.csv").to_sql("volunteer_details", conn, if_exists="replace", index=False)
    pd.read_csv(f"{base}/country.csv").to_sql("country", conn, if_exists="replace", index=False)

    print("Local SQLite DB set up successfully.")
    return conn

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
        start_date = request_body.get("start_date")
        end_date = request_body.get("end_date")
        time_range_location = request_body.get("time_range_location", "All")
        location_start_date = request_body.get("location_start_date")
        location_end_date = request_body.get("location_end_date")

        volunteer_activity_trend_virginia = get_volunteer_activity_trend(cursor_V, REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA, time_range, start_date, end_date)
        volunteers_by_location_virginia = get_volunteers_by_location(cursor_V, REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA, REAL_TABLE_COUNTRY_VIRGINIA, REAL_TABLE_USER_SKILL_VIRGINIA, REAL_TABLE_HELP_CATEGORIES_VIRGINIA, country, chart_type, skill, time_range_location, location_start_date, location_end_date)

        volunteer_activity_trend_ireland = get_volunteer_activity_trend(cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND, time_range, start_date, end_date)
        volunteers_by_location_ireland = get_volunteers_by_location(cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND, REAL_TABLE_COUNTRY_IRELAND, REAL_TABLE_USER_SKILLS_IRELAND, REAL_TABLE_HELP_CATEGORIES_IRELAND, country, chart_type, skill, time_range_location, location_start_date, location_end_date)

        response_data = {
            "volunteer_activity_trend": merge_volunteer_activity_trend(volunteer_activity_trend_virginia, volunteer_activity_trend_ireland),
            "volunteers_by_location": merge_volunteer_by_location(volunteers_by_location_virginia, volunteers_by_location_ireland)
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

def get_volunteer_activity_trend(cursor, users, volunteer_details, time_range="All", start_date=None, end_date=None):
    try:
        date_filter = build_date_filter_trend(time_range, start_date, end_date)
        grouping = get_grouping(time_range)

        query1 = f"""SELECT {grouping} AS period,
        COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        AND {date_filter}
        GROUP BY 1
        ORDER BY 1 ASC"""
        cursor.execute(query1)
        new_volunteers = cursor.fetchall()
        new_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in new_volunteers]

        query2 = f"""
        SELECT {grouping} AS period,
        COUNT(DISTINCT u.user_id) AS count FROM {users} u
        JOIN {volunteer_details} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        AND {date_filter}
        AND u.user_status_id = 1
        GROUP BY 1
        ORDER BY 1 ASC
        """
        cursor.execute(query2)
        active_volunteers = cursor.fetchall()
        active_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in active_volunteers]

        query3 = f"""
        SELECT period, SUM(count) OVER (ORDER BY period) AS count
        FROM ( SELECT {grouping} AS period,
        COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        AND {date_filter}
        GROUP BY 1 ) sub
        ORDER BY period ASC;
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

def merge_monthly_data(list1, list2):
    merged = {}
    for row in list1 + list2:
        period = row['period']
        count = row['count']
        merged[period] = merged.get(period, 0) + count
    return [
        {'period': period, 'count': merged[period]}
        for period in sorted(merged.keys())]

def merge_volunteer_activity_trend(volunteer_activity_trend_virginia, volunteer_activity_trend_ireland):
    return {
        "new_volunteers": merge_monthly_data(
            volunteer_activity_trend_virginia.get("new_volunteers", []),
            volunteer_activity_trend_ireland.get("new_volunteers", [])
        ),
        "active_volunteers": merge_monthly_data(
            volunteer_activity_trend_virginia.get("active_volunteers", []),
            volunteer_activity_trend_ireland.get("active_volunteers", [])
        ),
        "total_volunteers": merge_monthly_data(
            volunteer_activity_trend_virginia.get("total_volunteers", []),
            volunteer_activity_trend_ireland.get("total_volunteers", [])
        )
    }

def merge_volunteer_by_location(list1, list2):
    merged = {}
    for row in list1 + list2:
        country = row["country"]
        count = row["count"]
        merged[country] = merged.get(country, 0) + count
    return [{"country": country, "count": merged[country]} for country in sorted(merged.keys())]

def get_volunteers_by_location(cursor, users, volunteer_details, country_table, user_skills, help_categories, country='All Countries', chart_type="Bar Chart", skill="All Skills", time_range_location="All", location_start_date=None, location_end_date=None):
    try:
        date_filter = build_date_filter_location(time_range_location, location_start_date, location_end_date)

        query = f"""SELECT
                COALESCE(c.country_code, 'Unknown') AS country,
                COUNT(DISTINCT u.user_id) AS count
            FROM {users} u
            JOIN {volunteer_details} vd
                ON u.user_id = vd.user_id
            LEFT JOIN {country_table} c
                ON u.country_id = c.country_id
            WHERE {date_filter}
            """

        params = []

        if country != "All Countries":
            query += " AND UPPER(c.country_code) = ?"  if LOCAL_TESTING else " AND UPPER(c.country_code) = %s"
            params.append(country)

        if skill != 'All Skills':
            placeholder = "?" if LOCAL_TESTING else "%s"
            query += f"""
            AND EXISTS (SELECT 1
            FROM {user_skills} us JOIN
            {help_categories} h ON
            us.cat_id = h.cat_id
            WHERE us.user_id = u.user_id
            AND h.cat_name = {placeholder})"""
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

if __name__ == "__main__":
    if LOCAL_TESTING:
        conn = setup_local_db()
        cursor = conn.cursor()

        test_cases = [
            {"time_range": "7D",  "time_range_location": "7D"},
            {"time_range": "30D", "time_range_location": "30D"},
            {"time_range": "1Y",  "time_range_location": "1Y"},
            {"time_range": "All", "time_range_location": "All"},
            {
                "time_range": "Custom",
                "start_date": "2026-05-01",
                "end_date": "2026-05-31",
                "time_range_location": "Custom",
                "location_start_date": "2026-05-01",
                "location_end_date": "2026-05-31"
            },
        ]

        for tc in test_cases:
            time_range          = tc.get("time_range", "All")
            start_date          = tc.get("start_date")
            end_date            = tc.get("end_date")
            time_range_location = tc.get("time_range_location", "All")
            location_start_date = tc.get("location_start_date")
            location_end_date   = tc.get("location_end_date")

            print(f"\n{'='*50}")
            print(f"trend={time_range}  |  location={time_range_location}")
            print(f"{'='*50}")

            trend = get_volunteer_activity_trend(
                cursor, LOCAL_TABLE_USERS, LOCAL_TABLE_VOLUNTEER_DETAILS,
                time_range, start_date, end_date
            )
            print(f"\n--- Volunteer Activity Trend ({time_range}) ---")
            print(json.dumps(trend, indent=2))

            location = get_volunteers_by_location(
                cursor, LOCAL_TABLE_USERS, LOCAL_TABLE_VOLUNTEER_DETAILS,
                LOCAL_TABLE_COUNTRY, LOCAL_TABLE_USER_SKILLS, LOCAL_TABLE_HELP_CATEGORIES,
                time_range_location=time_range_location,
                location_start_date=location_start_date,
                location_end_date=location_end_date
            )
            print(f"\n--- Volunteers by Location ({time_range_location}) ---")
            print(json.dumps(location, indent=2))

        conn.close()
    else:
        test_event = {}
        print(lambda_handler(test_event, None))
