import json
import psycopg2
import pandas as pd
from datetime import datetime
import io

def lambda_handler(event, context):
    # Configuration
    DB_CONFIG = {
        "host": os.environ['host'],
        "port": os.environ['port'],
        "dbname": os.environ['dbname'],
        "user": os.environ['user'],
        "password": os.environ['password']
    }
    try:
        # Connects to database
        conn = psycopg2.connect(**DB_CONFIG)
        print ("Successfully connected to the databases")

    except Exception as e:
        # Catches an error if connection fails
        return {
            'status_code': 500,
            'body': json.dumps({'error': 'Could not connect to database'})
        }
    conn.autocommit = False
    cursor = conn.cursor()

    REAL_TABLE_REQUEST = "virginia_dev_saayam_rdbms.request"
    REAL_TABLE_USERS = "virginia_dev_saayam_rdbms.users"
    REAL_TABLE_COUNTRY = "virginia_dev_saayam_rdbms.country"


    ###############################################################################################
    ###############################################################################################
    ###############################################################################################


    def aggregate_beneficiaries(interval):
        try:
            # Queries the request table for dates within an interval length of time before the present.
            query = f"""
                SELECT DISTINCT req_user_id, last_update_date
                FROM {REAL_TABLE_REQUEST}
                WHERE last_update_date > CURRENT_TIMESTAMP - INTERVAL '{interval}'
                """
            cursor.execute(query)

        except Exception as e:
            # Returns an empty list if query fails.
            return []
        dates = cursor.fetchall()
        beneficiary_date = [t[1] for t in dates if len(t) > 1]

        return beneficiary_date

    def get_beneficiaries_dic(interval, group_by="day"):
        # Fetch data
        beneficiaries_dates = aggregate_beneficiaries(interval)

        # Convert to DataFrame
        df = pd.DataFrame(beneficiaries_dates, columns=["last_update_date"])
        df["last_update_date"] = pd.to_datetime(df["last_update_date"])

        # Group by day or month
        if group_by == "day":
            df_grouped = (
                df.groupby(df["last_update_date"].dt.date)  # group by date
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
            df_grouped["Date"] = df_grouped["last_update_date"].apply(lambda x: x.to_timestamp().isoformat()
            )
        else:
            raise ValueError("group_by must be either 'day' or 'month'")

        # Build list of dicts
        dic = df_grouped[["Date", "Count"]].to_dict("records")

        return dic

    def aggregate_beneficiaries_country():
        try:
            # Queries the database for beneficaries and their country.
            query = f"""
                SELECT DISTINCT req_user_id, c.country_name
                FROM {REAL_TABLE_REQUEST}
                INNER JOIN {REAL_TABLE_USERS} as u ON {REAL_TABLE_REQUEST}.req_user_id = u.user_id
                INNER JOIN {REAL_TABLE_COUNTRY} as c ON u.country_id = c.country_id
                """
            cursor.execute(query)

        except Exception as e:
            # Returns a dictionary with a status code of 500 if query fails.
            return {
                'status_code': 500,
                'error': 'Could not query the database.',
                'beneficiaries by country': []
            }
        rows = cursor.fetchall()

        # Count how many beneficiaries per country
        df = pd.DataFrame(rows, columns=["user_id", "country"])
        df_grouped = df.groupby("country").size().reset_index(name="Count")

        # Return as list of dicts
        dic = df_grouped.to_dict("records")

        return dic

    ###############################################################################################
    ###############################################################################################
    ###############################################################################################

    def aggregate_help_requests(interval):
        try:
            # Queries the database for help requests within an interval length of time before the present.
            query = f"""
            SELECT submission_date
            FROM {REAL_TABLE_REQUEST}
            WHERE submission_date > CURRENT_TIMESTAMP - INTERVAL '{interval}'
            """
            cursor.execute(query)

        except Exception as e:
            # Returns an empty list if query fails.
            return []
        dates = cursor.fetchall()
        request_date = [t[0] for t in dates if len(t) > 0]

        return request_date

    def get_help_requests_dic(interval, group_by="day"):
        # Fetch data
        request_dates = aggregate_help_requests(interval)

        # Convert to DataFrame
        df = pd.DataFrame(request_dates, columns=["submission_date"])
        df["submission_date"] = pd.to_datetime(df["submission_date"])

        # Group by day or month
        if group_by == "day":
            df_grouped = (
                df.groupby(df["submission_date"].dt.date)  # group by date
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
            df_grouped["Date"] = df_grouped["submission_date"].apply(lambda x: x.to_timestamp().isoformat()
            )
        else:
            raise ValueError("group_by must be either 'day' or 'month'")

        # Build list of dicts
        dic = df_grouped[["Date", "Count"]].to_dict("records")

        return dic

    def aggregate_help_requests_country():
        # Queries for help requests and their country.
        try:
            query = f"""
                    SELECT c.country_name
                    FROM {REAL_TABLE_REQUEST}
                        INNER JOIN {REAL_TABLE_USERS} as u on {REAL_TABLE_REQUEST}.req_user_id = u.user_id
                        INNER JOIN {REAL_TABLE_COUNTRY} as c on u.country_id = c.country_id
                    """
            cursor.execute(query)

        except Exception as e:
            # Returns a dictionary with status code 500 if query fails.
            return {
                'status_code': 500,
                'error': 'Could not query the database.',
                'requests by country': []
            }
        rows = cursor.fetchall()

        # Count how many beneficiaries per country
        df = pd.DataFrame(rows, columns=["country"])
        df_grouped = df.groupby("country").size().reset_index(name="Count")

        # Return as list of dicts
        dic = df_grouped.to_dict("records")

        return dic


    # Obtains the dictionaries for beneficiaries categorized by time and country.
    beneficiaries_days = get_beneficiaries_dic("7 days", "day")
    beneficiaries_month = get_beneficiaries_dic("1 month", "day")
    beneficiaries_year = get_beneficiaries_dic("1 year", "month")
    beneficiaries_country = aggregate_beneficiaries_country()

    # Obtains the dictionaries for help requests categorized by time and country.
    help_requests_days = get_help_requests_dic("7 days", "day")
    help_requests_month = get_help_requests_dic("1 month", "day")
    help_requests_year = get_help_requests_dic("1 year", "month")
    help_requests_country = aggregate_help_requests_country()

    response_body = {"7 days beneficiaries": beneficiaries_days,
    "1 month beneficiaries": beneficiaries_month,
    "1 year beneficiaries": beneficiaries_year,
    "Country beneficiaries": beneficiaries_country,
    "7 days help requests": help_requests_days,
    "1 month help requests": help_requests_month,
    "1 year help requests": help_requests_year,
    "Country help requests": help_requests_country}

    if conn:
        # Closes the connection
        conn.close()
        print("Database connection successfully closed")

    # Returns a status code of 200 and a JSON body consisting of beneficaries and requests by time and country.
    http_res = {
        'statusCode': 200,
        'body': json.dumps(response_body)
    }
    return http_res

if name == "main":
    print(lambda_handler("". ""))
