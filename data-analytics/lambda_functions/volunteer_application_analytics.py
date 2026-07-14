import json
import psycopg2
import boto3
import pandas as pd
import os

LOCAL_DB_TEST = True

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

        country = event.get("country", "All Countries")
        chart_type = event.get("chart_type", "Bar Chart")
        skill = event.get("skill", "All Skills")
        time_range = event.get("time_range", "All")
        start_date = event.get("start_date")
        end_date = event.get("end_date")

        time_range_location = event.get("time_range_location", "All")
        location_start_date = event.get("location_start_date")
        location_end_date = event.get("location_end_date")
     
        volunteer_activity_trend_virginia = get_volunteer_activity_trend(
    cursor_V,
    REAL_TABLE_USERS_VIRGINIA,
    REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA,
    time_range,
    start_date,
    end_date
)
        volunteers_by_location_virginia =  get_volunteers_by_location(cursor_V,REAL_TABLE_USERS_VIRGINIA,REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA,REAL_TABLE_COUNTRY_VIRGINIA,REAL_TABLE_USER_SKILL_VIRGINIA,REAL_TABLE_HELP_CATEGORIES_VIRGINIA,country,chart_type,skill,time_range_location,location_start_date,location_end_date)
        volunteer_activity_trend_ireland = get_volunteer_activity_trend(cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND)
        volunteers_by_location_ireland =  get_volunteers_by_location(cursor_I,REAL_TABLE_USERS_IRELAND,REAL_TABLE_VOLUNTEER_DETAILS_IRELAND,REAL_TABLE_COUNTRY_IRELAND,REAL_TABLE_USER_SKILLS_IRELAND,REAL_TABLE_HELP_CATEGORIES_IRELAND,country,chart_type,skill,time_range_location,location_start_date,location_end_date)

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
   
