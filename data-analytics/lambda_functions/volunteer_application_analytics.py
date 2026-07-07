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

# Supported time-range tokens. Anything outside this set is treated as "All".
VALID_TIME_RANGES = {"7D", "30D", "1Y", "All", "Custom"}


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


def build_date_filter_trend(time_range, start_date=None, end_date=None):
    """Return (sql_clause, params) filtering vd.created_at for the activity-trend queries.

    The clause is composable: it is either "" (no filter) or begins with " AND ..."
    so it can be appended directly after an existing WHERE predicate. Custom ranges
    use a parameterized BETWEEN to avoid SQL injection.
    """
    return _build_date_filter(time_range, start_date, end_date)


def build_date_filter_location(time_range, start_date=None, end_date=None):
    """Return (sql_clause, params) filtering vd.created_at for the by-location query.

    Same filtering logic as the trend filter, kept as a separate function so the two
    widgets stay independently wired end to end.
    """
    return _build_date_filter(time_range, start_date, end_date)


def _build_date_filter(time_range, start_date, end_date):
    if time_range == "7D":
        return " AND vd.created_at >= CURRENT_DATE - INTERVAL '7 days'", []
    if time_range == "30D":
        return " AND vd.created_at >= CURRENT_DATE - INTERVAL '30 days'", []
    if time_range == "1Y":
        return " AND vd.created_at >= CURRENT_DATE - INTERVAL '1 year'", []
    if time_range == "Custom":
        # Only apply BETWEEN when both bounds are present; otherwise no-op (All-like).
        if start_date and end_date:
            return " AND vd.created_at BETWEEN %s AND %s", [start_date, end_date]
        return "", []
    # "All" (and any unrecognized token) -> no date filter.
    return "", []


def get_grouping(time_range):
    """Grouping granularity for the activity-trend chart: 'day' or 'month'."""
    if time_range in ("7D", "30D", "Custom"):
        return "day"
    # "1Y", "All", and any unrecognized token -> monthly.
    return "month"


def _trunc_and_format(grouping):
    """Map grouping to the DATE_TRUNC unit and the TO_CHAR period format."""
    if grouping == "day":
        return "day", "YYYY-MM-DD"
    return "month", "YYYY-MM"


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

        # Independent date filters for the two widgets.
        time_range = request_body.get("time_range", "All")
        start_date = request_body.get("start_date")
        end_date = request_body.get("end_date")

        time_range_location = request_body.get("time_range_location", "All")
        location_start_date = request_body.get("location_start_date")
        location_end_date = request_body.get("location_end_date")

        volunteer_activity_trend_virginia = get_volunteer_activity_trend(
            cursor_V, REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA,
            time_range, start_date, end_date)
        volunteers_by_location_virginia =  get_volunteers_by_location(
            cursor_V, REAL_TABLE_USERS_VIRGINIA, REAL_TABLE_VOLUNTEER_DETAILS_VIRGINIA,
            REAL_TABLE_COUNTRY_VIRGINIA, REAL_TABLE_USER_SKILL_VIRGINIA,
            REAL_TABLE_HELP_CATEGORIES_VIRGINIA, country, chart_type, skill,
            time_range_location, location_start_date, location_end_date)

        volunteer_activity_trend_ireland = get_volunteer_activity_trend(
            cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND,
            time_range, start_date, end_date)
        volunteers_by_location_ireland =  get_volunteers_by_location(
            cursor_I, REAL_TABLE_USERS_IRELAND, REAL_TABLE_VOLUNTEER_DETAILS_IRELAND,
            REAL_TABLE_COUNTRY_IRELAND, REAL_TABLE_USER_SKILLS_IRELAND,
            REAL_TABLE_HELP_CATEGORIES_IRELAND, country, chart_type, skill,
            time_range_location, location_start_date, location_end_date)

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


def get_volunteer_activity_trend(cursor, users, volunteer_details,
                                 time_range="All", start_date=None, end_date=None):
    try:
        grouping = get_grouping(time_range)
        trunc_unit, period_fmt = _trunc_and_format(grouping)
        date_clause, date_params = build_date_filter_trend(time_range, start_date, end_date)

        # new_volunteers: distinct volunteers whose record was created in each period.
        query1 = f"""SELECT TO_CHAR(DATE_TRUNC('{trunc_unit}', vd.created_at), '{period_fmt}') AS period,
        COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL{date_clause}
        GROUP BY 1
        ORDER BY 1 ASC"""
        cursor.execute(query1, date_params)
        new_volunteers = cursor.fetchall()
        new_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in new_volunteers]

        # active_volunteers: same, restricted to active users (user_status_id = 1).
        query2 = f"""
        SELECT TO_CHAR(DATE_TRUNC('{trunc_unit}', vd.created_at), '{period_fmt}') AS period,
        COUNT(DISTINCT u.user_id) AS count FROM {users} u
        JOIN {volunteer_details} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL{date_clause}
        AND u.user_status_id = 1
        GROUP BY 1
        ORDER BY 1 ASC
        """
        cursor.execute(query2, date_params)
        active_volunteers = cursor.fetchall()
        active_volunteers_final = [{"period": row[0], "count": int(row[1])} for row in active_volunteers]

        # total_volunteers: cumulative running count across periods (within the filtered window).
        query3 = f"""
        SELECT period, SUM(count) OVER (ORDER BY period) AS count
        FROM ( SELECT TO_CHAR(DATE_TRUNC('{trunc_unit}', vd.created_at), '{period_fmt}') AS period,
        COUNT(DISTINCT u.user_id) AS count
        FROM {users} u
        JOIN {volunteer_details} vd
        ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL{date_clause}
        GROUP BY 1 ) sub
        ORDER BY period ASC;
        """
        cursor.execute(query3, date_params)
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


def get_volunteers_by_location(cursor, users, volunteer_details, country_table, user_skills,
                               help_categories, country='All Countries', chart_type="Bar Chart",
                               skill="All Skills", time_range="All",
                               start_date=None, end_date=None):
    try:
        # Date filter is applied ONLY. Country aggregation, country/skill filters, and the
        # response shape are left exactly as they were.
        date_clause, date_params = build_date_filter_location(time_range, start_date, end_date)

        query= f"""SELECT
                COALESCE(c.country_code, 'Unknown') AS country,
                COUNT(DISTINCT u.user_id) AS count
            FROM {users} u
            JOIN {volunteer_details} vd
                ON u.user_id = vd.user_id
            LEFT JOIN {country_table} c
                ON u.country_id = c.country_id
            WHERE 1=1{date_clause}
            """

        # params must follow the order the %s placeholders appear in the query:
        # date filter first, then country, then skill.
        params = list(date_params)

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
