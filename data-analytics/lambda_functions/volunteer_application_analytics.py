# TODO: Implement build_date_filter_trend()
# TODO: Implement get_grouping()
# TODO: Implement build_date_filter_location()
# TODO: Update get_volunteer_activity_trend()
# TODO: Update get_volunteers_by_location()

#CREATED by NITISH
def build_date_filter_trend(time_range, start_date=None, end_date=None):
    """
    Builds the SQL WHERE clause for Volunteer Activity Trend based on time_range.
    """

    if time_range == "7D":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '7 days'"

    elif time_range == "30D":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '30 days'"

    elif time_range == "1Y":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '1 year'"

    elif time_range == "All":
        return ""   # No date filter

    elif time_range == "Custom":
        if not start_date or not end_date:
            return ""  # Safety fallback
        return f"vd.created_at BETWEEN '{start_date}' AND '{end_date}'"

    else:
        return ""  # Default fallback
#CREATED by NITISH
def get_grouping(time_range):
    """
    Determines grouping logic (daily or monthly) for Volunteer Activity Trend.
    """

    if time_range in ["7D", "30D"]:
        return "daily"

    elif time_range in ["1Y", "All"]:
        return "monthly"

    elif time_range == "Custom":
        return "daily"

    else:
        return "daily"  # Safe fallback
    
#CREATED by NITISH
def build_date_filter_location(time_range_location, location_start_date=None, location_end_date=None):
    """
    Builds the SQL WHERE clause for Volunteers by Location based on time_range_location.
    """

    if time_range_location == "7D":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '7 days'"

    elif time_range_location == "30D":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '30 days'"

    elif time_range_location == "1Y":
        return "vd.created_at >= CURRENT_DATE - INTERVAL '1 year'"

    elif time_range_location == "All":
        return ""   # No date filter

    elif time_range_location == "Custom":
        if not location_start_date or not location_end_date:
            return ""  # Safety fallback
        return f"vd.created_at BETWEEN '{location_start_date}' AND '{location_end_date}'"

    else:
        return ""  # Default fallback


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

def get_db_connection():
    DB_CONFIG = {
        "host": "localhost",
        "port": "5432",
        "dbname": "Saayam_Local",
        "user": "postgres",
        "password": "postgres"
    }
    return psycopg2.connect(**DB_CONFIG)


#NITISH
def lambda_handler(event, context):
    """
    Main handler for Volunteer Analytics API.
    """

    try:
        # Connect to DB
        conn = get_db_connection()

        # 1️⃣ Extract TREND parameters
        trend_data = event.get("trend", {})
        time_range = trend_data.get("time_range")
        start_date = trend_data.get("start_date")
        end_date = trend_data.get("end_date")

        # 2️⃣ Extract LOCATION parameters
        location_data = event.get("location", {})
        time_range_location = location_data.get("time_range_location")
        location_start_date = location_data.get("location_start_date")
        location_end_date = location_data.get("location_end_date")

        # 3️⃣ Call TREND function
        trend_result = get_volunteer_activity_trend(
            conn,
            time_range,
            start_date,
            end_date
        )

        # 4️⃣ Call LOCATION function
        location_result = get_volunteers_by_location(
            conn,
            time_range_location,
            location_start_date,
            location_end_date
        )

        conn.close()

        # 5️⃣ Final response
        return {
            "statusCode": 200,
            "body": {
                "trend": trend_result,
                "location": location_result
            }
        }

    except Exception as e:
        print("Error in lambda_handler:", str(e))
        return {
            "statusCode": 500,
            "body": {"error": str(e)}
        }

#NITISH
def get_volunteer_activity_trend(conn, time_range, start_date=None, end_date=None):
    """
    Returns volunteer activity trend: new, active, total volunteers grouped by period.
    """

    cursor = conn.cursor()

    # 1️⃣ Build date filter
    date_filter = build_date_filter_trend(time_range, start_date, end_date)

    # 2️⃣ Determine grouping (daily or monthly)
    grouping = get_grouping(time_range)

    # 3️⃣ Build GROUP BY expression
    if grouping == "daily":
        period_expr = "DATE(vd.created_at)"
    else:  # monthly
        period_expr = "TO_CHAR(vd.created_at, 'YYYY-MM')"

    # 4️⃣ Build WHERE clause
    where_clause = f"WHERE {date_filter}" if date_filter else ""

    # 5️⃣ SQL for NEW volunteers
    new_volunteers_query = f"""
        SELECT {period_expr} AS period, COUNT(*) AS count
        FROM volunteer_details vd
        {where_clause}
        GROUP BY period
        ORDER BY period;
    """

    # 6️⃣ SQL for ACTIVE volunteers
    active_volunteers_query = f"""
        SELECT {period_expr} AS period, COUNT(DISTINCT vd.user_id) AS count
        FROM volunteer_details vd
        {where_clause}
        GROUP BY period
        ORDER BY period;
    """

    # 7️⃣ SQL for TOTAL volunteers
    total_volunteers_query = f"""
        SELECT {period_expr} AS period, COUNT(*) AS count
        FROM volunteer_details vd
        {where_clause}
        GROUP BY period
        ORDER BY period;
    """

    # 8️⃣ Execute queries
    cursor.execute(new_volunteers_query)
    new_volunteers = [{"period": str(row[0]), "count": row[1]} for row in cursor.fetchall()]

    cursor.execute(active_volunteers_query)
    active_volunteers = [{"period": str(row[0]), "count": row[1]} for row in cursor.fetchall()]

    cursor.execute(total_volunteers_query)
    total_volunteers = [{"period": str(row[0]), "count": row[1]} for row in cursor.fetchall()]

    cursor.close()

    # 9️⃣ Final output
    return {
        "new_volunteers": new_volunteers,
        "active_volunteers": active_volunteers,
        "total_volunteers": total_volunteers
    }

def merge_monthly_data(list1, list2):
    merged= {}
    for row in list1 + list2 : 
        month = row['month']
        count = row['count']

        merged[month] = merged.get(month,0) + count

    return [
        {'month': month, 'count': merged[month]}
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
def merge_volunteer_by_location(list1, list2): 
    merged = {} 
    for row in list1 + list2:
        country = row["country"] 
        count = row["count"] 
        merged[country] = merged.get(country, 0) + count 
    return [ {"country": country, "count": merged[country]} for country in sorted(merged.keys()) ]

#NITISH
def get_volunteers_by_location(conn, time_range_location, location_start_date=None, location_end_date=None):
    """
    Returns volunteer count grouped by country with optional date filtering.
    """

    cursor = conn.cursor()

    # 1️⃣ Build date filter
    date_filter = build_date_filter_location(time_range_location, location_start_date, location_end_date)

    # 2️⃣ Build WHERE clause
    where_clause = f"WHERE {date_filter}" if date_filter else ""

    # 3️⃣ SQL query
    query = f"""
        SELECT 
            COALESCE(vd.country, 'UNKNOWN') AS country,
            COUNT(*) AS count
        FROM volunteer_details vd
        {where_clause}
        GROUP BY country
        ORDER BY count DESC;
    """

    # 4️⃣ Execute query
    cursor.execute(query)
    rows = cursor.fetchall()

    cursor.close()

    # 5️⃣ Format output
    return [{"country": row[0], "count": int(row[1])} for row in rows]


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
    


  
