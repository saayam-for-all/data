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
# Core Analytical Queries (Using your streamlined SQL logic)
# ---------------------------------------------------------------------------
def get_volunteer_activity_trend(cursor, users_table, volunteer_details_table):
    empty = {"new_volunteers": [], "active_volunteers": [], "total_volunteers": []}
    try:
        # 1. New Volunteers per Month
        cursor.execute(f"""
            SELECT TO_CHAR(DATE_TRUNC('month', vd.created_at), 'YYYY-MM') AS month,
                   COUNT(DISTINCT u.user_id) AS count
            FROM {users_table} u
            JOIN {volunteer_details_table} vd ON u.user_id = vd.user_id
            WHERE vd.created_at IS NOT NULL
            GROUP BY 1 ORDER BY 1 ASC
        """)
        new_rows = cursor.fetchall()

        # 2. Active Volunteers per Month
        cursor.execute(f"""
            SELECT TO_CHAR(DATE_TRUNC('month', vd.created_at), 'YYYY-MM') AS month,
                   COUNT(DISTINCT u.user_id) AS count
            FROM {users_table} u
            JOIN {volunteer_details_table} vd ON u.user_id = vd.user_id
            WHERE vd.created_at IS NOT NULL AND u.user_status_id = 1
            GROUP BY 1 ORDER BY 1 ASC
        """)
        active_rows = cursor.fetchall()

        # 3. Clean Cumulative Total Query 
        cursor.execute(f"""
            WITH monthly AS (
                SELECT DATE_TRUNC('month', vd.created_at) AS month_bucket,
                       COUNT(DISTINCT u.user_id) AS monthly_count
                FROM {users_table} u
                JOIN {volunteer_details_table} vd ON u.user_id = vd.user_id
                WHERE vd.created_at IS NOT NULL
                GROUP BY 1
            )
            SELECT TO_CHAR(month_bucket, 'YYYY-MM') AS month,
                   SUM(monthly_count) OVER (
                       ORDER BY month_bucket ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) AS cumulative_count
            FROM monthly ORDER BY month_bucket ASC
        """)
        total_rows = cursor.fetchall()

        return {
            "new_volunteers": [{"month": r[0], "count": int(r[1])} for r in new_rows],
            "active_volunteers": [{"month": r[0], "count": int(r[1])} for r in active_rows],
            "total_volunteers": [{"month": r[0], "count": int(r[1])} for r in total_rows],
        }
    except Exception as e:
        print(f"[ERROR] get_volunteer_activity_trend failed: {e}")
        return empty

def get_volunteers_by_location(cursor, users_table, volunteer_details_table, country_table, user_skills_table, help_categories_table, country="All Countries", skill="All Skills"):
    try:
        query = f"""
            SELECT COALESCE(c.country_code, 'Unknown') AS country,
                   COUNT(DISTINCT u.user_id) AS count
            FROM {users_table} u
            JOIN {volunteer_details_table} vd ON u.user_id = vd.user_id
            LEFT JOIN {country_table} c ON u.country_id = c.country_id
            WHERE 1=1
        """
        params = []

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
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [{"country": r[0], "count": int(r[1])} for r in rows]
    except Exception as e:
        print(f"[ERROR] get_volunteers_by_location failed: {e}")
        return []

# ---------------------------------------------------------------------------
# Merging Layers
# ---------------------------------------------------------------------------
def merge_monthly_data(list1, list2):
    merged = {}
    for row in list1 + list2:
        month = row['month']
        merged[month] = merged.get(month, 0) + row['count']
    return [{'month': m, 'count': merged[m]} for m in sorted(merged.keys())]

def merge_volunteer_activity_trend(trend_v, trend_i):
    return {
        "new_volunteers": merge_monthly_data(trend_v.get("new_volunteers", []), trend_i.get("new_volunteers", [])),
        "active_volunteers": merge_monthly_data(trend_v.get("active_volunteers", []), trend_i.get("active_volunteers", [])),
        "total_volunteers": merge_monthly_data(trend_v.get("total_volunteers", []), trend_i.get("total_volunteers", []))
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

        # Query Virginia
        trend_v = get_volunteer_activity_trend(cursor_V, REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA)
        loc_v = get_volunteers_by_location(cursor_V, REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA, REAL_TABLE_COUNTRY_VIRGINIA, REAL_TABLE_USER_SKILL_VIRGINIA, REAL_TABLE_HELP_CATEGORIES_VIRGINIA, country, skill)

        # Query Ireland
        trend_i = get_volunteer_activity_trend(cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND)
        loc_i = get_volunteers_by_location(cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND, REAL_TABLE_COUNTRY_IRELAND, REAL_TABLE_USER_SKILLS_IRELAND, REAL_TABLE_HELP_CATEGORIES_IRELAND, country, skill)

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