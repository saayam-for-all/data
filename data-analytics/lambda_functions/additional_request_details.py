import json
import os
import boto3 
import psycopg2
from psycopg2.extras import RealDictCursor


SCHEMA_NAME = "virginia_dev_saayam_rdbms"


def get_default_response(request_id):
    return {"requestId": request_id,
        "additionalFields": {}
    }

def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=str)
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

def fetch_additional_request_info(cursor, request_id):

    query = f"""
        SELECT *
        FROM {SCHEMA_NAME}.req_add_info r
        WHERE r.req_id = %s
    """

    cursor.execute(query, (request_id,))
    rows = cursor.fetchall()


    response = {}

    for row in rows:
        if row['field_id'] in response:
            if row['item_id'] and not row['field_value']:
                response[row['field_id']].append(row['item_id'])
            elif row['item_id'] and row['field_value']:
                response[row['field_id']][row['item_id']] = row['field_value']
            elif not row['item_id'] and row['field_value']:
                response[row['field_id']] = row['field_value']
        else:
            if row['item_id'] and not row['field_value']:
                response[row['field_id']] = [row['item_id']]
            elif row['item_id'] and row['field_value']:
                response[row['field_id']] = {row['item_id']: row['field_value']}
            elif not row['item_id'] and row['field_value']:
                response[row['field_id']] = row['field_value']
    
    return response


def lambda_handler(event, context):
    conn = None
    cursor = None
    request_id = event.get("request_id")
    full_response = get_default_response(request_id)

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            response = fetch_additional_request_info(cursor, request_id)
            full_response["additionalFields"] = response

        except Exception as error:
            print(f"Additional request info query failed: {error}")
            full_response["additionalFields"] = {}

        return build_response(200, full_response)

    except Exception as error:
        print(f"DB connection failed: {error}")
        return build_response(500, {"error": "DE 1000: Internal Server Error"})

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    result_default = lambda_handler({}, None)
    print(json.dumps(result_default, indent=2))

