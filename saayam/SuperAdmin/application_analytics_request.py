import json
import psycopg2
import pandas as pd
import boto3

def get_db_config(db):
    ssm = boto3.client('ssm', region_name='us-east-1')

    if db == "Virginia":
        response = ssm.get_parameter(
            Name='/dev/saayam/db/Virginia/Analytics/user',
            WithDecryption=True
        )
    else:
        return None

    config = response['Parameter']['Value']
    config_list = [line.strip() for line in config.splitlines()]

    host     = config_list[1].split()[1][1:-2]
    port     = int(config_list[5].split()[1][:-1])
    dbname   = config_list[4].split()[2][1:-2]
    user     = config_list[2].split()[1][1:-2]
    password = config_list[3].split()[1][1:-2]

    return {
        "host":     host,
        "port":     port,
        "dbname":   dbname,
        "user":     user,
        "password": password
    }


def lambda_handler(event, context):
    VIRGINIA_DB_CONFIG = get_db_config("Virginia")

    try:
        conn_V = psycopg2.connect(**VIRGINIA_DB_CONFIG)
        print("Successfully connected to the Virginia database")
    except Exception as e:
        print("Exception", e)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Could not connect to Virginia database'})
        }

    conn_V.autocommit = False
    cursor_V = conn_V.cursor()

    try:

        VIRGINIA_REAL_TABLE_REQUEST    = "virginia_dev_saayam_rdbms.request"
        VIRGINIA_REAL_TABLE_USERS      = "virginia_dev_saayam_rdbms.users"
        VIRGINIA_REAL_TABLE_COUNTRY    = "virginia_dev_saayam_rdbms.country"
        VIRGINIA_REAL_TABLE_CATEGORIES = "virginia_dev_saayam_rdbms.help_categories"

        def get_request_volume_dic(interval, group_by="day"):
            try:
                trunc_unit = "month" if group_by == "month" else "day"
                query = f"""
                    SELECT DATE_TRUNC(%s, submission_date) AS date,
                        COUNT(*) AS count
                    FROM {VIRGINIA_REAL_TABLE_REQUEST}
                    WHERE submission_date > CURRENT_TIMESTAMP - INTERVAL %s
                    AND submission_date IS NOT NULL
                    GROUP BY DATE_TRUNC(%s, submission_date)
                    ORDER BY date
                """
                cursor_V.execute(query, (trunc_unit, interval, trunc_unit))
                rows = cursor_V.fetchall()
            except Exception as e:
                print(f"[WARN] get_request_volume_dic failed: {e}")
                return []

            if not rows:
                return []

            return [
                {"date": row[0].isoformat(), "count": row[1]}
                for row in rows
            ]


        def aggregate_requests_by_category_region(category_filter, country_filter, sort_by, cursor):
            try:
                params = []
                where_clauses = ["r.submission_date IS NOT NULL"]

                if category_filter and category_filter != "All":
                    where_clauses.append("hc.cat_name = %s")
                    params.append(category_filter)

                if country_filter and country_filter != "All":
                    where_clauses.append("c.country_name = %s")
                    params.append(country_filter)

                where_sql = "WHERE " + " AND ".join(where_clauses)

                query = f"""
                    SELECT  COALESCE(hc.cat_name, 'Unknown') AS category,
                            COALESCE(c.country_name, 'Unknown') AS country,
                            COUNT(*) AS count
                    FROM    {VIRGINIA_REAL_TABLE_REQUEST} r
                    LEFT JOIN {VIRGINIA_REAL_TABLE_CATEGORIES} hc
                        ON r.req_cat_id = hc.cat_id
                    LEFT JOIN {VIRGINIA_REAL_TABLE_USERS} u
                        ON r.req_user_id = u.user_id
                    LEFT JOIN {VIRGINIA_REAL_TABLE_COUNTRY} c
                        ON u.country_id = c.country_id
                    {where_sql}
                    GROUP BY hc.cat_name, c.country_name
                    ORDER BY count DESC
                """
                if sort_by == "category":
                    query = query.replace("ORDER BY count DESC", "ORDER BY hc.cat_name")
                elif sort_by == "country":
                    query = query.replace("ORDER BY count DESC", "ORDER BY c.country_name")

                cursor.execute(query, params)
            except Exception as e:
                print(f"[WARN] aggregate_requests_by_category_region failed: {e}")
                return []

            return cursor.fetchall()
        

        def get_requests_by_category_region_dic(category_filter="All", country_filter="All", sort_by="Total"):
            rows = aggregate_requests_by_category_region(category_filter, country_filter, sort_by, cursor_V)
            if not rows:
                return []

            return [{"category": r[0], "country": r[1], "count": r[2]} for r in rows]
        

        def aggregate_top_countries(cursor, limit=5):
            try:
                query = f"""
                    SELECT  COALESCE(c.country_name, 'Unknown') AS country,
                            COUNT(*) AS count
                    FROM    {VIRGINIA_REAL_TABLE_REQUEST} r
                    LEFT JOIN {VIRGINIA_REAL_TABLE_USERS} u
                        ON r.req_user_id = u.user_id
                    LEFT JOIN {VIRGINIA_REAL_TABLE_COUNTRY} c
                        ON u.country_id = c.country_id
                    WHERE   r.submission_date IS NOT NULL
                    GROUP BY c.country_name
                    ORDER BY count DESC
                    LIMIT {limit}
                """
                cursor.execute(query)
            except Exception as e:
                print(f"[WARN] aggregate_top_countries failed: {e}")
                return []

            return cursor.fetchall()
        

        def get_top_countries_dic():
            rows = aggregate_top_countries(cursor_V)
            if not rows:
                return []

            return [
                {"rank": idx + 1, "country": r[0], "count": r[1]}
                for idx, r in enumerate(rows)
            ]
        

        category_filter = event.get("category", "All") if event else "All"
        country_filter  = event.get("country",  "All") if event else "All"
        sort_by         = event.get("sort_by",  "Total") if event else "Total"


        response_body = {
            "request_volume_7_days":       [],
            "request_volume_1_month":      [],
            "request_volume_1_year":       [],
            "top_countries":               [],
            "requests_by_category_region": [],
        }

        try:
            response_body["request_volume_7_days"]  = get_request_volume_dic("7 days",  "day")
        except Exception as e:
            print(f"[WARN] request_volume_7_days failed: {e}")

        try:
            response_body["request_volume_1_month"] = get_request_volume_dic("30 days", "day")
        except Exception as e:
            print(f"[WARN] request_volume_1_month failed: {e}")

        try:
            response_body["request_volume_1_year"]  = get_request_volume_dic("1 year",  "month")
        except Exception as e:
            print(f"[WARN] request_volume_1_year failed: {e}")

        try:
            response_body["requests_by_category_region"] = get_requests_by_category_region_dic(
                category_filter, country_filter, sort_by
            )
        except Exception as e:
            print(f"[WARN] requests_by_category_region failed: {e}")

        try:
            response_body["top_countries"] = get_top_countries_dic()
        except Exception as e:
            print(f"[WARN] top_countries failed: {e}")

        return {
            'statusCode': 200,
            'body': response_body
    }


    finally:
        if cursor_V:
            cursor_V.close()
        if conn_V:
            conn_V.close()
            print("Virginia database connection successfully closed")



if __name__ == "__main__":
    print(lambda_handler({}, None))

