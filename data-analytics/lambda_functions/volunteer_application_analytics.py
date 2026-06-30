import json
import psycopg2

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


def normalize_time_range(value):
    """Return a supported dashboard time range."""
    valid_ranges = {"7D", "30D", "1Y", "All", "Custom"}
    return value if value in valid_ranges else "All"


def build_created_at_filter(time_range="All", start_date=None, end_date=None):
    """Build a vd.created_at SQL condition and parameter list."""
    time_range = normalize_time_range(time_range)

    if time_range == "7D":
        return " AND vd.created_at >= CURRENT_DATE - INTERVAL '7 days'", []

    if time_range == "30D":
        return " AND vd.created_at >= CURRENT_DATE - INTERVAL '30 days'", []

    if time_range == "1Y":
        return " AND vd.created_at >= CURRENT_DATE - INTERVAL '1 year'", []

    if time_range == "Custom":
        if start_date and end_date:
            return " AND vd.created_at BETWEEN %s AND %s", [start_date, end_date]
        return "", []

    return "", []


def build_date_filter_trend(time_range="All", start_date=None, end_date=None):
    """Build the SQL condition for Volunteer Activity Trend date filtering."""
    return build_created_at_filter(time_range, start_date, end_date)


def build_date_filter_location(time_range="All", start_date=None, end_date=None):
    """Build the SQL condition for Volunteers by Location date filtering."""
    return build_created_at_filter(time_range, start_date, end_date)


def get_grouping(time_range="All"):
    """Return the SQL date truncation unit and output date format."""
    time_range = normalize_time_range(time_range)

    if time_range in {"7D", "30D", "Custom"}:
        return "day", "YYYY-MM-DD"

    return "month", "YYYY-MM"


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
        # Connects to database
        VIRGINIA_DB_CONFIG = get_db_config('Virginia')
        IRELAND_DB_CONFIG = get_db_config('Ireland')
        conn_V = psycopg2.connect(**VIRGINIA_DB_CONFIG)
        cursor_V = conn_V.cursor()
        print("Virginia database connected succcessfully.")
        conn_I = psycopg2.connect(**IRELAND_DB_CONFIG)
        cursor_I = conn_I.cursor()
        print("Ireland database connected succcessfully.")

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
     
        volunteer_activity_trend_virginia = get_volunteer_activity_trend(
            cursor_V,
            REAL_TABLE_USERS_VIRGINIA,
            REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA,
            time_range,
            start_date,
            end_date
        )
        volunteers_by_location_virginia = get_volunteers_by_location(
            cursor_V,
            REAL_TABLE_USERS_VIRGINIA,
            REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA,
            REAL_TABLE_COUNTRY_VIRGINIA,
            REAL_TABLE_USER_SKILL_VIRGINIA,
            REAL_TABLE_HELP_CATEGORIES_VIRGINIA,
            country,
            chart_type,
            skill,
            time_range_location,
            location_start_date,
            location_end_date
        )

        volunteer_activity_trend_ireland = get_volunteer_activity_trend(
            cursor_I,
            REAL_TABLE_USERS_IRELAND,
            REAL_TABLE_VOLUNTEER_DETAILS_IRELAND,
            time_range,
            start_date,
            end_date
        )
        volunteers_by_location_ireland = get_volunteers_by_location(
            cursor_I,
            REAL_TABLE_USERS_IRELAND,
            REAL_TABLE_VOLUNTEER_DETAILS_IRELAND,
            REAL_TABLE_COUNTRY_IRELAND,
            REAL_TABLE_USER_SKILLS_IRELAND,
            REAL_TABLE_HELP_CATEGORIES_IRELAND,
            country,
            chart_type,
            skill,
            time_range_location,
            location_start_date,
            location_end_date
        )

        response_data = {
            "volunteer_activity_trend": merge_volunteer_activity_trend(
                volunteer_activity_trend_virginia,
                volunteer_activity_trend_ireland
            ),
            "volunteers_by_location": merge_volunteer_by_location(
                volunteers_by_location_virginia,
                volunteers_by_location_ireland
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
        # Catches an error if connection fails
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


def get_volunteer_activity_trend(
    cursor,
    users,
    volunteer_details,
    time_range="All",
    start_date=None,
    end_date=None
):
    try:
        date_filter, params = build_date_filter_trend(time_range, start_date, end_date)
        grouping_unit, period_format = get_grouping(time_range)

        query1 = f"""
        SELECT TO_CHAR(DATE_TRUNC('{grouping_unit}', vd.created_at), '{period_format}') AS period,
               COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        {date_filter}
        GROUP BY 1
        ORDER BY 1 ASC
        """
        cursor.execute(query1, params)

        new_volunteers = cursor.fetchall()
        new_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in new_volunteers]

        query2 = f""" 
        SELECT TO_CHAR(DATE_TRUNC('{grouping_unit}', vd.created_at), '{period_format}') AS period,
               COUNT(DISTINCT u.user_id) AS count
        FROM {users} u 
        JOIN {volunteer_details} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        {date_filter}
        AND u.user_status_id = 1 
        GROUP BY 1
        ORDER BY 1 ASC
        """
        cursor.execute(query2, params)
        active_volunteers = cursor.fetchall()
        active_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in active_volunteers]

        query3 = f"""
        SELECT period, SUM(count) OVER (ORDER BY period) AS count
        FROM (
            SELECT TO_CHAR(DATE_TRUNC('{grouping_unit}', vd.created_at), '{period_format}') AS period,
                   COUNT(DISTINCT u.user_id) AS count
            FROM {users} u
            JOIN {volunteer_details} vd ON u.user_id = vd.user_id
            WHERE vd.created_at IS NOT NULL
            {date_filter}
            GROUP BY 1
        ) sub
        ORDER BY period ASC;
        """
        
        cursor.execute(query3, params)
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
        period = row['period']
        count = row['count']

        merged[period] = merged.get(period, 0) + count

    return [
        {'period': period, 'count': merged[period]}
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

    return [
        {"country": country, "count": merged[country]}
        for country in sorted(merged.keys())
    ]


def get_volunteers_by_location(
    cursor,
    users,
    volunteer_details,
    country_table,
    user_skills,
    help_categories,
    country='All Countries',
    chart_type="Bar Chart",
    skill="All Skills",
    time_range_location="All",
    location_start_date=None,
    location_end_date=None
):
    try:
        query = f"""SELECT
                COALESCE(c.country_code, 'Unknown') AS country,
                COUNT(DISTINCT u.user_id) AS count
            FROM {users} u
            JOIN {volunteer_details} vd
                ON u.user_id = vd.user_id
            LEFT JOIN {country_table} c
                ON u.country_id = c.country_id
            WHERE 1=1
            """
        
        date_filter, date_params = build_date_filter_location(
            time_range_location,
            location_start_date,
            location_end_date
        )
        query += date_filter
        params = date_params.copy()
        
        if country != "All Countries":
            query += " AND UPPER(c.country_code) = %s"
            params.append(country)

        if skill != "All Skills":
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
    import boto3

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
