import json
import os
import boto3 
import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"


SLA = {
    "target_days": 10,
    "target_hours": 240,
    "warning_days": 8.33,
    "warning_hours": 200
}


def get_default_response():
    return {
        "7D":  {"request_status_distribution": [], "total_requests": 0, "average_resolution_time_by_category": []},
        "30D": {"request_status_distribution": [], "total_requests": 0, "average_resolution_time_by_category": []},
        "1Y":  {"request_status_distribution": [], "total_requests": 0, "average_resolution_time_by_category": []},
        "All": {"request_status_distribution": [], "total_requests": 0, "average_resolution_time_by_category": []},
        "Custom": {"request_status_distribution": [], "total_requests": 0, "average_resolution_time_by_category": []},
        "Snapshot":{"request_status_distribution": [], "total_requests": 0, "average_resolution_time_by_category": []},
        "sla": SLA
    }


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": body
    }


def get_db_connection():
    ssm = boto3.client("ssm", region_name="us-east-1")

    response = ssm.get_parameter(
        Name="/dev/saayam/db/Virginia/Analytics/user",
        WithDecryption=True
    )

    creds = json.loads(response["Parameter"]["Value"])
    db_name = creds["DATABASE NAME"]
    return psycopg2.connect(
        host=creds["HOST"],
        database=db_name,
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )
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
    elif time_range == 'Custom':
        period = "day"
        date_string = "YYYY-MM-DD"
    elif time_range == "All":
        return "month", "YYYY-MM"
    elif time_range == 'Snapshot':
        return None,None
    else:
        raise ValueError("Invalid time range. Must be one of: '7D', '30D', '1Y', or 'Custom'.")

    return period, date_string

def build_date_filter(time_range, start_date=None, end_date=None):
    sql_date_condition = ""
    sql_params = ()

    if time_range == "Custom" and start_date and end_date:
        sql_date_condition = "r.submission_date BETWEEN %s AND %s"
        sql_params = (start_date, end_date)
    elif time_range == "7D":
        sql_date_condition = "r.submission_date >= CURRENT_DATE - INTERVAL '7 days'"
    elif time_range == "30D":
        sql_date_condition = "r.submission_date >= CURRENT_DATE - INTERVAL '30 days'"
    elif time_range == "1Y":
        sql_date_condition = "r.submission_date >= CURRENT_DATE - INTERVAL '1 year'"
    elif time_range == "All":
        sql_date_condition = "r.submission_date >= CURRENT_DATE - INTERVAL '2 years'"

    return sql_date_condition, sql_params

def fetch_request_status_distribution(cursor, time_range="All", start_date=None, end_date=None):
    period, date_string = get_grouping(time_range)
    date_filter, params = build_date_filter(time_range, start_date, end_date)
    date_filter_clause = f"WHERE {date_filter}" if date_filter else ""

    if period : 
        query = f"""
            SELECT TO_CHAR(DATE_TRUNC('{period}', r.submission_date), '{date_string}') AS period,
                rs.req_status AS status,
                COUNT(r.req_id) AS count
            FROM {SCHEMA_NAME}.request r
            JOIN {SCHEMA_NAME}.request_status rs
                ON r.req_status_id = rs.req_status_id
            {date_filter_clause}
            GROUP BY 1,2
            order by 1, 2;
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            {
                "period":row["period"],
                "status": row["status"],
                "count": int(row["count"])
            }
            for row in rows
        ]
    else : 
        query = f"""
            SELECT
                rs.req_status AS status,
                COUNT(r.req_id) AS count
            FROM {SCHEMA_NAME}.request r
            JOIN {SCHEMA_NAME}.request_status rs
                ON r.req_status_id = rs.req_status_id
            {date_filter_clause}
            GROUP BY rs.req_status
            ORDER BY rs.req_status;
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [
            { "status": row["status"], "count": int(row["count"])}
            for row in rows
        ]


def fetch_total_requests(cursor, time_range="All", start_date=None, end_date=None):
    period, date_string = get_grouping(time_range)
    date_filter, params = build_date_filter(time_range, start_date, end_date)
    date_filter_clause = f"WHERE {date_filter}" if date_filter else ""

    if period:
        query = f"""
            SELECT TO_CHAR(DATE_TRUNC('{period}', r.submission_date), '{date_string}') AS period,
                COUNT(r.req_id) AS total_requests
            FROM {SCHEMA_NAME}.request r
            {date_filter_clause}
            GROUP BY 1
            ORDER BY 1 

    """

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            {"period": row["period"], "total_requests": int(row["total_requests"])}
            for row in rows
        ]    
    else : 
        query = f"""
            SELECT COUNT(r.req_id) AS total_requests
            FROM {SCHEMA_NAME}.request r
            {date_filter_clause};
        """
        cursor.execute(query, params)
        row = cursor.fetchone()
        return int(row["total_requests"]) if row and row["total_requests"] is not None else 0


