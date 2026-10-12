"""Help request workflow with profanity classification and routing.
Evaluates incoming help requests for safety and profanity using an external profanity api
and routes records to appropriate database table.

Following profanity API classification scores are assumed.
0 - clean request
1 - foul language
2 - depressive or suicidal content
3 - threatening content.

Routing Logic:
    - Clean requests are routed to 'request' table.
    - Rest are routed to 'fraud_requests' table.

All non-nullable columns required by the 'request' table are expected in the request payload.
"""

import json
import os

import psycopg2
import requests
from psycopg2.extras import RealDictCursor

SCHEMA_NAME = "virginia_dev_saayam_rdbms"
TABLE_REQUEST = f"{SCHEMA_NAME}.request"
TABLE_FRAUD = f"{SCHEMA_NAME}.fraud_requests"

# all non-nullable keys required for request table
REQUIRED_PARAMS = [
    "user_id",
    "req_for_id",
    "req_islead_id",
    "req_cat_id",
    "req_type_id",
    "req_priority_id",
    "req_status_id",
    "req_subj",
    "req_desc",
]

VALID_SCORES = {0, 1, 2, 3}
ALLOWED_SCORES = {0}


def parse_event_body(event):
    if not event:
        return {}
    body = event.get("body")
    if body is None:
        return event
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    if isinstance(body, dict):
        return body
    return {}


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }


def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "saayam_db"),
        user=os.environ.get("DB_USER", os.getenv("USER")),
        password=os.environ.get("DB_PASSWORD", ""),
    )


def validate_params(request_body):
    missing = [
        param for param in REQUIRED_PARAMS if request_body.get(param) in (None, "")
    ]
    if missing:
        raise ValueError(f"Missing request parameters: {', '.join(missing)}")


def profanity_score(text):
    """
    Sends the help request text to the Profanity API and
    returns the classification score (0-3).
    """
    api_url = os.environ["PROFANITY_API_URL"]

    response = requests.post(
        api_url,
        json={"text": text},
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    response.raise_for_status()

    result = response.json()
    score = int(result["score"])

    if score not in VALID_SCORES:
        raise ValueError(f"Profanity API returned an unexpected score: {score}")

    return score


def insert_request(cursor, params):
    query = f"""
        INSERT INTO {TABLE_REQUEST} (
            req_user_id, req_for_id, req_islead_id, req_cat_id,
            req_type_id, req_priority_id, req_status_id, req_loc,
            iscalamity, req_subj, req_desc, req_doc_link, audio_req_desc,
            submission_date, last_update_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        RETURNING req_id;
    """
    sql_args = [
        params["user_id"],
        params["req_for_id"],
        params["req_islead_id"],
        params["req_cat_id"],
        params["req_type_id"],
        params["req_priority_id"],
        params["req_status_id"],
        params.get("req_loc"),
        params.get("iscalamity"),
        params["req_subj"],
        params["req_desc"],
        params.get("req_doc_link"),
        params.get("audio_req_desc"),
    ]
    cursor.execute(query, sql_args)
    row = cursor.fetchone()
    return row["req_id"]


def insert_fraud_request(cursor, params, score):
    query = f"""
        INSERT INTO {TABLE_FRAUD} (user_id, request_datetime, reason)
        VALUES (%s, NOW(), %s)
        RETURNING fraud_request_id;
    """
    cursor.execute(query, [params["user_id"], f"Profanity score {score}"])
    row = cursor.fetchone()
    return row["fraud_request_id"]


def lambda_handler(event, context):
    conn = None
    cursor = None
    try:
        params = parse_event_body(event)
        validate_params(params)

        text = f"{params['req_subj']} {params['req_desc']}"
        score = profanity_score(text)

        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if score in ALLOWED_SCORES:
            req_id = insert_request(cursor, params)
            result = {"score": score, "routed_to": "request", "req_id": req_id}
        else:
            fraud_request_id = insert_fraud_request(cursor, params, score)
            result = {
                "score": score,
                "routed_to": "fraud_requests",
                "fraud_request_id": fraud_request_id,
            }
        conn.commit()
        return build_response(200, result)

    except ValueError as e:
        return build_response(400, {"value_error": str(e)})
    except Exception as e:
        if conn:
            conn.rollback()
        return build_response(500, {"error": str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    # Local test on local db only

    profanity_score = lambda text: 0
    test_event = {
        "user_id": "REQ-000002",
        "req_for_id": 2,
        "req_islead_id": 4,
        "req_cat_id": "CAT-OTHER",
        "req_type_id": 3,
        "req_priority_id": 4,
        "req_status_id": 3,
        "req_subj": "Help with travel this month",
        "req_desc": "Requesting recurring support until situation stabilizes.",
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))
    
    profanity_score = lambda text: 3
    test_event = {
        "user_id": "REQ-000005",
        "req_for_id": 8,
        "req_islead_id": 8,
        "req_cat_id": "CAT-OTHER",
        "req_type_id": 30,
        "req_priority_id": 2,
        "req_status_id": 4,
        "req_subj": "Help with dealing with neighbor",
        "req_desc": "Requesting to teach noisy neighbor some lesson",
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))




