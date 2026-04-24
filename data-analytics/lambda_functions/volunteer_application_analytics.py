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

    REAL_TABLE_VOLUNTEERS = "virginia_dev_saayam_rdbms.volunteers_assigned"
    REAL_TABLE_USERS = "virginia_dev_saayam_rdbms.users"
    REAL_TABLE_COUNTRY = "virginia_dev_saayam_rdbms.country"

    # UPDATE THIS IF NEEDED
    DATE_COLUMN = "created_date"   # or assigned_date

    conn = None

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # ---------------------------------------------------
        # 1. Volunteer Activity Trend
        # ---------------------------------------------------
        def get_volunteer_trend(interval, group_by="month"):
            query = f"""
                SELECT volunteer_id, {DATE_COLUMN}
                FROM {REAL_TABLE_VOLUNTEERS}
                WHERE {DATE_COLUMN} > CURRENT_TIMESTAMP - INTERVAL %s
                  AND {DATE_COLUMN} IS NOT NULL
            """
            cursor.execute(query, (interval,))
            rows = cursor.fetchall()

            if not rows:
                return []

            df = pd.DataFrame(rows, columns=["volunteer_id", "date"])
            df["date"] = pd.to_datetime(df["date"])

            if df.empty:
                return []

            # New volunteers per period
            if group_by == "month":
                df_grouped = (
                    df.groupby(df["date"].dt.to_period("M"))
                    .agg({"volunteer_id": "nunique"})
                    .reset_index()
                )
                df_grouped["Date"] = df_grouped["date"].apply(
                    lambda x: x.to_timestamp().isoformat()
                )

            else:
                df_grouped = (
                    df.groupby(df["date"].dt.date)
                    .agg({"volunteer_id": "nunique"})
                    .reset_index()
                )
                df_grouped["Date"] = df_grouped["date"].apply(
                    lambda x: pd.Timestamp(x).isoformat()
                )

            df_grouped.rename(columns={"volunteer_id": "New"}, inplace=True)

            # Total volunteers (cumulative)
            df_grouped["Total"] = df_grouped["New"].cumsum()

            # Active volunteers (approx: same as new here — can improve later)
            df_grouped["Active"] = df_grouped["New"]

            return df_grouped[["Date", "New", "Active", "Total"]].to_dict("records")

        # ---------------------------------------------------
        # 2. Volunteers by Location
        # ---------------------------------------------------
        def get_volunteers_by_country():
            query = f"""
                SELECT DISTINCT v.volunteer_id, c.country_name
                FROM {REAL_TABLE_VOLUNTEERS} v
                INNER JOIN {REAL_TABLE_USERS} u
                    ON v.volunteer_id = u.user_id
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

        # ---------------------------------------------------
        # Response
        # ---------------------------------------------------
        response_body = {
            "volunteer_activity_trend": get_volunteer_trend("1 year", "month"),
            "volunteers_by_location": get_volunteers_by_country(),

            # Optional KPIs (static for now — can improve later)
            "kpis": {
                "churn_rate": "~5-8%",
                "inactive_volunteers": 50,
                "retention_rate": "~90%"
            }
        }

        return {
            "statusCode": 200,
            "body": json.dumps(response_body, default=json_serializer)
        }

    except Exception as e:
        print(f"Volunteer analytics failed: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Volunteer analytics failed"})
        }

    finally:
        if conn:
            conn.close()
