import os
import json
import psycopg2
import pandas as pd


def lambda_handler(event, context):
    # Configuration
    DB_CONFIG = {
        "host": os.environ['host'],
        "port": os.environ['port'],
        "dbname": os.environ['dbname'],
        "user": os.environ['user'],
        "password": os.environ['password']
    }

    conn = None
    cursor = None

    try:
        # Connect to database
        conn = psycopg2.connect(**DB_CONFIG)
        print("Successfully connected to the databases")

        conn.autocommit = False
        cursor = conn.cursor()

        REAL_TABLE_REQUEST = "virginia_dev_saayam_rdbms.request"
        REAL_TABLE_USERS = "virginia_dev_saayam_rdbms.users"
        REAL_TABLE_COUNTRY = "virginia_dev_saayam_rdbms.country"

        IRELAND_TABLE_REQUEST = "ireland_dev_saayam_rdbms.request"
        IRELAND_TABLE_USERS = "ireland_dev_saayam_rdbms.users"
        IRELAND_TABLE_COUNTRY = "ireland_dev_saayam_rdbms.country"

        def aggregate_beneficiaries(interval):
            try:
                query = f"""
                    SELECT DISTINCT req_user_id, last_update_date
                    FROM {REAL_TABLE_REQUEST}
                    WHERE last_update_date > CURRENT_TIMESTAMP - INTERVAL '{interval}'

                    UNION ALL

                    SELECT DISTINCT req_user_id, last_update_date
                    FROM {IRELAND_TABLE_REQUEST}
                    WHERE last_update_date > CURRENT_TIMESTAMP - INTERVAL '{interval}'
                """
                cursor.execute(query)
                dates = cursor.fetchall()
                return [t[1] for t in dates if len(t) > 1]
            except Exception:
                return []

        def get_beneficiaries_dic(interval, group_by="day"):
            beneficiaries_dates = aggregate_beneficiaries(interval)
            if not beneficiaries_dates:
                return []

            df = pd.DataFrame(beneficiaries_dates, columns=["last_update_date"])
            df["last_update_date"] = pd.to_datetime(df["last_update_date"])

            if group_by == "day":
                df_grouped = (
                    df.groupby(df["last_update_date"].dt.date)
                    .size()
                    .reset_index(name="Count")
                )
                df_grouped["Date"] = df_grouped["last_update_date"].apply(
                    lambda x: pd.Timestamp(x).isoformat()
                )
            elif group_by == "month":
                df_grouped = (
                    df.groupby(df["last_update_date"].dt.to_period("M"))
                    .size()
                    .reset_index(name="Count")
                )
                df_grouped["Date"] = df_grouped["last_update_date"].apply(
                    lambda x: x.to_timestamp().isoformat()
                )
            else:
                return []

            return df_grouped[["Date", "Count"]].to_dict("records")

        def aggregate_beneficiaries_country():
            try:
                query = f"""
                    SELECT DISTINCT req_user_id, c.country_name
                    FROM {REAL_TABLE_REQUEST} r
                    INNER JOIN {REAL_TABLE_USERS} u ON r.req_user_id = u.user_id
                    INNER JOIN {REAL_TABLE_COUNTRY} c ON u.country_id = c.country_id

                    UNION ALL

                    SELECT DISTINCT req_user_id, c.country_name
                    FROM {IRELAND_TABLE_REQUEST} r
                    INNER JOIN {IRELAND_TABLE_USERS} u ON r.req_user_id = u.user_id
                    INNER JOIN {IRELAND_TABLE_COUNTRY} c ON u.country_id = c.country_id
                """
                cursor.execute(query)
                rows = cursor.fetchall()
                if not rows:
                    return []

                df = pd.DataFrame(rows, columns=["user_id", "country"])
                df_grouped = df.groupby("country").size().reset_index(name="Count")
                return df_grouped.to_dict("records")
            except Exception:
                return []

        def aggregate_help_requests(interval):
            try:
                query = f"""
                    SELECT submission_date
                    FROM {REAL_TABLE_REQUEST}
                    WHERE submission_date > CURRENT_TIMESTAMP - INTERVAL '{interval}'

                    UNION ALL

                    SELECT submission_date
                    FROM {IRELAND_TABLE_REQUEST}
                    WHERE submission_date > CURRENT_TIMESTAMP - INTERVAL '{interval}'
                """
                cursor.execute(query)
                dates = cursor.fetchall()
                return [t[0] for t in dates if len(t) > 0]
            except Exception:
                return []

        def get_help_requests_dic(interval, group_by="day"):
            request_dates = aggregate_help_requests(interval)
            if not request_dates:
                return []

            df = pd.DataFrame(request_dates, columns=["submission_date"])
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
            else:
                return []

            return df_grouped[["Date", "Count"]].to_dict("records")

        def aggregate_help_requests_country():
            try:
                query = f"""
                    SELECT c.country_name
                    FROM {REAL_TABLE_REQUEST} r
                    INNER JOIN {REAL_TABLE_USERS} u ON r.req_user_id = u.user_id
                    INNER JOIN {REAL_TABLE_COUNTRY} c ON u.country_id = c.country_id

                    UNION ALL

                    SELECT c.country_name
                    FROM {IRELAND_TABLE_REQUEST} r
                    INNER JOIN {IRELAND_TABLE_USERS} u ON r.req_user_id = u.user_id
                    INNER JOIN {IRELAND_TABLE_COUNTRY} c ON u.country_id = c.country_id
                """
                cursor.execute(query)
                rows = cursor.fetchall()
                if not rows:
                    return []

                df = pd.DataFrame(rows, columns=["country"])
                df_grouped = df.groupby("country").size().reset_index(name="Count")
                return df_grouped.to_dict("records")
            except Exception:
                return []

        beneficiaries_days = get_beneficiaries_dic("7 days", "day")
        beneficiaries_month = get_beneficiaries_dic("1 month", "day")
        beneficiaries_year = get_beneficiaries_dic("1 year", "month")
        beneficiaries_country = aggregate_beneficiaries_country()

        help_requests_days = get_help_requests_dic("7 days", "day")
        help_requests_month = get_help_requests_dic("1 month", "day")
        help_requests_year = get_help_requests_dic("1 year", "month")
        help_requests_country = aggregate_help_requests_country()

        response_body = {
            "7 days beneficiaries": beneficiaries_days,
            "1 month beneficiaries": beneficiaries_month,
            "1 year beneficiaries": beneficiaries_year,
            "Country beneficiaries": beneficiaries_country,
            "7 days help requests": help_requests_days,
            "1 month help requests": help_requests_month,
            "1 year help requests": help_requests_year,
            "Country help requests": help_requests_country
        }

        http_res = {
            'statusCode': 200,
            'body': json.dumps(response_body)
        }
        return http_res

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
            print("Database connection successfully closed")


if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(json.dumps(result, indent=2))