def fetch_average_resolution_time_by_category(cursor, time_range="All", start_date=None, end_date=None):
    period, date_string = get_grouping(time_range)
    date_filter, params = build_date_filter(time_range, start_date, end_date)
    date_filter_clause = f"AND {date_filter}" if date_filter else ""

    if period: 
        query = f"""
            SELECT TO_CHAR(DATE_TRUNC('{period}', r.submission_date), '{date_string}') AS period,
                hc.cat_name AS category,
                ROUND(
                    AVG(
                        EXTRACT(EPOCH FROM (r.serviced_date - r.submission_date)) / 3600
                    )::numeric,
                    2
                ) AS avg_hours
            FROM {SCHEMA_NAME}.request r
            JOIN {SCHEMA_NAME}.help_categories hc
                ON r.req_cat_id = hc.cat_id
            JOIN {SCHEMA_NAME}.request_status rs
                ON r.req_status_id = rs.req_status_id
            WHERE r.submission_date IS NOT NULL
            AND r.serviced_date IS NOT NULL
            AND r.serviced_date >= r.submission_date
            AND UPPER(rs.req_status) IN ('COMPLETED', 'RESOLVED')
            {date_filter_clause}
            GROUP BY hc.cat_name, TO_CHAR(DATE_TRUNC('{period}', r.submission_date), '{date_string}')
            ORDER BY avg_hours DESC;
        """

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            {
                "period": row["period"],
                "category": row["category"],
                "avg_hours": float(row["avg_hours"]) if row["avg_hours"] is not None else 0
            }
            for row in rows
        ]
    else :
        query = f"""
            SELECT
                hc.cat_name AS category,
                ROUND(
                    AVG(
                        EXTRACT(EPOCH FROM (r.serviced_date - r.submission_date)) / 3600
                    )::numeric,
                    2
                ) AS avg_hours
            FROM {SCHEMA_NAME}.request r
            JOIN {SCHEMA_NAME}.help_categories hc
                ON r.req_cat_id = hc.cat_id
            JOIN {SCHEMA_NAME}.request_status rs
                ON r.req_status_id = rs.req_status_id
            WHERE r.submission_date IS NOT NULL
              AND r.serviced_date IS NOT NULL
              AND r.serviced_date >= r.submission_date
              AND UPPER(rs.req_status) IN ('COMPLETED', 'RESOLVED')
              {date_filter_clause}
            GROUP BY hc.cat_name
            ORDER BY avg_hours DESC;
        """
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [
            {"category": row["category"], "avg_hours": float(row["avg_hours"]) if row["avg_hours"] is not None else 0}
            for row in rows
        ]

def lambda_handler(event, context):
    conn = None
    cursor = None

    time_range = event.get("time_range", None)

    # --- Custom date range: separate API call ---
    if time_range == "Custom":
        start_date = event.get("start_date", None)
        end_date = event.get("end_date", None)
        response_body = {
            "request_status_distribution": [],
            "total_requests": 0,
            "average_resolution_time_by_category": [],
            "sla": SLA
        }

        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            try:
                response_body["request_status_distribution"] = fetch_request_status_distribution(cursor, "Custom", start_date, end_date)
            except Exception as e:
                print(f"Custom status distribution failed: {e}")

            try:
                response_body["total_requests"] = fetch_total_requests(cursor, "Custom", start_date, end_date)
            except Exception as e:
                print(f"Custom total requests failed: {e}")

            try:
                response_body["average_resolution_time_by_category"] = fetch_average_resolution_time_by_category(cursor, "Custom", start_date, end_date)
            except Exception as e:
                print(f"Custom avg resolution failed: {e}")

            return build_response(200, response_body)

        except Exception as e:
            print(f"DB connection failed: {e}")
            return build_response(500, response_body)

        finally:
            if cursor: cursor.close()
            if conn: conn.close()

    # --- Consolidated call: {} returns 7D, 30D, 1Y, All together ---
    response_body = get_default_response()

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        for range_key in ["7D", "30D", "1Y", "All","Snapshot"]:
            try:
                response_body[range_key]["request_status_distribution"] = fetch_request_status_distribution(cursor, range_key)
            except Exception as e:
                print(f"{range_key} status distribution failed: {e}")

            try:
                response_body[range_key]["total_requests"] = fetch_total_requests(cursor, range_key)
            except Exception as e:
                print(f"{range_key} total requests failed: {e}")

            try:
                response_body[range_key]["average_resolution_time_by_category"] = fetch_average_resolution_time_by_category(cursor, range_key)
            except Exception as e:
                print(f"{range_key} avg resolution failed: {e}")

        return build_response(200, response_body)

    except Exception as e:
        print(f"DB connection failed: {e}")
        return build_response(500, response_body)

    finally:
        if cursor: cursor.close()
        if conn: conn.close()


if __name__ == "__main__":
    result_consolidated = lambda_handler({}, None)
    print(json.dumps(result_consolidated, indent=2))