def run_local_test(request_body):
    try:

        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        SQL_DIR = os.path.join(BASE_DIR, "..", "sql")

        users_df = pd.read_csv(os.path.join(SQL_DIR, "users.csv"))
        volunteer_details_df = pd.read_csv(os.path.join(SQL_DIR, "volunteer_details.csv"))
        country_df = pd.read_csv(os.path.join(SQL_DIR, "country.csv"))
        user_skills_df = pd.read_csv(os.path.join(SQL_DIR, "user_skills.csv"))
        help_categories_df = pd.read_csv(os.path.join(SQL_DIR, "help_category.csv"))

        volunteer_details_df["created_at"] = pd.to_datetime(
            volunteer_details_df["created_at"],
            errors="coerce"
        )

        print("CSV files loaded successfully")

        response = {
            "volunteer_activity_trend": generate_local_activity_trend(
            users_df,
            volunteer_details_df,
            request_body
        ),

        "volunteers_by_location": generate_local_location_summary(
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
            "body": json.dumps(response)
        }

    except Exception as e:
        print("Local Test Error:", e)

        return {
            "statusCode": 500,
            "body": json.dumps({
                "volunteer_activity_trend": {
                    "new_volunteers": [],
                    "active_volunteers": [],
                    "total_volunteers": []
                },
                "volunteers_by_location": []
            })
        }

def filter_dataframe_by_date(dataframe, request_data, mode="trend"):
    filtered_df = dataframe.copy()

    if mode == "trend":
        selected_range = request_data.get("time_range", "All")
        from_date = request_data.get("start_date")
        to_date = request_data.get("end_date")
    else:
        selected_range = request_data.get("time_range_location", "All")
        from_date = request_data.get("location_start_date")
        to_date = request_data.get("location_end_date")

    current_day = pd.Timestamp.today().normalize()

    if selected_range == "7D":
        return filtered_df[
            filtered_df["created_at"] >= current_day - pd.Timedelta(days=7)
        ]

    elif selected_range == "30D":
        return filtered_df[
            filtered_df["created_at"] >= current_day - pd.Timedelta(days=30)
        ]

    elif selected_range == "1Y":
        return filtered_df[
            filtered_df["created_at"] >= current_day - pd.DateOffset(years=1)
        ]

    elif selected_range == "Custom" and from_date and to_date:
        from_date = pd.to_datetime(from_date, errors="coerce")
        to_date = pd.to_datetime(to_date, errors="coerce")

        if pd.notna(from_date) and pd.notna(to_date):
            return filtered_df[
                (filtered_df["created_at"].dt.date >= from_date.date()) &
                (filtered_df["created_at"].dt.date <= to_date.date())
            ]

    return filtered_df

def generate_local_activity_trend(users_data, volunteer_data, request_data):

    combined_df = volunteer_data.merge(
        users_data,
        on="user_id",
        how="inner"
    )

    combined_df = combined_df[combined_df["created_at"].notna()]
    combined_df = filter_dataframe_by_date(
        combined_df,
        request_data,
        "trend"
    )

    selected_range = request_data.get("time_range", "All")

    if selected_range in ["7D", "30D", "Custom"]:
        combined_df["period"] = combined_df["created_at"].dt.strftime("%Y-%m-%d")
    else:
        combined_df["period"] = combined_df["created_at"].dt.strftime("%Y-%m")

    new_users = (
        combined_df.groupby("period")["user_id"]
        .nunique()
        .reset_index(name="count")
        .sort_values("period")
    )

    active_users = (
        combined_df[combined_df["user_status_id"] == 1]
        .groupby("period")["user_id"]
        .nunique()
        .reset_index(name="count")
        .sort_values("period")
    )

    cumulative_users = new_users.copy()
    cumulative_users["count"] = cumulative_users["count"].cumsum()

    return {
        "new_volunteers": new_users.to_dict("records"),
        "active_volunteers": active_users.to_dict("records"),
        "total_volunteers": cumulative_users.to_dict("records")
    }

def generate_local_location_summary(
    users_data,
    volunteer_data,
    country_data,
    skills_data,
    category_data,
    request_data
):

    selected_country = request_data.get("country", "All Countries")
    selected_skill = request_data.get("skill", "All Skills")

    location_df = volunteer_data.merge(
        users_data,
        on="user_id",
        how="inner"
    )

    location_df = location_df[
        location_df["created_at"].notna()
    ]

    location_df = filter_dataframe_by_date(
        location_df,
        request_data,
        "location"
    )

    location_df = location_df.merge(
        country_data,
        on="country_id",
        how="left"
    )

    if selected_country != "All Countries":
        location_df = location_df[
            location_df["country_code"].astype(str).str.upper()
            == selected_country.upper()
        ]

    if selected_skill != "All Skills":

        eligible_users = (
            skills_data.merge(
                category_data,
                on="cat_id",
                how="inner"
            )
        )

        eligible_users = eligible_users[
            eligible_users["cat_name"] == selected_skill
        ]["user_id"].unique()

        location_df = location_df[
            location_df["user_id"].isin(eligible_users)
        ]

    summary = (
        location_df.groupby("country_code")["user_id"]
        .nunique()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )

    summary["country"] = summary["country_code"].fillna("Unknown")

    return summary[["country", "count"]].to_dict("records")    

def build_date_filter_trend(time_range, start_date=None, end_date=None):

    if time_range == "7D":
        return "AND vd.created_at >= CURRENT_DATE - INTERVAL '7 days'"

    elif time_range == "30D":
        return "AND vd.created_at >= CURRENT_DATE - INTERVAL '30 days'"

    elif time_range == "1Y":
        return "AND vd.created_at >= CURRENT_DATE - INTERVAL '1 year'"

    elif time_range == "Custom" and start_date and end_date:
        return f"AND vd.created_at BETWEEN '{start_date}' AND '{end_date}'"

    return ""

def get_grouping(time_range):

    if time_range in ["7D", "30D", "Custom"]:
        return "day"

    return "month"

def get_volunteer_activity_trend(
    cursor,
    users,
    volunteer_details,
    time_range,
    start_date=None,
    end_date=None
):
    date_filter = build_date_filter_trend(
    time_range,
    start_date,
    end_date
)
    grouping = get_grouping(time_range) 
    if grouping == "day":
        period = "TO_CHAR(vd.created_at,'YYYY-MM-DD')"
    else:
        period = "TO_CHAR(DATE_TRUNC('month',vd.created_at),'YYYY-MM')"
    try: 
        query1 = f"""
        SELECT
        {period} AS period,
        COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd
        ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        {date_filter}
        GROUP BY 1
        ORDER BY 1 ASC
        """
        cursor.execute(query1)

    
        new_volunteers = cursor.fetchall()
        new_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in new_volunteers]

        query2 = f""" 
        SELECT {period} AS month,
        COUNT(DISTINCT u.user_id) AS count FROM {users} u 
        JOIN {volunteer_details} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        AND u.user_status_id = 1 
        GROUP BY 1
        ORDER BY 1 ASC
        """
        cursor.execute(query2)
        active_volunteers = cursor.fetchall()
        active_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in active_volunteers]

        query3 = f"""
        SELECT period, SUM(count) OVER (ORDER BY period)
        FROM ( SELECT {period} AS month,
        COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd
        ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        GROUP BY 1 ) sub
        ORDER BY month ASC;
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
        for month in sorted(merged.keys())] 

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
def build_date_filter_location(
    time_range,
    start_date=None,
    end_date=None
):

    if time_range == "7D":
        return "AND vd.created_at >= CURRENT_DATE - INTERVAL '7 days'"

    elif time_range == "30D":
        return "AND vd.created_at >= CURRENT_DATE - INTERVAL '30 days'"

    elif time_range == "1Y":
        return "AND vd.created_at >= CURRENT_DATE - INTERVAL '1 year'"

    elif time_range == "Custom" and start_date and end_date:
        return f"AND vd.created_at BETWEEN '{start_date}' AND '{end_date}'"

    return ""

def merge_volunteer_by_location(list1, list2): 
    merged = {} 
    for row in list1 + list2:
        country = row["country"] 
        count = row["count"] 
        merged[country] = merged.get(country, 0) + count 
    return [ {"country": country, "count": merged[country]} for country in sorted(merged.keys()) ]


def get_volunteers_by_location( cursor, users, volunteer_details, country_table, user_skills,help_categories,country='All Countries',chart_type="Bar Chart",skill="All Skills",time_range="All", start_date=None, end_date=None):
    try: 
        date_filter = build_date_filter_location(
    time_range,
    start_date,
    end_date
)
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
    test_event = {}
    print(lambda_handler(test_event, None))
    


  
