import json
import psycopg2
import boto3
import os
import pandas as pd
from datetime import datetime

LOCAL_DB_TEST = os.getenv("LOCAL_DB_TEST", "false").lower() == "true"

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

    if LOCAL_DB_TEST:
        print("Running in LOCAL_DB_TEST mode using CSV files")

        request_body = parse_event_body(event)

        return run_local_test(request_body)
    
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
        volunteers_by_location_virginia =  get_volunteers_by_location(cursor_V,REAL_TABLE_USERS_VIRGINIA,REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA,REAL_TABLE_COUNTRY_VIRGINIA,REAL_TABLE_USER_SKILL_VIRGINIA,REAL_TABLE_HELP_CATEGORIES_VIRGINIA,country,chart_type,skill, request_body)

        volunteer_activity_trend_ireland = get_volunteer_activity_trend(cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND, request_body)
        volunteers_by_location_ireland =  get_volunteers_by_location(cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND, REAL_TABLE_COUNTRY_IRELAND, REAL_TABLE_USER_SKILLS_IRELAND, REAL_TABLE_HELP_CATEGORIES_IRELAND,country, chart_type,skill, request_body)

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
        
def is_valid_date(date_text):
    try:
        datetime.strptime(date_text, "%Y-%m-%d")
        return True
    except Exception:
        return False        
   
def build_date_filter_trend(request_body):
    time_range = request_body.get("time_range", "All")

    if time_range == "7D":
        return " AND vd.created_at >= CURRENT_DATE - INTERVAL '7 days' "

    if time_range == "30D":
        return " AND vd.created_at >= CURRENT_DATE - INTERVAL '30 days' "

    if time_range == "1Y":
        return " AND vd.created_at >= CURRENT_DATE - INTERVAL '1 year' "

    if time_range == "Custom":
        start_date = request_body.get("start_date")
        end_date = request_body.get("end_date")

        if start_date and end_date and is_valid_date(start_date) and is_valid_date(end_date):
            return f" AND vd.created_at::date BETWEEN '{start_date}' AND '{end_date}' "

    return ""


def build_date_filter_location(request_body):
    time_range = request_body.get("time_range_location", "All")

    if time_range == "7D":
        return " AND vd.created_at >= CURRENT_DATE - INTERVAL '7 days' "

    if time_range == "30D":
        return " AND vd.created_at >= CURRENT_DATE - INTERVAL '30 days' "

    if time_range == "1Y":
        return " AND vd.created_at >= CURRENT_DATE - INTERVAL '1 year' "

    if time_range == "Custom":
        start_date = request_body.get("location_start_date")
        end_date = request_body.get("location_end_date")

        if start_date and end_date and is_valid_date(start_date) and is_valid_date(end_date):
            return f" AND vd.created_at::date BETWEEN '{start_date}' AND '{end_date}' "

    return ""


def get_grouping(request_body):
    time_range = request_body.get("time_range", "All")

    if time_range in ["7D", "30D", "Custom"]:
        return {
            "select": "TO_CHAR(vd.created_at::date, 'YYYY-MM-DD')",
            "group_by": "vd.created_at::date",
            "order_by": "vd.created_at::date"
        }

    return {
        "select": "TO_CHAR(DATE_TRUNC('month', vd.created_at), 'YYYY-MM')",
        "group_by": "DATE_TRUNC('month', vd.created_at)",
        "order_by": "DATE_TRUNC('month', vd.created_at)"
    }

