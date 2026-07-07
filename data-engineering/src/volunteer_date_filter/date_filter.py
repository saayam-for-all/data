import json
import os
import psycopg2
import boto3

# --- Schema Qualifier Variables ---
REAL_TABLE_USERS_VIRGINIA = "virginia_dev_saayam_rdbms.users"
REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA = "virginia_dev_saayam_rdbms.volunteer_details"
REAL_TABLE_COUNTRY_VIRGINIA = "virginia_dev_saayam_rdbms.country"
REAL_TABLE_USER_SKILL_VIRGINIA = "virginia_dev_saayam_rdbms.user_skills"
REAL_TABLE_HELP_CATEGORIES_VIRGINIA = "virginia_dev_saayam_rdbms.help_categories"

REAL_TABLE_USERS_IRELAND = "ireland_dev_saayam_rdbms.users"
REAL_TABLE_VOLUNTEER_DETAILS_IRELAND = "ireland_dev_saayam_rdbms.volunteer_details"
REAL_TABLE_COUNTRY_IRELAND = "ireland_dev_saayam_rdbms.country"
REAL_TABLE_USER_SKILLS_IRELAND = "ireland_dev_saayam_rdbms.user_skills"
REAL_TABLE_HELP_CATEGORIES_IRELAND = "ireland_dev_saayam_rdbms.help_categories"

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
}

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

def get_db_config(db):
    # Fallback to environment variables for local mocking/development first
    if os.environ.get("LOCAL_DEV") == "true":
        return {
            "host": os.environ.get("DB_HOST", "localhost"),
            "port": int(os.environ.get("DB_PORT", 5432)),
            "dbname": os.environ.get("DB_NAME", "saayam"),
            "user": os.environ.get("DB_USER", "postgres"),
            "password": os.environ.get("DB_PASSWORD", "")
        }

    ssm = boto3.client("ssm", region_name="us-east-1")
    parameter_name = f"/dev/saayam/db/{db}/Analytics/user"
    
    response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
    config = response["Parameter"]["Value"]
    config_list = [line.strip() for line in config.splitlines()]

    return {
        "host": config_list[1].split()[1][1:-2],
        "port": int(config_list[5].split()[1][:-1]),
        "dbname": config_list[4].split()[2][1:-2],
        "user": config_list[2].split()[1][1:-2],
        "password": config_list[3].split()[1][1:-2]
    }

# ---------------------------------------------------------------------------
# Date Filter Helpers
# ---------------------------------------------------------------------------
def build_date_filter_trend(time_range, start_date=None, end_date=None):
    """Builds the SQL filter and parameters for Volunteer Activity Trend."""
    if time_range == "7D":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '7 days'", []
    elif time_range == "30D":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '30 days'", []
    elif time_range == "1Y":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '1 year'", []
    elif time_range == "Custom" and start_date and end_date:
        return "vd.created_at BETWEEN %s AND %s", [start_date, end_date]
    return "1=1", []

def build_date_filter_location(time_range_location, start_date=None, end_date=None):
    """Builds the SQL filter and parameters for Volunteers by Location."""
    if time_range_location == "7D":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '7 days'", []
    elif time_range_location == "30D":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '30 days'", []
    elif time_range_location == "1Y":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '1 year'", []
    elif time_range_location == "Custom" and start_date and end_date:
        return "vd.created_at BETWEEN %s AND %s", [start_date, end_date]
    return "1=1", []

def get_grouping(time_range):
    """Determines how to group data based on the requested time range."""
    if time_range in ["7D", "30D", "Custom"]:
        return "day", "YYYY-MM-DD"
    # Default behavior for 1Y, All, and unexpected values
    return "month", "YYYY-MM"

