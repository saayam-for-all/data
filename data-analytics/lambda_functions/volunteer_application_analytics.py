import json
import psycopg2
import boto3

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

    if body is None : 
        return event
    
    if isinstance(body,str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body,dict):
        return body

    return {}

def build_date_filter_trend(event):
    time_range = event.get("time_range", "All")

    if time_range == "7D":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '7 days'"
    if time_range == "30D":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '30 days'"
    if time_range == "1Y":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '1 year'"
    if time_range == "Custom":
        start_date = event.get("start_date")
        end_date = event.get("end_date")
        if start_date and end_date:
            return f"vd.created_at BETWEEN '{start_date}' AND '{end_date}'"
        return ""

    return ""

def build_date_filter_location(event):
    time_range = event.get("time_range_location", "All")

    if time_range == "7D":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '7 days'"
    if time_range == "30D":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '30 days'"
    if time_range == "1Y":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '1 year'"
    if time_range == "Custom":
        start_date = event.get("location_start_date")
        end_date = event.get("location_end_date")
        if start_date and end_date:
            return f"vd.created_at BETWEEN '{start_date}' AND '{end_date}'"
        return ""

    return ""

def get_grouping(time_range):
    if time_range in ("7D", "30D", "Custom"):
        return (
            "DATE(vd.created_at)",
            "TO_CHAR(DATE(vd.created_at), 'YYYY-MM-DD')"
        )

    return (
        "DATE_TRUNC('month', vd.created_at)",
        "TO_CHAR(DATE_TRUNC('month', vd.created_at), 'YYYY-MM')"
    )