def get_volunteer_activity_trend(cursor, users, volunteer_details, request_body):
    try:
        date_filter = build_date_filter_trend(request_body)
        grouping = get_grouping(request_body)

        query1 = f"""
        SELECT 
            {grouping["select"]} AS period,
            COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd 
            ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        {date_filter}
        GROUP BY {grouping["group_by"]}
        ORDER BY {grouping["order_by"]} ASC
        """

        cursor.execute(query1)
        new_volunteers = cursor.fetchall()
        new_volunteers_final = [
            {"period": row[0], "count": int(row[1])}
            for row in new_volunteers
        ]

        query2 = f"""
        SELECT 
            {grouping["select"]} AS period,
            COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd 
            ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        {date_filter}
        AND u.user_status_id = 1
        GROUP BY {grouping["group_by"]}
        ORDER BY {grouping["order_by"]} ASC
        """

        cursor.execute(query2)
        active_volunteers = cursor.fetchall()
        active_volunteers_final = [
            {"period": row[0], "count": int(row[1])}
            for row in active_volunteers
        ]

        query3 = f"""
        SELECT 
            period,
            SUM(count) OVER (ORDER BY period) AS count
        FROM (
            SELECT 
                {grouping["select"]} AS period,
                COUNT(DISTINCT u.user_id) AS count
            FROM {users} u
            JOIN {volunteer_details} vd
                ON u.user_id = vd.user_id
            WHERE vd.created_at IS NOT NULL
            {date_filter}
            GROUP BY {grouping["group_by"]}
        ) sub
        ORDER BY period ASC
        """

        cursor.execute(query3)
        total_volunteers = cursor.fetchall()
        total_volunteers_final = [
            {"period": row[0], "count": int(row[1])}
            for row in total_volunteers
        ]

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

