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

    REAL_TABLE_VOLUNTEERS_ASSIGNED = "virginia_dev_saayam_rdbms.volunteers_assigned"
    REAL_TABLE_USERS = "virginia_dev_saayam_rdbms.users"
    REAL_TABLE_COUNTRY = "virginia_dev_saayam_rdbms.country"

    # Update this if schema uses assigned_date / last_update_date
    VOLUNTEER_ACTIVITY_DATE_COLUMN = "created_date"

    conn = None

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        def get_volunteer_trend(interval, group_by="day"):
            query = f"""
                SELECT DISTINCT volunteer_id, {VOLUNTEER_ACTIVITY_DATE_COLUMN}
                FROM {REAL_TABLE_VOLUNTEERS_ASSIGNED}
                WHERE {VOLUNTEER_ACTIVITY_DATE_COLUMN} > CURRENT_TIMESTAMP - INTERVAL %s
                  AND {VOLUNTEER_ACTIVITY_DATE_COLUMN} IS NOT NULL
            """
            cursor.execute(query, (interval,))
            rows = cursor.fetchall()

            if not rows:
                return []

            dates = [row[1] for row in rows if row[1] is not None]
            df = pd.DataFrame(dates, columns=["activity_date"])

            if df.empty:
                return []

            df["activity_date"] = pd.to_datetime(df["activity_date"])

            if group_by == "day":
                df_grouped = (
                    df.groupby(df["activity_date"].dt.date)
                    .size()
                    .reset_index(name="Count")
                )
                df_grouped["Date"] = df_grouped["activity_date"].apply(
                    lambda x: pd.Timestamp(x).isoformat()
                )

            elif group_by == "month":
                df_grouped = (
                    df.groupby(df["activity_date"].dt.to_period("M"))
                    .size()
                    .reset_index(name="Count")
                )
                df_grouped["Date"] = df_grouped["activity_date"].apply(
                    lambda x: x.to_timestamp().isoformat()
                )

            return df_grouped[["Date", "Count"]].to_dict("records")

        def get_volunteers_by_country():
            query = f"""
                SELECT DISTINCT va.volunteer_id, c.country_name
                FROM {REAL_TABLE_VOLUNTEERS_ASSIGNED} va
                INNER JOIN {REAL_TABLE_USERS} u
                    ON va.volunteer_id = u.user_id
                INNER JOIN {REAL_TABLE_COUNTRY} c
                    ON u.country_id = c.country_id
                WHERE c.country_name IS NOT NULL
            """
            cursor.execute(query)
            rows = cursor.fetchall()

            if not rows:
                return []

            df = pd.DataFrame(rows, columns=["volunteer_id", "country"])
            df_grouped = df.groupby("country").size().reset_index(name="Count")

            return df_grouped.to_dict("records")

        response_body = {
            "7 days volunteers": get_volunteer_trend("7 days", "day"),
            "1 month volunteers": get_volunteer_trend("1 month", "day"),
            "1 year volunteers": get_volunteer_trend("1 year", "month"),
            "Country volunteers": get_volunteers_by_country(),
        }

        return {
            "statusCode": 200,
            "body": json.dumps(response_body, default=json_serializer)
        }

    except Exception as e:
        print(f"Volunteer analytics Lambda failed: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Could not process volunteer analytics"})
        }

    finally:
        if conn:
            conn.close()
