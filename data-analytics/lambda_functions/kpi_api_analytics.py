import json
import psycopg2
import os

# Virginia RDS table references
REAL_TABLE_REQUEST = "virginia_dev_saayam_rdbms.request"
REAL_TABLE_REQUEST_STATUS = "virginia_dev_saayam_rdbms.request_status"
REAL_TABLE_HELP_CATEGORIES = "virginia_dev_saayam_rdbms.help_categories"


def lambda_handler(event, context):
    conn = None
    cursor = None

    DB_CONFIG = {
        "host": os.environ['host'],
        "port": os.environ['port'],
        "dbname": os.environ['dbname'],
        "user": os.environ['user'],
        "password": os.environ['password']
    }

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        print("Successfully connected to the database")

        response_body = {}

        return {
            "statusCode": 200,
            "body": json.dumps(response_body)
        }

    except Exception as e:
        print("ERROR:", str(e))
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Could not connect to database"})
        }

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print("Database connection closed")