def merge_volunteer_activity_trend(volunteer_activity_trend_virginia, volunteer_activity_trend_ireland):
    return {
        "new_volunteers": merge_period_data(
            volunteer_activity_trend_virginia.get("new_volunteers", []),
            volunteer_activity_trend_ireland.get("new_volunteers", [])
        ),
        "active_volunteers": merge_period_data(
            volunteer_activity_trend_virginia.get("active_volunteers", []),
            volunteer_activity_trend_ireland.get("active_volunteers", [])
        ),
        "total_volunteers": merge_period_data(
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


def get_volunteers_by_location( cursor, users, volunteer_details, country_table, user_skills,help_categories,country='All Countries',chart_type="Bar Chart",skill="All Skills", request_body=None):
    try:
        
        if request_body is None:
            request_body = {}

        date_filter = build_date_filter_location(request_body)
         
        query= f"""SELECT
                COALESCE(c.country_code, 'Unknown') AS country,
                COUNT(DISTINCT u.user_id) AS count
            FROM {users} u
            JOIN {volunteer_details} vd
                ON u.user_id = vd.user_id
            LEFT JOIN {country_table} c
                ON u.country_id = c.country_id
            WHERE 1=1
            {date_filter}
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

        return[
        {"country": row[0], "count": int(row[1])}
        for row in rows
        ]

    except Exception as e:
        print("Error in get_volunteers_by_location:", str(e))
        return []

def apply_local_date_filter(df, request_body, filter_type="trend"):
    df = df.copy()

    if filter_type == "trend":
        time_range = request_body.get("time_range", "All")
        start_date = request_body.get("start_date")
        end_date = request_body.get("end_date")
    else:
        time_range = request_body.get("time_range_location", "All")
        start_date = request_body.get("location_start_date")
        end_date = request_body.get("location_end_date")

    today = pd.Timestamp.today().normalize()

    if time_range == "7D":
        return df[df["created_at"] >= today - pd.Timedelta(days=7)]

    if time_range == "30D":
        return df[df["created_at"] >= today - pd.Timedelta(days=30)]

    if time_range == "1Y":
        return df[df["created_at"] >= today - pd.DateOffset(years=1)]

    if time_range == "Custom" and start_date and end_date:
        start_date = pd.to_datetime(start_date, errors="coerce")
        end_date = pd.to_datetime(end_date, errors="coerce")

        if pd.notna(start_date) and pd.notna(end_date):
            return df[
                (df["created_at"].dt.date >= start_date.date()) &
                (df["created_at"].dt.date <= end_date.date())
            ]

    return df

def get_local_volunteer_activity_trend(users_df, volunteer_details_df, request_body):
    time_range = request_body.get("time_range", "All")

    merged_df = volunteer_details_df.merge(
        users_df,
        on="user_id",
        how="inner"
    )

    merged_df = merged_df[merged_df["created_at"].notna()]
    merged_df = apply_local_date_filter(merged_df, request_body, "trend")

    if time_range in ["7D", "30D", "Custom"]:
        merged_df["period"] = merged_df["created_at"].dt.strftime("%Y-%m-%d")
    else:
        merged_df["period"] = merged_df["created_at"].dt.strftime("%Y-%m")

    new_volunteers = (
        merged_df.groupby("period")["user_id"]
        .nunique()
        .reset_index(name="count")
        .sort_values("period")
    )

    active_df = merged_df[merged_df["user_status_id"] == 1]

    active_volunteers = (
        active_df.groupby("period")["user_id"]
        .nunique()
        .reset_index(name="count")
        .sort_values("period")
    )

    total_volunteers = new_volunteers.copy()
    total_volunteers["count"] = total_volunteers["count"].cumsum()

    return {
        "new_volunteers": new_volunteers.to_dict("records"),
        "active_volunteers": active_volunteers.to_dict("records"),
        "total_volunteers": total_volunteers.to_dict("records")
    }
    
def get_local_volunteers_by_location(
    users_df,
    volunteer_details_df,
    country_df,
    user_skills_df,
    help_categories_df,
    request_body
):
    country = request_body.get("country", "All Countries")
    skill = request_body.get("skill", "All Skills")

    merged_df = volunteer_details_df.merge(
        users_df,
        on="user_id",
        how="inner"
    )

    merged_df = merged_df[merged_df["created_at"].notna()]
    merged_df = apply_local_date_filter(merged_df, request_body, "location")

    merged_df = merged_df.merge(
        country_df,
        on="country_id",
        how="left"
    )

    if country != "All Countries":
        merged_df = merged_df[
            merged_df["country_code"].astype(str).str.upper() == country.upper()
        ]

    if skill != "All Skills":
        skill_users = user_skills_df.merge(
            help_categories_df,
            on="cat_id",
            how="inner"
        )

        skill_users = skill_users[
            skill_users["cat_name"] == skill
        ]["user_id"].unique()

        merged_df = merged_df[
            merged_df["user_id"].isin(skill_users)
        ]

    location_df = (
        merged_df.groupby("country_code")["user_id"]
        .nunique()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )

    location_df["country"] = location_df["country_code"].fillna("Unknown")

    return location_df[["country", "count"]].to_dict("records")    

def run_local_test(request_body):
    try:
        users_df = pd.read_csv("sql/users.csv")
        volunteer_details_df = pd.read_csv("sql/volunteer_details.csv")
        country_df = pd.read_csv("sql/country.csv")
        user_skills_df = pd.read_csv("sql/user_skills.csv")
        help_categories_df = pd.read_csv("sql/help_category.csv")

        volunteer_details_df["created_at"] = pd.to_datetime(
            volunteer_details_df["created_at"],
            errors="coerce"
        )

        print("Local CSV files loaded successfully")

        response_data = {
            # "volunteer_activity_trend": {},
            # "volunteers_by_location": []
            "volunteer_activity_trend": get_local_volunteer_activity_trend(
                users_df,
                volunteer_details_df,
                request_body
            ),
            "volunteers_by_location": get_local_volunteers_by_location(
                users_df,
                volunteer_details_df,
                country_df,
                user_skills_df,
                help_categories_df,
                request_body
            )
        }

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps(response_data)
        }

    except Exception as e:
        print("Local test error:", str(e))

        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "volunteer_activity_trend": {
                    "new_volunteers": [],
                    "active_volunteers": [],
                    "total_volunteers": []
                },
                "volunteers_by_location": []
            })
        }    

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
    test_event = {
        "time_range": "All",
        "time_range_location": "All"
    }
    # for custom
    # test_event = {
    #     "time_range": "Custom",
    #     "start_date": "2026-05-01",
    #     "end_date": "2026-05-31",
    #     "time_range_location": "Custom",
    #     "location_start_date": "2026-05-01",
    #     "location_end_date": "2026-05-31"
    # }
    print(lambda_handler(test_event, None))
