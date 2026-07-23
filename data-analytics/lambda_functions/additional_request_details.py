import json
import re

# Safe import of psycopg2 for environments without the native driver installed
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    psycopg2 = None
    RealDictCursor = None

# Safe import of AWS Lambda Powertools for local environment compatibility
try:
    from aws_lambda_powertools.utilities import parameters
except ImportError:
    class DummyParameters:
        @staticmethod
        def get_parameter(name, decrypt=True, max_age=None):
            raise NotImplementedError("AWS Lambda Powertools parameters utility is not installed.")
    parameters = DummyParameters

SCHEMA_NAME = "virginia_dev_saayam_rdbms"


def build_response(status_code, body):
    """
    Constructs the standard HTTP response structure for Lambda.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }


def get_db_connection():
    """
    Retrieves database credentials from SSM Parameter Store dynamically
    and returns a psycopg2 database connection.
    """
    creds = json.loads(parameters.get_parameter(
        "/dev/saayam/db/Virginia/Analytics/user",
        decrypt=True,
        max_age=3600
    ))

    db_name = creds["DATABASE NAME"]

    return psycopg2.connect(
        host=creds["HOST"],
        database=db_name,
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )


def is_null_val(val):
    """
    Helper to check if a value is NULL, None, or empty.
    """
    if val is None:
        return True
    if isinstance(val, str) and val.strip().upper() == "NULL":
        return True
    if isinstance(val, str) and val.strip() == "":
        return True
    return False


def parse_additional_fields(rows):
    """
    Processes query rows and returns a structured dictionary matching
    the frontend Additional Fields schema requirements.
    """
    # Group rows by field_id
    grouped_fields = {}
    for row in rows:
        field_id = row.get("field_id")
        if not field_id:
            continue
        grouped_fields.setdefault(field_id, []).append(row)
        
    additional_fields = {}
    for field_id, field_rows in grouped_fields.items():
        # Check if any row has a date-time format in field_value
        is_datetime = False
        for row in field_rows:
            val = row.get("field_value")
            if val and not is_null_val(val) and re.match(r"^\d{4}-\d{2}-\d{2}T", str(val)):
                is_datetime = True
                break
                
        if is_datetime:
            dt_dict = {}
            for row in field_rows:
                item_id = row.get("item_id")
                val = row.get("field_value")
                if val and not is_null_val(val) and re.match(r"^\d{4}-\d{2}-\d{2}T", str(val)):
                    date_part = val.split('T')[0]
                    # Handle trailing Z and millisecond values cleanly
                    time_part = val.split('T')[1].replace('Z', '').split('.')[0]
                    prefix = item_id if item_id and not is_null_val(item_id) else field_id
                    dt_dict[f"{prefix}_date"] = date_part
                    dt_dict[f"{prefix}_time"] = time_part
            additional_fields[field_id] = dt_dict
            
        else:
            # Check if any row has a non-null item_id
            has_item_id = False
            for row in field_rows:
                if row.get("item_id") and not is_null_val(row.get("item_id")):
                    has_item_id = True
                    break
                    
            if has_item_id:
                # Are there any rows with non-null field_value?
                has_field_value = False
                for row in field_rows:
                    if row.get("field_value") and not is_null_val(row.get("field_value")):
                        has_field_value = True
                        break
                        
                if has_field_value:
                    # List of objects: map item_id to field_value
                    obj_dict = {}
                    for row in field_rows:
                        item_id = row.get("item_id")
                        val = row.get("field_value")
                        if item_id and not is_null_val(item_id):
                            obj_dict[item_id] = val if not is_null_val(val) else None
                    additional_fields[field_id] = obj_dict
                else:
                    # Radio/checkbox selection: list of selected item_ids
                    item_ids = []
                    for row in field_rows:
                        item_id = row.get("item_id")
                        if item_id and not is_null_val(item_id):
                            item_ids.append(item_id)
                    additional_fields[field_id] = item_ids
            else:
                # Textbox/IntegerField: item_id is null and field_value is not null
                val = None
                for row in field_rows:
                    if row.get("field_value") and not is_null_val(row.get("field_value")):
                        val = row.get("field_value")
                        break
                if val is not None:
                    additional_fields[field_id] = val
                    
    return additional_fields


def lambda_handler(event, context):
    """
    Main Lambda entry point. Handles request validation, DB connection,
    data fetching, mapping, and error handling.
    """
    # Check request_id in event payload (handling both direct invocation and API Gateway string/dict body wrapper)
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

    request_id = None
    if isinstance(payload, dict):
        request_id = payload.get("request_id")
        
    if not request_id:
        # Error DE 1002: request_id missing from payload
        return build_response(400, {"error": "DE 1002: Internal Server Error"})
        
    conn = None
    cursor = None
    try:
        try:
            conn = get_db_connection()
        except Exception as conn_err:
            print(f"DB connection failed: {conn_err}")
            return build_response(500, {"error": "DE 1000: Internal Server Error"})
            
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        try:
            query = f"""
                SELECT field_id, item_id, field_value
                FROM {SCHEMA_NAME}.req_add_info
                WHERE req_id = %s
            """
            cursor.execute(query, (request_id,))
            rows = cursor.fetchall()
        except Exception as query_err:
            print(f"Query execution failed: {query_err}")
            return build_response(500, {"error": "DE 1001: Internal Server Error"})
            
        additional_fields = parse_additional_fields(rows)
        
        return build_response(200, {
            "requestId": request_id,
            "additionalFields": additional_fields
        })
        
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    import unittest.mock as mock
    import csv
    import os
    
    print("Initializing mock connection suite for local testing...")

    # Mock Cursor that reads from our CSV file
    class MockCursor:
        def __init__(self):
            self.rows = []
            
        def execute(self, query, params=None):
            req_id_to_find = params[0] if params else None
            self.rows = []
            
            # Locate the req_add_info.csv file dynamically
            base_dir = os.path.dirname(__file__)
            csv_path = os.path.abspath(os.path.join(base_dir, "..", "sql", "req_add_info.csv"))
            if not os.path.exists(csv_path):
                csv_path = "data-analytics/sql/req_add_info.csv"
                
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("req_id") == req_id_to_find:
                        self.rows.append({
                            "field_id": row.get("field_id"),
                            "item_id": row.get("item_id") if row.get("item_id") != "" else None,
                            "field_value": row.get("field_value") if row.get("field_value") != "" else None
                        })
                        
        def fetchall(self):
            return self.rows
            
        def close(self):
            pass
            
    class MockConnection:
        def cursor(self, cursor_factory=None):
            return MockCursor()
        def close(self):
            pass

    # Patch get_db_connection directly to return MockConnection
    with mock.patch(f"{__name__}.get_db_connection", return_value=MockConnection()):
         
        # Test Case 1: REQ-00-000-000-015x
        print("\n--- Test Case 1: REQ-00-000-000-015x ---")
        result = lambda_handler({"request_id": "REQ-00-000-000-015x"}, None)
        body = json.loads(result["body"])

        assert result["statusCode"] == 200
        assert "additionalFields" in body
        assert "requestId" in body
        assert body["requestId"] == "REQ-00-000-000-015x"
        assert isinstance(body["additionalFields"], dict)
        assert len(body["additionalFields"]) > 0
        assert body["additionalFields"] == {"2.2.x": "shirt", "2.2.x1": ["2.2.B.x"]}
        print("Success: REQ-00-000-000-015x results match expected format!")
        print(json.dumps(body, indent=2))

        # Test Case 2: REQ-123 (Complex mapping check)
        print("\n--- Test Case 2: REQ-123 (Complex) ---")
        result = lambda_handler({"request_id": "REQ-123"}, None)
        body = json.loads(result["body"])
        assert result["statusCode"] == 200
        assert body["requestId"] == "REQ-123"
        assert body["additionalFields"]["1.1.B"] == ["1.1.B.1", "1.1.B.2"]
        assert body["additionalFields"]["1.2.A"] == "some typed response from user"
        assert body["additionalFields"]["1.2.B"] == ["1.2.B.2"]
        assert body["additionalFields"]["2.1.C"] == {"2.1.C.1": "3", "2.1.C.3": "9"}
        assert body["additionalFields"]["6.1.B"] == {
            "6.1.B.1_date": "2026-03-24", "6.1.B.1_time": "14:30:00",
            "6.1.B.2_date": "2026-03-28", "6.1.B.2_time": "14:10:00"
        }
        assert body["additionalFields"]["6.8.C"] == {
            "6.8.C_date": "2026-04-15", "6.8.C_time": "17:09:00"
        }
        print("Success: REQ-123 results match expected format!")
        print(json.dumps(body, indent=2))
        
        # Test Case 3: Missing request_id (DE 1002)
        print("\n--- Test Case 3: Missing request_id ---")
        result = lambda_handler({}, None)
        assert result["statusCode"] == 400
        body = json.loads(result["body"])
        assert body == {"error": "DE 1002: Internal Server Error"}
        print("Success: Missing request_id handled correctly with DE 1002 error!")

        # Test Case 4: Non-existent request_id
        print("\n--- Test Case 4: Non-existent request_id ---")
        result = lambda_handler({"request_id": "REQ-NOT-EXIST"}, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body == {"requestId": "REQ-NOT-EXIST", "additionalFields": {}}
        print("Success: Non-existent request_id returned empty additionalFields!")

        # Test Case 5: API Gateway payload wrapper format
        print("\n--- Test Case 5: API Gateway body wrapper ---")
        result = lambda_handler({"body": "{\"request_id\": \"REQ-00-000-000-015x\"}"}, None)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["requestId"] == "REQ-00-000-000-015x"
        assert body["additionalFields"] == {"2.2.x": "shirt", "2.2.x1": ["2.2.B.x"]}
        print("Success: API Gateway body wrapper parsed successfully!")

        print("\nAll assertions passed successfully!")