# ---------------------------------------------------------------------------
# Core Analytical Queries
# ---------------------------------------------------------------------------
def get_volunteer_activity_trend(cursor, users_table, volunteer_details_table, time_range="All", start_date=None, end_date=None):
    empty = {"new_volunteers": [], "active_volunteers": [], "total_volunteers": []}
    try:
        # Construct date filters and grouping params dynamically
        date_filter_sql, date_params = build_date_filter_trend(time_range, start_date, end_date)
        date_trunc_unit, date_format = get_grouping(time_range)

        # 1. New Volunteers per Period
        cursor.execute(f"""
            SELECT TO_CHAR(DATE_TRUNC('{date_trunc_unit}', vd.created_at), '{date_format}') AS period,
                   COUNT(DISTINCT u.user_id) AS count
            FROM {users_table} u
            JOIN {volunteer_details_table} vd ON u.user_id = vd.user_id
            WHERE vd.created_at IS NOT NULL AND {date_filter_sql}
            GROUP BY 1 ORDER BY 1 ASC
        """, tuple(date_params))
        new_rows = cursor.fetchall()

        # 2. Active Volunteers per Period
        cursor.execute(f"""
            SELECT TO_CHAR(DATE_TRUNC('{date_trunc_unit}', vd.created_at), '{date_format}') AS period,
                   COUNT(DISTINCT u.user_id) AS count
            FROM {users_table} u
            JOIN {volunteer_details_table} vd ON u.user_id = vd.user_id
            WHERE vd.created_at IS NOT NULL AND u.user_status_id = 1 AND {date_filter_sql}
            GROUP BY 1 ORDER BY 1 ASC
        """, tuple(date_params))
        active_rows = cursor.fetchall()

        # 3. Clean Cumulative Total Query 
        cursor.execute(f"""
            WITH periodic AS (
                SELECT DATE_TRUNC('{date_trunc_unit}', vd.created_at) AS period_bucket,
                       COUNT(DISTINCT u.user_id) AS periodic_count
                FROM {users_table} u
                JOIN {volunteer_details_table} vd ON u.user_id = vd.user_id
                WHERE vd.created_at IS NOT NULL AND {date_filter_sql}
                GROUP BY 1
            )
            SELECT TO_CHAR(period_bucket, '{date_format}') AS period,
                   SUM(periodic_count) OVER (
                       ORDER BY period_bucket ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) AS cumulative_count
            FROM periodic ORDER BY period_bucket ASC
        """, tuple(date_params))
        total_rows = cursor.fetchall()

        return {
            "new_volunteers": [{"period": r[0], "count": int(r[1])} for r in new_rows],
            "active_volunteers": [{"period": r[0], "count": int(r[1])} for r in active_rows],
            "total_volunteers": [{"period": r[0], "count": int(r[1])} for r in total_rows],
        }
    except Exception as e:
        print(f"[ERROR] get_volunteer_activity_trend failed: {e}")
        return empty

def get_volunteers_by_location(cursor, users_table, volunteer_details_table, country_table, user_skills_table, help_categories_table, country="All Countries", skill="All Skills", time_range_location="All", start_date=None, end_date=None):
    try:
        date_filter_sql, date_params = build_date_filter_location(time_range_location, start_date, end_date)

        query = f"""
            SELECT COALESCE(c.country_code, 'Unknown') AS country,
                   COUNT(DISTINCT u.user_id) AS count
            FROM {users_table} u
            JOIN {volunteer_details_table} vd ON u.user_id = vd.user_id
            LEFT JOIN {country_table} c ON u.country_id = c.country_id
            WHERE {date_filter_sql}
        """
        params = list(date_params)

        if country and country.strip().lower() not in ("", "all countries"):
            query += " AND UPPER(c.country_code) = %s"
            params.append(country.strip().upper())

        if skill and skill.strip().lower() not in ("", "all skills"):
            query += f""" 
                AND EXISTS (
                    SELECT 1 FROM {user_skills_table} us 
                    JOIN {help_categories_table} h ON us.cat_id = h.cat_id 
                    WHERE us.user_id = u.user_id AND h.cat_name = %s
                )"""
            params.append(skill.strip())

        query += """
            GROUP BY COALESCE(c.country_code, 'Unknown')
            ORDER BY count DESC;
        """
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        return [{"country": r[0], "count": int(r[1])} for r in rows]
    except Exception as e:
        print(f"[ERROR] get_volunteers_by_location failed: {e}")
        return []

