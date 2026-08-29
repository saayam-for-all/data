import json
import re

import psycopg2
from psycopg2.extras import RealDictCursor
from aws_lambda_powertools.utilities import parameters

SCHEMA_NAME = "virginia_dev_saayam_rdbms"

# ISO datetime detection, e.g. "2026-03-24T14:30:00" or "2026-04-15T17:09:00Z".
# Do NOT hardcode date&time field_ids; decide dynamically from the value.
DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body, default=str)
    }


def error_response(status_code, code):
    return build_response(status_code, {"error": f"{code}: Internal Server Error"})


def get_db_connection():
    creds = json.loads(parameters.get_parameter(
        "/dev/saayam/db/Virginia/Analytics/user",
        decrypt=True,
        max_age=3600
    ))

    return psycopg2.connect(
        host=creds["HOST"],
        database=creds["DATABASE NAME"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require"
    )


def fetch_additional_info_rows(cursor, request_id):
    query = f"""
        SELECT field_id, item_id, field_value
        FROM {SCHEMA_NAME}.req_add_info
        WHERE req_id = %s;
    """
    cursor.execute(query, (request_id,))
    return cursor.fetchall()


def _split_datetime(value):
    """'2026-03-24T14:30:00' -> ('2026-03-24', '14:30:00'); trailing 'Z' stripped."""
    date_part, time_part = value.split("T", 1)
    return date_part, time_part.rstrip("Z")


def build_additional_fields(rows):
    """
    Map req_add_info rows into the additionalFields structure.

    Per row, by (item_id, field_value):
      - value is an ISO datetime  -> field_id: {"<key>_date": d, "<key>_time": t}
                                     where <key> = item_id, or field_id when item_id is null
      - item_id set, value null   -> field_id: [item_id, ...]        (radio/checkbox)
      - item_id set, value set     -> field_id: {item_id: value, ...} (list w/ inputs)
      - item_id null, value set    -> field_id: value                 (textbox/number)
      - item_id null, value null   -> skipped (undefined in spec)

    Assumes a given field_id is shape-consistent across its rows (spec implies this).
    """
    fields = {}
    for row in rows:
        field_id = row["field_id"]
        item_id = row["item_id"]
        value = row["field_value"]

        if value is not None and DATETIME_PATTERN.match(value):
            prefix = item_id if item_id is not None else field_id
            date_part, time_part = _split_datetime(value)
            bucket = fields.setdefault(field_id, {})
            bucket[f"{prefix}_date"] = date_part
            bucket[f"{prefix}_time"] = time_part
        elif item_id is not None and value is None:
            fields.setdefault(field_id, []).append(item_id)
        elif item_id is not None and value is not None:
            fields.setdefault(field_id, {})[item_id] = value
        elif item_id is None and value is not None:
            fields[field_id] = value
        # item_id is None and value is None -> nothing to represent; skip

    return fields


def lambda_handler(event, context):
    event = event or {}
    request_id = event.get("request_id")

    # DE 1002: request_id missing from payload
    if not request_id:
        return error_response(400, "DE 1002")

    conn = None
    cursor = None
    try:
        # DE 1000: DB connection failure
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        except Exception as error:
            print(f"DB connection failed: {error}")
            return error_response(500, "DE 1000")

        # DE 1001: query execution failure
        try:
            rows = fetch_additional_info_rows(cursor, request_id)
        except Exception as error:
            print(f"Query execution failed: {error}")
            return error_response(500, "DE 1001")

        # No rows / request_id not found -> 200 with empty additionalFields
        additional_fields = build_additional_fields(rows) if rows else {}

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
    result = lambda_handler({"request_id": "REQ-00-000-000-015x"}, None)
    body = json.loads(result["body"])

    assert result["statusCode"] == 200
    assert "additionalFields" in body
    assert "requestId" in body
    assert body["requestId"] == "REQ-00-000-000-015x"
    assert isinstance(body["additionalFields"], dict)

    print("All assertions passed")
    print(json.dumps(result, indent=2))
