import json
import psycopg2
import pandas as pd
from datetime import datetime
import io
import os
import boto3

def lambda_handler(event, context):
    VIRGINIA_DB_CONFIG = get_db_config("Virginia")
    IRELAND_DB_CONFIG = get_db_config("Ireland")

    try:
        # Connects to database
        # conn = psycopg2.connect(**IRELAND_DB_CONFIG)
        conn_V = psycopg2.connect(**VIRGINIA_DB_CONFIG)
        conn_I = psycopg2.connect(**IRELAND_DB_CONFIG)
        print ("Successfully connected to the databases")

    except Exception as e:
        # Catches an error if connection fails
        print ("Exception", e)
        return {
            'status_code': 500,
            'body': json.dumps({'error': 'Could not connect to databases'})
        }
    conn_V.autocommit = False
    conn_I.autocommit = False
    cursor_V = conn_V.cursor()
    cursor_I = conn_I.cursor()

    VIRGINIA_REAL_TABLE_REQUEST = "virginia_dev_saayam_rdbms.request"
    VIRGINIA_REAL_TABLE_USERS = "virginia_dev_saayam_rdbms.users"
    VIRGINIA_REAL_TABLE_COUNTRY = "virginia_dev_saayam_rdbms.country"

    IRELAND_REAL_TABLE_REQUEST = "virginia_dev_saayam_rdbms.request"
    IRELAND_REAL_TABLE_USERS = "ireland_dev_saayam_rdbms.users"
    IRELAND_REAL_TABLE_COUNTRY = "virginia_dev_saayam_rdbms.country"


    ###############################################################################################
    ###############################################################################################
    ###############################################################################################


    def aggregate_beneficiaries(interval, REAL_TABLE_REQUEST, cursor):
        try:
            # Queries the request table for dates within an interval length of time before the present.
            if type(interval) == str:
                query = f"""
                    SELECT DISTINCT req_user_id, last_update_date
                    FROM {REAL_TABLE_REQUEST}
                    WHERE last_update_date > CURRENT_TIMESTAMP - INTERVAL '{interval}'
                    """

            else:
                start_date, end_date = interval
                query = f"""
                    SELECT DISTINCT req_user_id, last_update_date
                    FROM {REAL_TABLE_REQUEST}
                    WHERE last_update_date BETWEEN '{start_date}' AND '{end_date}'
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
        beneficiaries_dates_virginia = aggregate_beneficiaries(interval, VIRGINIA_REAL_TABLE_REQUEST, cursor_V)
        # beneficiaries_dates_ireland = aggregate_beneficiaries(interval, IRELAND_REAL_TABLE_REQUEST, cursor_I)
        beneficiaries_dates = beneficiaries_dates_virginia

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

    def aggregate_beneficiaries_country(REAL_TABLE_REQUEST, REAL_TABLE_USERS, REAL_TABLE_COUNTRY, cursor):
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

        return rows

    def get_beneficiaries_country_dic():
        rows_virginia = aggregate_beneficiaries_country(VIRGINIA_REAL_TABLE_REQUEST, VIRGINIA_REAL_TABLE_USERS, VIRGINIA_REAL_TABLE_COUNTRY,
        cursor_V)
        rows_ireland = aggregate_beneficiaries_country(IRELAND_REAL_TABLE_REQUEST, IRELAND_REAL_TABLE_USERS, IRELAND_REAL_TABLE_COUNTRY,
        cursor_I)
        rows = rows_virginia

        # Count how many beneficiaries per country
        df = pd.DataFrame(rows, columns=["user_id", "country"])
        df_grouped = df.groupby("country").size().reset_index(name="Count")

        # Return as list of dicts
        dic = df_grouped.to_dict("records")

        return dic

    ###############################################################################################
    ###############################################################################################
    ###############################################################################################

    def aggregate_help_requests(interval, REAL_TABLE_REQUEST, cursor):
        try:
            # Queries the database for help requests within an interval length of time before the present.
            if type(interval) == str:
                query = f"""
                    SELECT submission_date
                    FROM {REAL_TABLE_REQUEST}
                    WHERE submission_date > CURRENT_TIMESTAMP - INTERVAL '{interval}'
                    """

            else:
                start_date, end_date = interval
                query = f"""
                    SELECT submission_date
                    FROM {REAL_TABLE_REQUEST}
                    WHERE submission_date BETWEEN '{start_date}' AND '{end_date}'
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
        request_dates_virginia = aggregate_help_requests(interval, VIRGINIA_REAL_TABLE_REQUEST, cursor_V)
        # request_dates_ireland = aggregate_help_requests(interval, IRELAND_REAL_TABLE_REQUEST, cursor_I)
        request_dates = request_dates_virginia

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

    def aggregate_help_requests_country(REAL_TABLE_REQUEST, REAL_TABLE_USERS, REAL_TABLE_COUNTRY, cursor):
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

        return rows

    def get_help_requests_country_dic():
        rows_virginia = aggregate_help_requests_country(VIRGINIA_REAL_TABLE_REQUEST, VIRGINIA_REAL_TABLE_USERS, VIRGINIA_REAL_TABLE_COUNTRY,
        cursor_V)
        rows_ireland = aggregate_help_requests_country(IRELAND_REAL_TABLE_REQUEST, IRELAND_REAL_TABLE_USERS, IRELAND_REAL_TABLE_COUNTRY,
        cursor_I)
        rows = rows_virginia

        # Count how many beneficiaries per country
        df = pd.DataFrame(rows, columns=["country"])
        df_grouped = df.groupby("country").size().reset_index(name="Count")

        # Return as list of dicts
        dic = df_grouped.to_dict("records")

        return dic



    # body = event['body']
    beneficiaries_start_date = event['beneficiaries_start_date']
    beneficiaries_end_date = event['beneficiaries_end_date']

    # Obtains the dictionaries for beneficiaries in the Virginia database categorized by time and country.
    beneficiaries_days = get_beneficiaries_dic("7 days", "day")
    beneficiaries_month = get_beneficiaries_dic("1 month", "day")
    beneficiaries_year = get_beneficiaries_dic("1 year", "month")
    beneficiaries_custom = get_beneficiaries_dic((beneficiaries_start_date, beneficiaries_end_date), "day")
    beneficiaries_country = get_beneficiaries_country_dic()

    help_requests_start_date = event['help_requests_start_date']
    help_requests_end_date = event['help_requests_end_date']

    # Obtains the dictionaries for help requests in the Virginia database categorized by time and country.
    help_requests_days = get_help_requests_dic("7 days", "day")
    help_requests_month = get_help_requests_dic("1 month", "day")
    help_requests_year = get_help_requests_dic("1 year", "month")
    help_requests_custom = get_help_requests_dic((help_requests_start_date, help_requests_end_date), "day")
    help_requests_country = get_help_requests_country_dic()




    response_body = {"7 days beneficiaries": beneficiaries_days,
    "1 month beneficiaries": beneficiaries_month,
    "1 year beneficiaries": beneficiaries_year,
    "Custom date range beneficiaries": beneficiaries_custom,
    "Country beneficiaries": beneficiaries_country,
    "7 days help requests": help_requests_days,
    "1 month help requests": help_requests_month,
    "1 year help requests": help_requests_year,
    "Custom date range help requests": help_requests_custom,
    "Country help requests": help_requests_country}

    if conn_V:
        # Closes the connection
        conn_V.close()
        print("Virginia database connection successfully closed")

    if conn_I:
        conn_I.close()
        print("Ireland database connection successfully closed")
    # Returns a status code of 200 and a JSON body consisting of beneficaries and requests by time and country.
    http_res = {
        'statusCode': 200,
        'body': response_body
    }
    return http_res