# ---------------------------------------------------------------------------
# Merging Layers
# ---------------------------------------------------------------------------
def merge_period_data(list1, list2):
    """Merged renamed from merge_monthly_data to accommodate daily grouping structure."""
    merged = {}
    for row in list1 + list2:
        period = row['period']
        merged[period] = merged.get(period, 0) + row['count']
    return [{'period': p, 'count': merged[p]} for p in sorted(merged.keys())]

def merge_volunteer_activity_trend(trend_v, trend_i):
    return {
        "new_volunteers": merge_period_data(trend_v.get("new_volunteers", []), trend_i.get("new_volunteers", [])),
        "active_volunteers": merge_period_data(trend_v.get("active_volunteers", []), trend_i.get("active_volunteers", [])),
        "total_volunteers": merge_period_data(trend_v.get("total_volunteers", []), trend_i.get("total_volunteers", []))
    }

def merge_volunteer_by_location(list1, list2):
    merged = {}
    for row in list1 + list2:
        country = row["country"]
        merged[country] = merged.get(country, 0) + row["count"]
    return [{"country": c, "count": merged[c]} for c in sorted(merged.keys())]

# ---------------------------------------------------------------------------
# Lambda Handler Entry Point
# ---------------------------------------------------------------------------
def lambda_handler(event, context):
    conn_V = conn_I = cursor_V = cursor_I = None
    safe_response = {
        "volunteer_activity_trend": {"new_volunteers": [], "active_volunteers": [], "total_volunteers": []},
        "volunteers_by_location": []
    }

    try:
        # Establish dual-region parallel architecture handles
        conn_V = psycopg2.connect(**get_db_config('Virginia'))
        cursor_V = conn_V.cursor()
        
        conn_I = psycopg2.connect(**get_db_config('Ireland'))
        cursor_I = conn_I.cursor()

        request_body = parse_event_body(event)
        country = request_body.get("country", "All Countries")
        skill = request_body.get("skill", "All Skills")

        # Parse Date Filters
        time_range = request_body.get("time_range", "All")
        start_date = request_body.get("start_date")
        end_date = request_body.get("end_date")

        time_range_location = request_body.get("time_range_location", "All")
        location_start_date = request_body.get("location_start_date")
        location_end_date = request_body.get("location_end_date")

        # Query Virginia
        trend_v = get_volunteer_activity_trend(
            cursor_V, REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA, 
            time_range, start_date, end_date
        )
        loc_v = get_volunteers_by_location(
            cursor_V, REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA, 
            REAL_TABLE_COUNTRY_VIRGINIA, REAL_TABLE_USER_SKILL_VIRGINIA, REAL_TABLE_HELP_CATEGORIES_VIRGINIA, 
            country, skill, time_range_location, location_start_date, location_end_date
        )

        # Query Ireland
        trend_i = get_volunteer_activity_trend(
            cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND, 
            time_range, start_date, end_date
        )
        loc_i = get_volunteers_by_location(
            cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND, 
            REAL_TABLE_COUNTRY_IRELAND, REAL_TABLE_USER_SKILLS_IRELAND, REAL_TABLE_HELP_CATEGORIES_IRELAND, 
            country, skill, time_range_location, location_start_date, location_end_date
        )

        # Merge outputs cross-regionally
        response_data = {
            "volunteer_activity_trend": merge_volunteer_activity_trend(trend_v, trend_i),
            "volunteers_by_location": merge_volunteer_by_location(loc_v, loc_i)
        }

        return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps(response_data)}

    except Exception as e:
        print(f"[CRITICAL ERROR]: {e}")
        return {"statusCode": 500, "headers": CORS_HEADERS, "body": json.dumps(safe_response)}
        
    finally:
        for cursor, conn in [(cursor_V, conn_V), (cursor_I, conn_I)]:
            if cursor: cursor.close()
            if conn: conn.close()