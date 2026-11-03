import json
import re
import os
import boto3
import psycopg2

# Constant for Virginia DB SSM Parameter
SSM_PARAMETER_NAME = "/dev/saayam/db/Virginia/Analytics/user"

def get_db_config():
    """
    Fetches database credentials from AWS SSM Parameter Store.
    Includes a fallback for local offline testing.
    """
    try:
        ssm = boto3.client("ssm", region_name="us-east-1")
        response = ssm.get_parameter(
            Name=SSM_PARAMETER_NAME,
            WithDecryption=True
        )
        config = response["Parameter"]["Value"]
        config_list = [line.strip() for line in config.splitlines()]

        host = config_list[1].split()[1][1:-2]
        port = int(config_list[5].split()[1][:-1])
        dbname = config_list[4].split()[2][1:-2]
        user = config_list[2].split()[1][1:-2]
        password = config_list[3].split()[1][1:-2]

        return {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password
        }
    except Exception as e:
        print(f"⚠️ AWS SSM failed ({str(e)}). Falling back to local/mock database config.")
        return {
            "host": "localhost",
            "port": 5432,
            "dbname": "postgres",
            "user": "postgres",
            "password": "password"
        }

def parse_event_body(event):
    """
    Safely parses the event body whether it is a dict or a JSON-string.
    """
    if not event:
        return {}
    if isinstance(event, dict):
        if "body" in event and isinstance(event["body"], str):
            try:
                return json.loads(event["body"])
            except Exception:
                return event
        return event
    if isinstance(event, str):
        try:
            return json.loads(event)
        except Exception:
            return {}
    return {}

def format_datetime_value(value):
    """
    Splits an ISO 8601 datetime string into a tuple of (date_str, time_str).
    Input example: "2026-03-24T14:30:00" -> ("2026-03-24", "14:30:00")
    """
    # Remove 'Z' if present at the end
    clean_val = value[:-1] if value.endswith('Z') else value
    parts = clean_val.split('T')
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else "00:00:00"
    return date_part, time_part

def process_rows(rows):
    """
    Transforms the database query rows into the structured additionalFields layout.
    """
    additional_fields = {}
    datetime_regex = re.compile(r"^\d{4}-\d{2}-\d{2}T")

    for row in rows:
        field_id = row["field_id"]
        item_id = row["item_id"]
        field_value = row["field_value"]

        # Case 1: Date & Time Field Handling (Regex detection on field_value)
        if field_value and datetime_regex.match(str(field_value)):
            date_val, time_val = format_datetime_value(field_value)
            
            if field_id not in additional_fields:
                additional_fields[field_id] = {}
            elif not isinstance(additional_fields[field_id], dict):
                # Fallback safeguard
                additional_fields[field_id] = {}

            if item_id:
                additional_fields[field_id][f"{item_id}_date"] = date_val
                additional_fields[field_id][f"{item_id}_time"] = time_val
            else:
                additional_fields[field_id][f"{field_id}_date"] = date_val
                additional_fields[field_id][f"{field_id}_time"] = time_val

        # Case 2: Radio / Checkbox Field (item_id is not null, field_value is null)
        elif item_id and field_value is None:
            if field_id not in additional_fields:
                additional_fields[field_id] = []
            elif isinstance(additional_fields[field_id], dict):
                # Safeguard type consistency
                additional_fields[field_id] = list(additional_fields[field_id].keys())

            if item_id not in additional_fields[field_id]:
                additional_fields[field_id].append(item_id)

        # Case 3: List with text/number inputs (Both item_id and field_value are not null)
        elif item_id and field_value is not None:
            if field_id not in additional_fields:
                additional_fields[field_id] = {}
            elif not isinstance(additional_fields[field_id], dict):
                additional_fields[field_id] = {}

            additional_fields[field_id][item_id] = field_value

        # Case 4: Textbox / Integer Field (item_id is null, field_value is not null)
        elif item_id is None and field_value is not None:
            additional_fields[field_id] = field_value

    return additional_fields

def lambda_handler(event, context):
    conn = None
    cursor = None
    
    # Pre-parse body to check for request_id immediately
    body = parse_event_body(event)
    request_id = body.get("request_id")

    # Error: request_id missing from payload (DE 1002)
    if not request_id:
        return {
            "statusCode": 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({"error": "DE 1002: Internal Server Error"})
        }

    try:
        # DB connection
        db_config = get_db_config()
        conn = psycopg2.connect(**db_config)
        cursor = conn.cursor()
        
        # Execute query against Virginia schema
        query = """
            SELECT field_id, item_id, field_value 
            FROM virginia_dev_saayam_rdbms.req_add_info 
            WHERE req_id = %s
        """
        cursor.execute(query, (request_id,))
        
        columns = [desc[0] for desc in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        # Structure the payload response
        additional_fields = process_rows(results)

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({
                "requestId": request_id,
                "additionalFields": additional_fields
            })
        }

    except psycopg2.OperationalError as conn_err:
        print("Database Connection Failure:", str(conn_err))
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({"error": "DE 1000: Internal Server Error"})
        }
    except Exception as query_err:
        print("Query/Execution Failure:", str(query_err))
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*"
            },
            "body": json.dumps({"error": "DE 1001: Internal Server Error"})
        }
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()