# Configuration
def get_db_config(db):
    ssm = boto3.client('ssm', region_name='us-east-1')
    Names = ["host", "port", "dbname", "user", "password"]

    if db == "Virginia":
        response = ssm.get_parameter(Name = '/dev/saayam/db/Virginia/Analytics/user', WithDecryption = True)

    elif db == "Ireland":
        response = ssm.get_parameter(Name = '/dev/saayam/db/Ireland/Analytics/user', WithDecryption = True)

    else:
        return {
            'status_code': 500,
            'body': json.dumps({'error': 'Database is neither Virginia nor Ireland'})
        }

    config = response['Parameter']['Value']
    config_list = [line.strip() for line in config.splitlines()]

    host = config_list[1].split()[1][1:-2]
    port = int(config_list[5].split()[1][:-1])
    dbname = config_list[4].split()[2][1:-2]
    user = config_list[2].split()[1][1:-2]
    password = config_list[3].split()[1][1:-2]

    DB_CONFIG = {
        "host": host,
        "port": port,
        "dbname": dbname,
        "user": user,
        "password": password
    }

    return DB_CONFIG

if __name__ == "__main__":
    event = {
        "body": """{ \"beneficiaries_start_date\": \"2026-04-03\", \"beneficiaries_end_date\": \"2026-04-16\",
        \"help_requests_start_date\": \"2026-03-03\", \"help_requests_end_date\": \"2026-05-13\" }
        """
    }
    print(lambda_handler(event, ""))