def lambda_handler(event, context):
    conn_V = None
    cursor_V = None
    conn_I = None
    cursor_I = None

    safe_response = {
        "volunteer_activity_trend":{
        "new_volunteers": [],
        "active_volunteers": [],
        "total_volunteers": []},
        "volunteers_by_location":[]
    }

    try:
        # Connects to database
        VIRGINIA_DB_CONFIG = get_db_config('Virginia')
        IRELAND_DB_CONFIG = get_db_config('Ireland')
        conn_V = psycopg2.connect(**VIRGINIA_DB_CONFIG)
        cursor_V = conn_V.cursor()
        print("Virginia database connected succcessfully.")
        conn_I = psycopg2.connect(**IRELAND_DB_CONFIG)
        cursor_I = conn_I.cursor()
        print ("Ireland database connected succcessfully.")

        request_body = parse_event_body(event)
        country = request_body.get("country", "All Countries")
        chart_type = request_body.get("chart_type", "Bar Chart")
        skill = request_body.get("skill", "All Skills")
     
        volunteer_activity_trend_virginia = get_volunteer_activity_trend(cursor_V, REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA, request_body)
        volunteers_by_location_virginia =  get_volunteers_by_location(cursor_V,REAL_TABLE_USERS_VIRGINIA,REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA,REAL_TABLE_COUNTRY_VIRGINIA,REAL_TABLE_USER_SKILL_VIRGINIA,REAL_TABLE_HELP_CATEGORIES_VIRGINIA,country,chart_type,skill,request_body)

        volunteer_activity_trend_ireland = get_volunteer_activity_trend(cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND, request_body)
        volunteers_by_location_ireland =  get_volunteers_by_location(cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND, REAL_TABLE_COUNTRY_IRELAND, REAL_TABLE_USER_SKILLS_IRELAND, REAL_TABLE_HELP_CATEGORIES_IRELAND,country, chart_type,skill,request_body)

        response_data = {
            "volunteer_activity_trend" : merge_volunteer_activity_trend(volunteer_activity_trend_virginia, volunteer_activity_trend_ireland ),
            "volunteers_by_location" : merge_volunteer_by_location(volunteers_by_location_virginia, volunteers_by_location_ireland)
        }

        return {
        "statusCode": 200,
        "headers":{
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
        },
        "body": json.dumps(response_data)
        }
        
    except Exception as e:
        # Catches an error if connection fails
        print("ERROR:", str(e))
        return {
            "statusCode": 500,
            "headers":{
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
   


def get_volunteer_activity_trend(cursor,users,volunteer_details,event=None):
    try:
        event = event or {}
        time_range = event.get("time_range", "All")
        date_filter = build_date_filter_trend(event)
        group_by, period_select = get_grouping(time_range)
        date_condition = f" AND {date_filter}" if date_filter else ""

        query1 = f"""SELECT {period_select} AS period,
        COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL{date_condition}
        GROUP BY {group_by}
        ORDER BY 1 ASC"""
        cursor.execute(query1)


        new_volunteers = cursor.fetchall()
        new_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in new_volunteers]

        query2 = f"""
        SELECT {period_select} AS period,
        COUNT(DISTINCT u.user_id) AS count FROM {users} u
        JOIN {volunteer_details} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL{date_condition}
        AND u.user_status_id = 1
        GROUP BY {group_by}
        ORDER BY 1 ASC
        """
        cursor.execute(query2)
        active_volunteers = cursor.fetchall()
        active_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in active_volunteers]

        query3 = f"""
        SELECT period, SUM(count) OVER (ORDER BY period) AS count
        FROM ( SELECT {period_select} AS period,
        COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd
        ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL{date_condition}
        GROUP BY {group_by} ) sub
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
    merged= {}
    for row in list1 + list2 :
        period = row['period']
        count = row['count']

        merged[period] = merged.get(period,0) + count

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
    return [ {"country": country, "count": merged[country]} for country in sorted(merged.keys()) ]


def get_volunteers_by_location( cursor, users, volunteer_details, country_table, user_skills,help_categories,country='All Countries',chart_type="Bar Chart",skill="All Skills",event=None):
    try:
        query= f"""SELECT
                COALESCE(c.country_code, 'Unknown') AS country,
                COUNT(DISTINCT u.user_id) AS count
            FROM {users} u
            JOIN {volunteer_details} vd
                ON u.user_id = vd.user_id
            LEFT JOIN {country_table} c
                ON u.country_id = c.country_id
            WHERE 1=1
            """

        params = []

        date_filter = build_date_filter_location(event or {})
        if date_filter:
            query += f" AND {date_filter}"

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

        return[
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
    import csv
    import os

    SQL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sql")

    # Local database only -- connection details come from environment
    # variables with localhost defaults, never from SSM.
    LOCAL_DB_CONFIG = {
        "host": os.environ.get("LOCAL_DB_HOST", "localhost"),
        "port": int(os.environ.get("LOCAL_DB_PORT", "5432")),
        "dbname": os.environ.get("LOCAL_DB_NAME", "postgres"),
        "user": os.environ.get("LOCAL_DB_USER", "postgres"),
        "password": os.environ.get("LOCAL_DB_PASSWORD", "postgres"),
    }

    def read_csv(filename):
        path = os.path.join(SQL_DIR, filename)
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def clean(value):
        if value in (None, "", "NULL"):
            return None
        return value

    def load_local_test_data(conn):
        users_rows = read_csv("users.csv")
        volunteer_rows = read_csv("volunteer_details.csv")
        country_rows = read_csv("country.csv")
        skill_rows = read_csv("user_skills.csv")
        category_rows = read_csv("help_category.csv")

        cur = conn.cursor()
        for schema in ("virginia_dev_saayam_rdbms", "ireland_dev_saayam_rdbms"):
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            cur.execute(f"CREATE SCHEMA {schema}")
            cur.execute(f"CREATE TABLE {schema}.users (user_id TEXT, country_id INT, user_status_id INT)")
            cur.execute(f"CREATE TABLE {schema}.volunteer_details (user_id TEXT, created_at TIMESTAMP)")
            cur.execute(f"CREATE TABLE {schema}.country (country_id INT, country_code TEXT)")
            cur.execute(f"CREATE TABLE {schema}.user_skills (user_id TEXT, cat_id TEXT)")
            cur.execute(f"CREATE TABLE {schema}.help_categories (cat_id TEXT, cat_name TEXT)")

        # The CSV fixtures represent one region; load them into the
        # Virginia schema and leave Ireland empty.
        schema = "virginia_dev_saayam_rdbms"
        cur.executemany(
            f"INSERT INTO {schema}.users VALUES (%s, %s, %s)",
            [(r["user_id"], clean(r["country_id"]), clean(r["user_status_id"])) for r in users_rows],
        )
        cur.executemany(
            f"INSERT INTO {schema}.volunteer_details VALUES (%s, %s)",
            [(r["user_id"], clean(r["created_at"])) for r in volunteer_rows],
        )
        cur.executemany(
            f"INSERT INTO {schema}.country VALUES (%s, %s)",
            [(clean(r["country_id"]), clean(r["country_code"])) for r in country_rows],
        )
        cur.executemany(
            f"INSERT INTO {schema}.user_skills VALUES (%s, %s)",
            [(r["user_id"], r["cat_id"]) for r in skill_rows],
        )
        cur.executemany(
            f"INSERT INTO {schema}.help_categories VALUES (%s, %s)",
            [(r["cat_id"], r["cat_name"]) for r in category_rows],
        )
        conn.commit()
        cur.close()

    def local_db_config(db):
        return LOCAL_DB_CONFIG

    try:
        setup_conn = psycopg2.connect(**LOCAL_DB_CONFIG)
        load_local_test_data(setup_conn)
        setup_conn.close()
        print("Local test data loaded from", SQL_DIR)
    except Exception as e:
        print("Could not prepare local test database:", str(e))
        raise SystemExit(1)

    get_db_config = local_db_config

    test_events = [
        {"time_range": "7D", "time_range_location": "7D"},
        {"time_range": "30D", "time_range_location": "30D"},
        {"time_range": "1Y", "time_range_location": "1Y"},
        {"time_range": "All", "time_range_location": "All"},
        {"time_range": "Custom", "start_date": "2026-01-01", "end_date": "2026-05-31",
         "time_range_location": "Custom", "location_start_date": "2026-01-01", "location_end_date": "2026-05-31"},
    ]

    for test_event in test_events:
        print("Event:", json.dumps(test_event))
        result = lambda_handler(test_event, None)
        print("Response:", result["body"])
        print()

