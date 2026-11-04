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

                if interval == "all":
                    query = f"""
                    SELECT DISTINCT req_user_id, last_update_date
                    FROM {REAL_TABLE_REQUEST}
                    """
                
                else:
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

    def aggregate_beneficiaries_country(interval, REAL_TABLE_REQUEST, REAL_TABLE_USERS, REAL_TABLE_COUNTRY, cursor):
        try:
            # Queries the database for beneficaries and their country.

            if interval == "all":
                query = f"""
                SELECT DISTINCT req_user_id, c.country_code, {REAL_TABLE_REQUEST}.last_update_date
                FROM {REAL_TABLE_REQUEST}
                INNER JOIN {REAL_TABLE_USERS} as u ON {REAL_TABLE_REQUEST}.req_user_id = u.user_id
                INNER JOIN {REAL_TABLE_COUNTRY} as c ON u.country_id = c.country_id
                """
            
            else:
                query = f"""
                SELECT DISTINCT req_user_id, c.country_code, {REAL_TABLE_REQUEST}.last_update_date
                FROM {REAL_TABLE_REQUEST}
                INNER JOIN {REAL_TABLE_USERS} as u ON {REAL_TABLE_REQUEST}.req_user_id = u.user_id
                INNER JOIN {REAL_TABLE_COUNTRY} as c ON u.country_id = c.country_id
                WHERE {REAL_TABLE_REQUEST}.last_update_date > CURRENT_TIMESTAMP - INTERVAL '{interval}'
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

    def get_beneficiaries_country_dic(interval, group_by = "day"):
        rows_virginia = aggregate_beneficiaries_country(interval, VIRGINIA_REAL_TABLE_REQUEST, VIRGINIA_REAL_TABLE_USERS, VIRGINIA_REAL_TABLE_COUNTRY,
        cursor_V)
        rows_ireland = aggregate_beneficiaries_country(interval, IRELAND_REAL_TABLE_REQUEST, IRELAND_REAL_TABLE_USERS, IRELAND_REAL_TABLE_COUNTRY,
        cursor_I)
        rows = rows_virginia

        # Count how many beneficiaries per country
        df = pd.DataFrame(rows, columns=["user_id", "country", "last_update_date"])
        df["last_update_date"] = pd.to_datetime(df["last_update_date"])

        # Group by day or month
        if group_by == "day":
            df_grouped = (
                df.groupby(["country", df["last_update_date"].dt.date])  # group by date
                .size()
                .reset_index(name="Count")
                )
            df_grouped["Date"] = df_grouped["last_update_date"].apply(
                lambda x: pd.Timestamp(x).isoformat())

        elif group_by == "month":
            df_grouped = (
                df.groupby(["country", df["last_update_date"].dt.to_period("M")])
                .size()
                .reset_index(name="Count")
                )
            df_grouped["Date"] = df_grouped["last_update_date"].apply(lambda x: x.to_timestamp().isoformat())

        else:
            raise ValueError("group_by must be either 'day' or 'month'")

        # Return as list of dicts
        dic = {country: g[["Date", "Count"]].to_dict("records") for country, g in df_grouped.groupby("country")}

        for country in dic:
            total = 0

            for d in dic[country]:
                total += d["Count"]
            dic[country].append({"Total Count": total})

        return dic



    if 'custom_start_date' in event:
        start_date = event['custom_start_date']
        end_date = event['custom_end_date']
        group_by = event['custom_group_by']
        beneficiaries_custom = get_beneficiaries_dic((start_date, end_date), group_by)

    else:
        beneficiaries_custom = []

    # Obtains the dictionaries for beneficiaries in the Virginia database categorized by time and country.
    beneficiaries_7_days = get_beneficiaries_dic("7 days", "day")
    beneficiaries_30_days = get_beneficiaries_dic("30 days", "day")
    beneficiaries_1_year = get_beneficiaries_dic("1 year", "day")
    beneficiaries_all = get_beneficiaries_dic("all", "month")
    beneficiaries_country_7_days = get_beneficiaries_country_dic("7 days", "day")
    beneficiaries_country_30_days = get_beneficiaries_country_dic("30 days", "day")
    beneficiaries_country_1_year = get_beneficiaries_country_dic("1 year", "month")
    beneficiaries_country_all = get_beneficiaries_country_dic("all", "month")



    response_body = {"Beneficiaries count 7 days": beneficiaries_7_days,
    "Beneficiaries count 30 days": beneficiaries_30_days,
    "Beneficiaries count 1 year": beneficiaries_1_year,
    "Beneficiaries count all": beneficiaries_all,
    "Beneficiaries count custom date range": beneficiaries_custom,
    "Beneficiaries count by country 7 days": beneficiaries_country_7_days,
    "Beneficiaries count by country 30 days": beneficiaries_country_30_days,
    "Beneficiaries count by country 1 year": beneficiaries_country_1_year,
    "Beneficiaries count by country all": beneficiaries_country_all
    }

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
        "custom_start_date": "2026-04-03",
        "custom_end_date": "2026-04-16",
        "custom_group_by": "day",
    }
    event = {}
    print(lambda_handler(event, ""))
