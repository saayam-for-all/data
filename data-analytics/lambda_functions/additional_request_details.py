import json
import os
import boto3 
import psycopg2
from psycopg2.extras import RealDictCursor
import re



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

def check_if_datetime(value: str) -> bool:
    # Simple regex for basic datetime format (you can adjust this as needed)
    datetime_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}T')
    return bool(datetime_pattern.match(value))

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
            # field_id already exists — append or extend the existing entry
            if row['item_id'] and not row['field_value']:
                # Radio/checkbox: another selection for the same field, append to list
                response[row['field_id']].append(row['item_id'])
            elif row['item_id'] and row['field_value']:
                if check_if_datetime(row['field_value']):
                    # Date&time with item_id: add _date and _time keys to existing dict
                    date = row['field_value'].split('T')[0]
                    time = row['field_value'].split('T')[1]
                    date_key = f"{row['item_id']}_date"
                    time_key = f"{row['item_id']}_time"
                    response[row['field_id']][date_key] = date
                    response[row['field_id']][time_key] = time
                else:
                    # Non-datetime with item_id: add item_id → field_value to existing dict
                    response[row['field_id']][row['item_id']] = row['field_value']
            elif not row['item_id'] and row['field_value']:
                if check_if_datetime(row['field_value']):
                    # Date&time with no item_id: use field_id as key prefix
                    date = row['field_value'].split('T')[0]
                    time = row['field_value'].split('T')[1]

                    date_key = f"{row['field_id']}_date"
                    time_key = f"{row['field_id']}_time"

                    response[row['field_id']][date_key] = date
                    response[row['field_id']][time_key] = time
                else:
                    # Textbox: overwrite with new value (same field_id, no item_id — shouldn't repeat but just in case)
                    response[row['field_id']] = row['field_value']
        else:
            # field_id not yet in response — create the entry
            if row['item_id'] and not row['field_value']:
                # Radio/checkbox: start a new list with this item_id
                response[row['field_id']] = [row['item_id']]
            elif row['item_id'] and row['field_value']:
                if check_if_datetime(row['field_value']):
                    # Date&time with item_id: create dict with _date and _time keys
                    date = row['field_value'].split('T')[0]
                    time = row['field_value'].split('T')[1]

                    date_key = f"{row['item_id']}_date"
                    time_key = f"{row['item_id']}_time"

                    response[row['field_id']] = {date_key: date, time_key: time}
                else:
                    # Non-datetime with item_id: create dict with item_id → field_value
                    response[row['field_id']] = {row['item_id']: row['field_value']}
            elif not row['item_id'] and row['field_value']:
                if check_if_datetime(row['field_value']):
                    # Date&time with no item_id: use field_id as key prefix
                    date = row['field_value'].split('T')[0]
                    time = row['field_value'].split('T')[1]

                    date_key = f"{row['field_id']}_date"
                    time_key = f"{row['field_id']}_time"

                    response[row['field_id']] = {date_key: date, time_key: time}
                else:
                    response[row['field_id']] = row['field_value']

    return response


def lambda_handler(event, context):
    conn = None
    cursor = None
    request_id = event.get("request_id")
    full_response = get_default_response(request_id)

    if not request_id:
        return build_response(400, {"error": "DE 1002: Internal Server Error"})

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        try:
            response = fetch_additional_request_info(cursor, request_id)
            full_response["additionalFields"] = response

        except Exception as error:
            print(f"Additional request info query failed: {error}")
            return build_response(500, {"error": "DE 1001: Internal Server Error"})

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
    result = lambda_handler({"request_id": "test-request-id"}, None)
    print(json.dumps(result, indent=2))


