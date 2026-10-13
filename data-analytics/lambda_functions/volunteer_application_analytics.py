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

def lambda_handler(event, context):
    conn_V = None
    cursor_V = None
    conn_I = None
    cursor_I = None

    safe_response = {
        "7D": {"volunteer_activity_trend": {"new_volunteers": [], "active_volunteers": [], "total_volunteers": []}, "volunteers_by_location": []},
        "30D": {"volunteer_activity_trend": {"new_volunteers": [], "active_volunteers": [], "total_volunteers": []}, "volunteers_by_location": []},
        "1Y": {"volunteer_activity_trend": {"new_volunteers": [], "active_volunteers": [], "total_volunteers": []}, "volunteers_by_location": []},
        "All": {"volunteer_activity_trend": {"new_volunteers": [], "active_volunteers": [], "total_volunteers": []}, "volunteers_by_location": []},
        "Custom": {"volunteer_activity_trend": {"new_volunteers": [], "active_volunteers": [], "total_volunteers": []}, "volunteers_by_location": []}
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

        start_date = request_body.get("start_date", None)
        end_date = request_body.get("end_date", None)
        start_date_loc = request_body.get("location_start_date", None)
        end_date_loc = request_body.get("location_end_date", None)

        # --- Custom activity call ---
        if start_date and end_date:
            vat_Custom = get_volunteer_activity_by_time_range_VI_combined(cursor_V, cursor_I, "Custom", start_date, end_date)
            response_data = {
                "Custom": {
                    "volunteer_activity_trend": vat_Custom,
                    "volunteers_by_location": []
                }
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

        # --- Custom location call ---
        if start_date_loc and end_date_loc:
            vbl_Custom = get_volunteer_locations_by_time_range_VI_combined(cursor_V, cursor_I, country, chart_type, skill, "Custom", start_date_loc, end_date_loc)
            response_data = {
                "Custom": {
                    "volunteer_activity_trend": {"new_volunteers": [], "active_volunteers": [], "total_volunteers": []},
                    "volunteers_by_location": vbl_Custom
                }
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

        # --- Consolidated call: {} ---
        vat_7D = get_volunteer_activity_by_time_range_VI_combined(cursor_V, cursor_I, "7D")
        vbl_7D = get_volunteer_locations_by_time_range_VI_combined(cursor_V, cursor_I, country, chart_type, skill, "7D")

        vat_30D = get_volunteer_activity_by_time_range_VI_combined(cursor_V, cursor_I, "30D")
        vbl_30D = get_volunteer_locations_by_time_range_VI_combined(cursor_V, cursor_I, country, chart_type, skill, "30D")

        vat_1Y = get_volunteer_activity_by_time_range_VI_combined(cursor_V, cursor_I, "1Y")
        vbl_1Y = get_volunteer_locations_by_time_range_VI_combined(cursor_V, cursor_I, country, chart_type, skill, "1Y")

        vat_All = get_volunteer_activity_by_time_range_VI_combined(cursor_V, cursor_I, "All")
        vbl_All = get_volunteer_locations_by_time_range_VI_combined(cursor_V, cursor_I, country, chart_type, skill, "All")

        response_data = {
            "7D": {"volunteer_activity_trend": vat_7D, "volunteers_by_location": vbl_7D},
            "30D": {"volunteer_activity_trend": vat_30D, "volunteers_by_location": vbl_30D},
            "1Y": {"volunteer_activity_trend": vat_1Y, "volunteers_by_location": vbl_1Y},
            "All": {"volunteer_activity_trend": vat_All, "volunteers_by_location": vbl_All},
            "Custom": {
                "volunteer_activity_trend": {"new_volunteers": [], "active_volunteers": [], "total_volunteers": []},
                "volunteers_by_location": []
            }
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
        if cursor_V: cursor_V.close()
        if conn_V: conn_V.close()
        print("Virginia Database connection closed")
        if cursor_I: cursor_I.close()
        if conn_I: conn_I.close()
        print("Ireland Database connection closed")

def get_volunteer_activity_by_time_range_VI_combined(cursor_V, cursor_I, time_range, start_date=None, end_date=None):
    """
    Fetches volunteer activity trend data for both Virginia and Ireland databases, merges the results, and returns the combined data.
    """
    volunteer_activity_trend_virginia = get_volunteer_activity_trend(cursor_V, REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA, time_range, start_date, end_date)
    volunteer_activity_trend_ireland = get_volunteer_activity_trend(cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND, time_range, start_date, end_date)

    vat = merge_volunteer_activity_trend(volunteer_activity_trend_virginia, volunteer_activity_trend_ireland)
    return vat

def get_volunteer_locations_by_time_range_VI_combined(cursor_V, cursor_I, country, chart_type, skill, time_range_loc, location_start_date=None, location_end_date=None):
    """
    Fetches volunteer location data for both Virginia and Ireland databases, merges the results, and returns
    the combined data.
    """
    volunteers_by_location_virginia = get_volunteers_by_location(cursor_V,REAL_TABLE_USERS_VIRGINIA,REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA,REAL_TABLE_COUNTRY_VIRGINIA,REAL_TABLE_USER_SKILL_VIRGINIA,REAL_TABLE_HELP_CATEGORIES_VIRGINIA, country, chart_type, skill, time_range_loc, location_start_date, location_end_date)
    volunteers_by_location_ireland = get_volunteers_by_location(cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND, REAL_TABLE_COUNTRY_IRELAND, REAL_TABLE_USER_SKILLS_IRELAND, REAL_TABLE_HELP_CATEGORIES_IRELAND,country, chart_type,skill, time_range_loc, location_start_date, location_end_date)

    vbl = merge_volunteer_by_location(volunteers_by_location_virginia, volunteers_by_location_ireland)
    return vbl

def get_grouping(time_range):
    
    period = ""
    date_string = ""

    if time_range == '7D':
        period = "day"
        date_string = "YYYY-MM-DD"
    elif time_range == '30D':
        period = "day"
        date_string = "YYYY-MM-DD"
    elif time_range == '1Y':
        period = "month"
        date_string = "YYYY-MM"
    elif time_range == 'All':
        period = "month"
        date_string = "YYYY-MM"
    elif time_range == 'Custom':
        period = "day"
        date_string = "YYYY-MM-DD"
    else:
        raise ValueError("Invalid time range. Must be one of: '7D', '30D', '1Y', or 'Custom'.")

    return period, date_string

def build_date_filter_trend(time_range, start_date=None, end_date=None):
    where_clause = ""
    params = ()

    if time_range == '7D':
        where_clause = "AND vd.created_at >= CURRENT_DATE - INTERVAL '7 days'"
    elif time_range == '30D':
        where_clause = "AND vd.created_at >= CURRENT_DATE - INTERVAL '30 days'"
    elif time_range == '1Y':
        where_clause = "AND vd.created_at >= CURRENT_DATE - INTERVAL '1 year'"
    elif time_range == 'All':
        where_clause = ""
    elif time_range == 'Custom':
        if start_date and end_date:
            where_clause = f"AND vd.created_at BETWEEN %s AND %s"
            params = (start_date, end_date)
        elif start_date:
            where_clause = f"AND vd.created_at >= %s"
            params = (start_date,)
        elif end_date:
            where_clause = f"AND vd.created_at <= %s"
            params = (end_date,)

    return where_clause, params

def build_date_filter_location(time_range, start_date=None, end_date=None):
    where_clause = ""
    params = ()

    if time_range == '7D':
        where_clause = "AND vd.created_at >= CURRENT_DATE - INTERVAL '7 days'"
    elif time_range == '30D':
        where_clause = "AND vd.created_at >= CURRENT_DATE - INTERVAL '30 days'"
    elif time_range == '1Y':
        where_clause = "AND vd.created_at >= CURRENT_DATE - INTERVAL '1 year'"
    elif time_range == 'All':
        where_clause = ""
    elif time_range == 'Custom':
        if start_date and end_date:
            where_clause = f"AND vd.created_at BETWEEN %s AND %s"
            params = (start_date, end_date)
        elif start_date:
            where_clause = f"AND vd.created_at >= %s"
            params = (start_date,)
        elif end_date:
            where_clause = f"AND vd.created_at <= %s"
            params = (end_date,)

    return where_clause, params



def get_volunteer_activity_trend(cursor, users, volunteer_details, time_range='All', start_date=None, end_date=None):
    period, date_string = get_grouping(time_range)
    date_where_clause, params = build_date_filter_trend(time_range, start_date, end_date)

    try:
        query1 = f"""
            SELECT TO_CHAR(DATE_TRUNC('{period}', vd.created_at), '{date_string}') AS period,
            COUNT(DISTINCT u.user_id) AS count 
            FROM {users} u 
            JOIN {volunteer_details} vd ON u.user_id = vd.user_id 
            WHERE vd.created_at IS NOT NULL 
            {date_where_clause}
            GROUP BY 1 
            ORDER BY 1 ASC
        """
        cursor.execute(query1, params)
        new_volunteers = cursor.fetchall()
        new_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in new_volunteers]

        query2 = f"""
            SELECT TO_CHAR(DATE_TRUNC('{period}', vd.created_at), '{date_string}') AS period,
            COUNT(DISTINCT u.user_id) AS count 
            FROM {users} u 
            JOIN {volunteer_details} vd ON u.user_id = vd.user_id
            WHERE vd.created_at IS NOT NULL
            AND u.user_status_id = 1 
            {date_where_clause}
            GROUP BY 1
            ORDER BY 1 ASC
        """
        cursor.execute(query2, params)
        active_volunteers = cursor.fetchall()
        active_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in active_volunteers]

        if time_range == "Custom":
            query3 = f"""
                SELECT period, base_count + SUM(count) OVER (ORDER BY period) AS count
                FROM (
                    SELECT 
                        TO_CHAR(DATE_TRUNC('{period}', vd.created_at), '{date_string}') AS period,
                        COUNT(DISTINCT u.user_id) AS count,
                        (SELECT COUNT(DISTINCT u2.user_id) 
                         FROM {users} u2
                         JOIN {volunteer_details} vd2 ON u2.user_id = vd2.user_id
                         WHERE vd2.created_at::date < %s) AS base_count
                    FROM {users} u
                    JOIN {volunteer_details} vd ON u.user_id = vd.user_id
                    WHERE vd.created_at IS NOT NULL
                    AND vd.created_at::date BETWEEN %s AND %s
                    GROUP BY 1, base_count
                ) sub
                ORDER BY period ASC;
            """
            query3_params = (start_date, start_date, end_date)
        else:
            query3 = f"""
                SELECT period, SUM(count) OVER (ORDER BY period) AS count
                FROM (
                    SELECT TO_CHAR(DATE_TRUNC('{period}', vd.created_at), '{date_string}') AS period,
                    COUNT(DISTINCT u.user_id) AS count
                    FROM {users} u
                    JOIN {volunteer_details} vd ON u.user_id = vd.user_id
                    WHERE vd.created_at IS NOT NULL
                    {date_where_clause}
                    GROUP BY 1
                ) sub
                ORDER BY period ASC;
            """
            query3_params = params

        cursor.execute(query3, query3_params)
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

def merge_periodic_data(list1, list2):
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
        "new_volunteers": merge_periodic_data(
            volunteer_activity_trend_virginia.get("new_volunteers", []),
            volunteer_activity_trend_ireland.get("new_volunteers", [])
        ),
        "active_volunteers": merge_periodic_data(
            volunteer_activity_trend_virginia.get("active_volunteers", []),
            volunteer_activity_trend_ireland.get("active_volunteers", [])
        ),
        "total_volunteers": merge_periodic_data(
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


def get_volunteers_by_location(cursor, users, volunteer_details, country_table, user_skills,help_categories,country='All Countries',chart_type="Bar Chart",skill="All Skills", time_range='All', start_date=None, end_date=None):
    date_where_clause, date_params = build_date_filter_location(time_range, start_date, end_date) # date_params is a tuple here
    
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
        
        if time_range != 'All':
            query += f" {date_where_clause}"
            params.extend(date_params) # params is a list, date_params is a tuple, so we extend the list with the tuple
        
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