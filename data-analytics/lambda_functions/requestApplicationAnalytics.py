import json
import boto3
import psycopg2
from datetime import date, datetime


# CORS headers — required for the response to be consumed by the webapp.
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
    #"Access-Control-Allow-Headers": "Content-Type",
    #"Access-Control-Allow-Methods": "GET,POST,OPTIONS",
}


def json_serializer(obj):
    """Handle date/datetime serialization for JSON output."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def get_db_config(db):
    """Fetch DB credentials from AWS Systems Manager Parameter Store.

    Uses the same shared parameter as the other analytics Lambdas so the
    credential format/naming stays consistent across the team.
    """
    ssm = boto3.client("ssm", region_name="us-east-1")

    if db == "Virginia":
        response = ssm.get_parameter(
            Name="/dev/saayam/db/Virginia/Analytics/user",
            WithDecryption=True,
        )
    else:
        return None

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
        "password": password,
    }


def lambda_handler(event, context):

    DB_CONFIG = get_db_config("Virginia")

    SCHEMA = "virginia_dev_saayam_rdbms"
    TABLE_REQUEST = f"{SCHEMA}.request"
    TABLE_USERS = f"{SCHEMA}.users"
    TABLE_COUNTRY = f"{SCHEMA}.country"
    TABLE_CATEGORY = f"{SCHEMA}.help_categories"

    conn = None
    cursor = None

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # -------------------------------------------------------
        # 1. Request Volume Trend
        # -------------------------------------------------------
        def get_request_volume_trend(interval, group_by="day"):
            """Return request counts grouped by day or month over a given interval.

            Aggregation is done in SQL via DATE_TRUNC() + COUNT(*) so no
            data is pulled into Python for grouping.
            """
            try:
                cursor.execute(f"SELECT count(*) FROM {TABLE_REQUEST}")
                result = cursor.fetchone()[0]
                print("num requests", result)
                trunc_unit = "month" if group_by == "month" else "day"

                if type(interval) == str:
                    query = f"""
                        SELECT DATE_TRUNC(%s, submission_date) AS date,
                            COUNT(*) AS count
                        FROM {TABLE_REQUEST}
                        WHERE submission_date > CURRENT_TIMESTAMP - INTERVAL %s
                        AND submission_date IS NOT NULL
                        GROUP BY DATE_TRUNC(%s, submission_date)
                        ORDER BY date
                    """
                    cursor.execute(query, (trunc_unit, interval, trunc_unit))
                
                else:
                    start_date, end_date = interval
                    query = f"""
                        SELECT DATE_TRUNC(%s, submission_date) AS date,
                            COUNT(*) AS count
                        FROM {TABLE_REQUEST}
                        WHERE submission_date BETWEEN %s AND %s
                        AND submission_date IS NOT NULL
                        GROUP BY DATE_TRUNC(%s, submission_date)
                        ORDER BY date
                    """
                    cursor.execute(query, (trunc_unit, start_date, end_date, trunc_unit))
                
                rows = cursor.fetchall()
            except Exception:
                return []

            if not rows:
                return []

            return [
                {"date": row[0].isoformat(), "count": row[1]}
                for row in rows
            ]

        # -------------------------------------------------------
        # 2. Requests by Category and Region
        # -------------------------------------------------------
        def get_requests_by_category_region(filter_category=None, filter_country=None, sort_by="count", interval = "7 days"):
            """Return request counts grouped by category and country, with optional filters."""
            try:
                query = f"""
                    SELECT cat.cat_name, c.country_code, COUNT(*) AS count
                    FROM {TABLE_REQUEST} r
                    INNER JOIN {TABLE_USERS} u ON r.req_user_id = u.user_id
                    INNER JOIN {TABLE_COUNTRY} c ON u.country_id = c.country_id
                    INNER JOIN {TABLE_CATEGORY} cat ON r.req_cat_id = cat.cat_id
                    WHERE c.country_code IS NOT NULL
                      AND cat.cat_name IS NOT NULL
                      AND r.submission_date > CURRENT_TIMESTAMP - INTERVAL '{interval}'
                """
                params = []
                if filter_category:
                    query += " AND cat.cat_name = %s"
                    params.append(filter_category)
                if filter_country:
                    query += " AND UPPER(c.country_code) = %s"
                    params.append(filter_country)

                query += " GROUP BY cat.cat_name, c.country_code"

                if sort_by == "category":
                    query += " ORDER BY cat.cat_name"
                elif sort_by == "country":
                    query += " ORDER BY c.country_code"
                else:
                    query += " ORDER BY count DESC"

                cursor.execute(query, params if params else None)
                rows = cursor.fetchall()
            except Exception:
                return []

            if not rows:
                return []

            return [
                {"category": row[0], "country": row[1], "count": row[2]}
                for row in rows
            ]

        # -------------------------------------------------------
        # 3. Top 5 Countries by Request Volume
        # -------------------------------------------------------
        def get_top_countries(interval):
            """Return top 5 countries ranked by total request count."""
            try:
                query = f"""
                    SELECT c.country_code, COUNT(*) AS count
                    FROM {TABLE_REQUEST} r
                    INNER JOIN {TABLE_USERS} u ON r.req_user_id = u.user_id
                    INNER JOIN {TABLE_COUNTRY} c ON u.country_id = c.country_id
                    WHERE c.country_code IS NOT NULL AND r.submission_date > CURRENT_TIMESTAMP - INTERVAL '{interval}'
                    GROUP BY c.country_code
                    ORDER BY count DESC
                    LIMIT 5
                """
                cursor.execute(query)
                rows = cursor.fetchall()
            except Exception:
                return []

            if not rows:
                return []

            return [
                {"rank": i + 1, "country": row[0], "count": row[1]}
                for i, row in enumerate(rows)
            ]

        # -------------------------------------------------------
        # Parse optional filters from event
        # -------------------------------------------------------
        filter_category = event.get("category") if event else None
        filter_country = event.get("country") if event else None
        sort_by = event.get("sort_by", "count") if event else "count"

        if 'start_date' in event:
            start_date = event['start_date']
            end_date = event['end_date']
            group_by = event['group_by']
            custom = get_request_volume_trend((start_date, end_date), group_by)
            print ("start date = ", start_date)
        
        else:
            custom = []
            print ("here")

        response_body = {
            "request_volume_7_days": get_request_volume_trend("7 days", "day"),
            "request_volume_1_month": get_request_volume_trend("30 days", "day"),
            "request_volume_1_year": get_request_volume_trend("1 year", "month"),
            "request_volume_custom_range": custom,
            "top_countries 7 days": get_top_countries("7 days"),
            "top_countries 30 days": get_top_countries("30 days"),
            "top_countries 1 year": get_top_countries("1 year"),
            "requests_by_category_region 7 days": get_requests_by_category_region(
                filter_category, filter_country, sort_by, "7 days"),
            "requests_by_category_region 1 month": get_requests_by_category_region(
            filter_category, filter_country, sort_by, "30 days"),
            "requests_by_category_region 1 year": get_requests_by_category_region(
            filter_category, filter_country, sort_by, "1 year")
        }

        return {
            "statusCode": 200,
            #"headers": CORS_HEADERS,
            # "body": json.dumps(response_body, default=json_serializer),
            "body": response_body
        }

    except Exception as e:
        print(f"Application analytics failed: {str(e)}")
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "Failed to connect to database"}),
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    # Local testing — requires DB env vars to be set
    import pprint
    result = lambda_handler({}, None)
    print(f"Status: {result['statusCode']}")
    pprint.pprint(json.loads(result["body"]))
