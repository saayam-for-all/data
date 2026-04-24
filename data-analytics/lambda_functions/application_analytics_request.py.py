import os
import json
import psycopg2
import pandas as pd
from datetime import date, datetime


def json_serializer(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return str(obj)


def lambda_handler(event, context):
    DB_CONFIG = {
        "host": os.environ["host"],
        "port": os.environ["port"],
        "dbname": os.environ["dbname"],
        "user": os.environ["user"],
        "password": os.environ["password"],
    }

    REAL_TABLE_REQUEST = "virginia_dev_saayam_rdbms.request"
    REAL_TABLE_USERS = "virginia_dev_saayam_rdbms.users"
    REAL_TABLE_COUNTRY = "virginia_dev_saayam_rdbms.country"

    conn = None

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        def get_request_trend(interval, group_by="day"):
            query = f"""
                SELECT submission_date
                FROM {REAL_TABLE_REQUEST}
                WHERE submission_date > CURRENT_TIMESTAMP - INTERVAL %s
                  AND submission_date IS NOT NULL
            """
            cursor.execute(query, (interval,))
            rows = cursor.fetchall()

            if not rows:
                return []

            dates = [row[0] for row in rows if row[0] is not None]
            df = pd.DataFrame(dates, columns=["submission_date"])

            if df.empty:
                return []

            df["submission_date"] = pd.to_datetime(df["submission_date"])

            if group_by == "day":
                df_grouped = (
                    df.groupby(df["submission_date"].dt.date)
                    .size()
                    .reset_index(name="Count")
                )
                df_grouped["Date"] = df_grouped["submission_date"].apply(
                    lambda x: pd.Timestamp(x).isoformat()
                )

            elif group_by == "month":
                df_grouped = (
                    df.groupby(df["submission_date"].dt.to_period("M"))
                    .size()
                    .reset_index(name="Count")
                )
                df_grouped["Date"] = df_grouped["submission_date"].apply(
                    lambda x: x.to_timestamp().isoformat()
                )

            return df_grouped[["Date", "Count"]].to_dict("records")

        def get_requests_by_country():
            query = f"""
                SELECT c.country_name
                FROM {REAL_TABLE_REQUEST} r
                INNER JOIN {REAL_TABLE_USERS} u
                    ON r.req_user_id = u.user_id
                INNER JOIN {REAL_TABLE_COUNTRY} c
                    ON u.country_id = c.country_id
                WHERE c.country_name IS NOT NULL
            """
            cursor.execute(query)
            rows = cursor.fetchall()

            if not rows:
                return []

            df = pd.DataFrame(rows, columns=["country"])
            df_grouped = df.groupby("country").size().reset_index(name="Count")

            return df_grouped.to_dict("records")

        response_body = {
            "7 days requests": get_request_trend("7 days", "day"),
            "1 month requests": get_request_trend("1 month", "day"),
            "1 year requests": get_request_trend("1 year", "month"),
            "Country requests": get_requests_by_country(),
        }

        return {
            "statusCode": 200,
            "body": json.dumps(response_body, default=json_serializer)
        }

    except Exception as e:
        print(f"Request analytics Lambda failed: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Could not process request analytics"})
        }

    finally:
        if conn:
            conn.close()
