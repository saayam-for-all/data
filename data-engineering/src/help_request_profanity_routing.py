import json
import os
import urllib.request

import psycopg2
from psycopg2.extras import RealDictCursor

SCHEMA_NAME = "virginia_dev_saayam_rdbms"

# Severity scores returned by the profanity API:
# 0 = clean, 1 = mild, 2 = moderate, 3 = severe
VALID_SCORES = {0, 1, 2, 3}

# Scores allowed into the normal request workflow. Any other score is
# logged in fraud_requests and the request is not sent to matching.
ALLOWED_SCORES = {0, 1}

REQUIRED_FIELDS = [
    "user_id",
    "req_for_id",
    "req_islead_id",
    "req_cat_id",
    "req_type_id",
    "req_priority_id",
    "req_subj",
    "req_desc",
]


# ---------------------------------------------------------------------------
# Response / request plumbing
# ---------------------------------------------------------------------------

def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }


def parse_event_body(event):
    """Accepts either a raw dict (local/test invocation) or an API Gateway
    style event with a JSON-encoded "body" string."""
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


def validate_request(body):
    """Raises ValueError if a required field is missing so the caller can
    return a 400 response."""
    missing = [field for field in REQUIRED_FIELDS if body.get(field) in (None, "")]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# DB connection (local PostgreSQL - no AWS Parameter Store)
# ---------------------------------------------------------------------------

def get_db_connection():
    # Matches .env.example: DATABASE_URL=postgresql://user:password@host:port/dbname
    database_url = os.environ["DATABASE_URL"]
    return psycopg2.connect(database_url)


# ---------------------------------------------------------------------------
# Profanity API
# ---------------------------------------------------------------------------

def get_profanity_score(text):
    """Sends the help request text to the profanity API and returns the
    severity score (0-3)."""
    api_url = os.environ["PROFANITY_API_URL"]

    payload = json.dumps({"text": text}).encode("utf-8")
    api_request = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(api_request, timeout=10) as api_response:
        result = json.loads(api_response.read().decode("utf-8"))

    # NOTE: "severity_score" is the assumed key in the API response.
    score = int(result["severity_score"])

    if score not in VALID_SCORES:
        raise ValueError(f"Profanity API returned an unexpected score: {score}")

    return score


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def get_created_status_id(cursor):
    query = f"""
        SELECT req_status_id
        FROM {SCHEMA_NAME}.request_status
        WHERE req_status = 'CREATED';
    """
    cursor.execute(query)
    row = cursor.fetchone()
    return row["req_status_id"]


def insert_request(cursor, body, status_id):
    # req_id is left out on purpose: the before_insert_requests trigger
    # generates it.
    query = f"""
        INSERT INTO {SCHEMA_NAME}.request (
            req_user_id, req_for_id, req_islead_id, req_cat_id,
            req_type_id, req_priority_id, req_status_id, req_loc,
            iscalamity, req_subj, req_desc, req_doc_link, audio_req_desc,
            submission_date, last_update_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        RETURNING req_id;
    """
    params = [
        body["user_id"],
        body["req_for_id"],
        body["req_islead_id"],
        body["req_cat_id"],
        body["req_type_id"],
        body["req_priority_id"],
        status_id,
        body.get("req_loc"),
        body.get("iscalamity"),
        body["req_subj"],
        body["req_desc"],
        body.get("req_doc_link"),
        body.get("audio_req_desc"),
    ]
    cursor.execute(query, params)
    row = cursor.fetchone()
    return row["req_id"]


def insert_fraud_request(cursor, user_id, score):
    query = f"""
        INSERT INTO {SCHEMA_NAME}.fraud_requests (user_id, request_datetime, reason)
        VALUES (%s, NOW(), %s)
        RETURNING fraud_request_id;
    """
    cursor.execute(query, [user_id, f"Profanity severity score {score}"])
    row = cursor.fetchone()
    return row["fraud_request_id"]


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def lambda_handler(event, context):
    conn = None
    cursor = None

    body = parse_event_body(event)

    try:
        validate_request(body)
    except ValueError as error:
        return build_response(400, {"error": str(error)})

    text = f"{body['req_subj']} {body['req_desc']}"

    try:
        score = get_profanity_score(text)
    except Exception as error:
        print(f"Profanity API call failed: {error}")
        return build_response(502, {"error": "Could not check the request for profanity."})

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        if score in ALLOWED_SCORES:
            status_id = get_created_status_id(cursor)
            req_id = insert_request(cursor, body, status_id)
            result = {
                "severity_score": score,
                "routed_to": "request",
                "req_id": req_id,
            }
        else:
            fraud_request_id = insert_fraud_request(cursor, body["user_id"], score)
            result = {
                "severity_score": score,
                "routed_to": "fraud_requests",
                "fraud_request_id": fraud_request_id,
            }

        conn.commit()
        return build_response(200, result)

    except Exception as error:
        print(f"Routing failed: {error}")
        if conn:
            conn.rollback()
        return build_response(500, {"error": "Could not route the help request."})

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    # Local test only: skips the real API and pretends it returned a score.
    # Change the number (0-3) to test each route.
    get_profanity_score = lambda text: 3

    test_event = {
        "body": json.dumps({
            "user_id": "replace-with-a-real-user-id",
            "req_for_id": 1,
            "req_islead_id": 1,
            "req_cat_id": "replace-with-a-real-user-id",
            "req_type_id": 1,
            "req_priority_id": 1,
            "req_subj": "Test subject",
            "req_desc": "Test description",
        })
    }
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))