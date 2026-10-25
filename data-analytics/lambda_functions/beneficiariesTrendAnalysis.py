import json
import psycopg2
import pandas as pd
from datetime import datetime
import io
import os
import boto3

def lambda_handler(event, context):
    conn_V = None
    conn_I = None
    cursor_V = None
    cursor_I = None

    try:
        try:
            VIRGINIA_DB_CONFIG = get_db_config("Virginia")
            IRELAND_DB_CONFIG = get_db_config("Ireland")

            # Connects to databases
            conn_V = psycopg2.connect(**VIRGINIA_DB_CONFIG)
            conn_I = psycopg2.connect(**IRELAND_DB_CONFIG)
            print("Successfully connected to the databases")
        except Exception as e:
            # Catches an error if connection fails
            print("Exception connecting to databases:", e)
            return {
                'statusCode': 500,
                'body': json.dumps({'error': f'Could not connect to databases: {str(e)}'})
            }

        conn_V.autocommit = False
        conn_I.autocommit = False
        cursor_V = conn_V.cursor()
        cursor_I = conn_I.cursor()

        VIRGINIA_REAL_TABLE_REQUEST = "virginia_dev_saayam_rdbms.request"
        VIRGINIA_REAL_TABLE_USERS = "virginia_dev_saayam_rdbms.users"
        VIRGINIA_REAL_TABLE_COUNTRY = "virginia_dev_saayam_rdbms.country"

        IRELAND_REAL_TABLE_REQUEST = "ireland_dev_saayam_rdbms.request"
        IRELAND_REAL_TABLE_USERS = "ireland_dev_saayam_rdbms.users"
        IRELAND_REAL_TABLE_COUNTRY = "ireland_dev_saayam_rdbms.country"

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
                dates = cursor.fetchall()
                beneficiary_date = [t[1] for t in dates if len(t) > 1]
                return beneficiary_date
            except Exception as e:
                print(f"Error in aggregate_beneficiaries: {e}")
                return []

        def get_beneficiaries_dic(interval, group_by="day"):
            if isinstance(interval, tuple) and (interval[0] is None or interval[1] is None):
                return []

            # Fetch data
            beneficiaries_dates_virginia = aggregate_beneficiaries(interval, VIRGINIA_REAL_TABLE_REQUEST, cursor_V)
            beneficiaries_dates_ireland = aggregate_beneficiaries(interval, IRELAND_REAL_TABLE_REQUEST, cursor_I)
            beneficiaries_dates = beneficiaries_dates_virginia + beneficiaries_dates_ireland

            # Add empty data handling
            if not beneficiaries_dates:
                return []

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
                df_grouped["Date"] = df_grouped["last_update_date"].apply(
                    lambda x: x.to_timestamp().isoformat()
                )
            else:
                raise ValueError("group_by must be either 'day' or 'month'")

            # Build list of dicts
            dic = df_grouped[["Date", "Count"]].to_dict("records")
            return dic

        def aggregate_beneficiaries_country(REAL_TABLE_REQUEST, REAL_TABLE_USERS, REAL_TABLE_COUNTRY, cursor):
            try:
                # Queries the database for beneficiaries and their country.
                query = f"""
                    SELECT DISTINCT req_user_id, c.country_name
                    FROM {REAL_TABLE_REQUEST}
                    INNER JOIN {REAL_TABLE_USERS} as u ON {REAL_TABLE_REQUEST}.req_user_id = u.user_id
                    INNER JOIN {REAL_TABLE_COUNTRY} as c ON u.country_id = c.country_id
                    """
                cursor.execute(query)
                rows = cursor.fetchall()
                if not rows:
                    return []
                return rows
            except Exception as e:
                print(f"Error in aggregate_beneficiaries_country: {e}")
                return []

        def get_beneficiaries_country_dic():
            rows_virginia = aggregate_beneficiaries_country(
                VIRGINIA_REAL_TABLE_REQUEST, VIRGINIA_REAL_TABLE_USERS, VIRGINIA_REAL_TABLE_COUNTRY, cursor_V
            )
            rows_ireland = aggregate_beneficiaries_country(
                IRELAND_REAL_TABLE_REQUEST, IRELAND_REAL_TABLE_USERS, IRELAND_REAL_TABLE_COUNTRY, cursor_I
            )
            rows = rows_virginia + rows_ireland

            # Add empty data handling
            if not rows:
                return []

            # Count how many beneficiaries per country
            df = pd.DataFrame(rows, columns=["user_id", "country"])
            df_grouped = df.groupby("country").size().reset_index(name="Count")

            # Return as list of dicts
            dic = df_grouped.to_dict("records")
            return dic

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
                dates = cursor.fetchall()
                request_date = [t[0] for t in dates if len(t) > 0]
                return request_date
            except Exception as e:
                print(f"Error in aggregate_help_requests: {e}")
                return []

        def get_help_requests_dic(interval, group_by="day"):
            if isinstance(interval, tuple) and (interval[0] is None or interval[1] is None):
                return []

            # Fetch data
            request_dates_virginia = aggregate_help_requests(interval, VIRGINIA_REAL_TABLE_REQUEST, cursor_V)
            request_dates_ireland = aggregate_help_requests(interval, IRELAND_REAL_TABLE_REQUEST, cursor_I)
            request_dates = request_dates_virginia + request_dates_ireland

            # Add empty data handling
            if not request_dates:
                return []

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
                df_grouped["Date"] = df_grouped["submission_date"].apply(
                    lambda x: x.to_timestamp().isoformat()
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
                rows = cursor.fetchall()
                if not rows:
                    return []
                return rows
            except Exception as e:
                print(f"Error in aggregate_help_requests_country: {e}")
                return []

        def get_help_requests_country_dic():
            rows_virginia = aggregate_help_requests_country(
                VIRGINIA_REAL_TABLE_REQUEST, VIRGINIA_REAL_TABLE_USERS, VIRGINIA_REAL_TABLE_COUNTRY, cursor_V
            )
            rows_ireland = aggregate_help_requests_country(
                IRELAND_REAL_TABLE_REQUEST, IRELAND_REAL_TABLE_USERS, IRELAND_REAL_TABLE_COUNTRY, cursor_I
            )
            rows = rows_virginia + rows_ireland

            # Add empty data handling
            if not rows:
                return []

            # Count how many beneficiaries per country
            df = pd.DataFrame(rows, columns=["country"])
            df_grouped = df.groupby("country").size().reset_index(name="Count")

            # Return as list of dicts
            dic = df_grouped.to_dict("records")
            return dic

        # Parse event body
        payload = event
        if isinstance(event, dict) and "body" in event:
            body = event["body"]
            if isinstance(body, str):
                try:
                    payload = json.loads(body)
                except Exception:
                    pass
            elif isinstance(body, dict):
                payload = body

        beneficiaries_start_date = payload.get('beneficiaries_start_date')
        beneficiaries_end_date = payload.get('beneficiaries_end_date')
        help_requests_start_date = payload.get('help_requests_start_date')
        help_requests_end_date = payload.get('help_requests_end_date')

        # Obtains the dictionaries for beneficiaries categorized by time and country.
        beneficiaries_days = get_beneficiaries_dic("7 days", "day")
        beneficiaries_month = get_beneficiaries_dic("1 month", "day")
        beneficiaries_year = get_beneficiaries_dic("1 year", "month")
        beneficiaries_custom = get_beneficiaries_dic((beneficiaries_start_date, beneficiaries_end_date), "day")
        beneficiaries_country = get_beneficiaries_country_dic()

        # Obtains the dictionaries for help requests categorized by time and country.
        help_requests_days = get_help_requests_dic("7 days", "day")
        help_requests_month = get_help_requests_dic("1 month", "day")
        help_requests_year = get_help_requests_dic("1 year", "month")
        help_requests_custom = get_help_requests_dic((help_requests_start_date, help_requests_end_date), "day")
        help_requests_country = get_help_requests_country_dic()

        response_body = {
            "7 days beneficiaries": beneficiaries_days,
            "1 month beneficiaries": beneficiaries_month,
            "1 year beneficiaries": beneficiaries_year,
            "Custom date range beneficiaries": beneficiaries_custom,
            "Country beneficiaries": beneficiaries_country,
            "7 days help requests": help_requests_days,
            "1 month help requests": help_requests_month,
            "1 year help requests": help_requests_year,
            "Custom date range help requests": help_requests_custom,
            "Country help requests": help_requests_country
        }

        # Returns a status code of 200 and a JSON body consisting of beneficiaries and requests by time and country.
        return {
            'statusCode': 200,
            'body': response_body
        }

    finally:
        if cursor_V:
            cursor_V.close()
        if cursor_I:
            cursor_I.close()
        if conn_V:
            conn_V.close()
            print("Virginia database connection successfully closed")
        if conn_I:
            conn_I.close()
            print("Ireland database connection successfully closed")

# Configuration
def get_db_config(db):
    ssm = boto3.client('ssm', region_name='us-east-1')
    
    if db == "Virginia":
        response = ssm.get_parameter(Name = '/dev/saayam/db/Virginia/Analytics/user', WithDecryption = True)
    elif db == "Ireland":
        response = ssm.get_parameter(Name = '/dev/saayam/db/Ireland/Analytics/user', WithDecryption = True)
    else:
        raise ValueError('Database is neither Virginia nor Ireland')

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
    import unittest.mock as mock
    
    # Define Mock SSM client
    class MockSSM:
        def get_parameter(self, Name, WithDecryption=True):
            return {
                'Parameter': {
                    'Value': "dbname\nhost 'mock_host';\nuser 'mock_user';\npassword 'mock_password';\ndatabase name 'mock_dbname';\nport 5432;\n"
                }
            }

    # Define Mock Cursor
    class MockCursor:
        def execute(self, query, params=None):
            pass
        def fetchall(self):
            # Return empty tables to verify empty data handling & no crash
            return []
        def close(self):
            print("Mock cursor closed successfully")

    # Define Mock Connection
    class MockConnection:
        def __init__(self):
            self.autocommit = False
        def cursor(self):
            return MockCursor()
        def close(self):
            print("Mock connection closed successfully")

    # Patch boto3 and psycopg2
    mock_ssm = MockSSM()
    
    with mock.patch('boto3.client', return_value=mock_ssm), \
         mock.patch('psycopg2.connect', return_value=MockConnection()):
        
        event = {
            "body": """{ \"beneficiaries_start_date\": \"2026-04-03\", \"beneficiaries_end_date\": \"2026-04-16\",
            \"help_requests_start_date\": \"2026-03-03\", \"help_requests_end_date\": \"2026-05-13\" }
            """
        }
        print("Running lambda_handler locally with mocked DB...")
        result = lambda_handler(event, "")
        print("Result:", json.dumps(result, indent=2))
