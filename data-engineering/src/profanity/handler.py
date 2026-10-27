"""Lambda entry point for Help Request sentiment scoring and routing (#422).

    POST  { "req_user_id": "SID-...", "req_subj": "...", "req_desc": "...",
            "req_cat_id": "1.1", "req_type_id": 2, "req_for_id": 1,
            "req_islead_id": 1, "req_priority_id": 2 }

Returns the sentiment score and the routing decision. A clean request (score
0) is answered with action ALLOW and no row is written here - creating the
request is the existing intake service's job. Scores 1-3 are diverted and
persisted before the response is returned.
"""

import json
import os

import boto3
import psycopg2
from psycopg2.extras import RealDictCursor

from src.profanity.routing import DIVERT, missing_fields, route
from src.profanity.severity import classify_request

SSM_DB_PARAMETER = os.environ.get(
    "SAAYAM_DB_SSM_PARAMETER", "/dev/saayam/db/Virginia/Analytics/user")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }


def parse_event_body(event):
    """Accept both a direct invoke payload and an API Gateway proxy event."""
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


def get_db_connection():
    """Credentials come from SSM Parameter Store - never from the source."""
    ssm = boto3.client("ssm", region_name=AWS_REGION)
    response = ssm.get_parameter(Name=SSM_DB_PARAMETER, WithDecryption=True)

    creds = json.loads(response["Parameter"]["Value"])
    return psycopg2.connect(
        host=creds["HOST"],
        database=creds["DATABASE NAME"],
        user=creds["USERNAME"],
        password=creds["PASSWORD"],
        port=creds["PORT"],
        sslmode="require",
    )


def lambda_handler(event, context):
    conn = None
    cursor = None

    payload = parse_event_body(event)
    subject = (payload.get("req_subj") or "").strip()
    description = (payload.get("req_desc") or "").strip()

    if not subject and not description:
        return build_response(
            400, {"error": "req_subj or req_desc is required"})

    # Scoring is pure, so it happens before any connection is opened; a
    # clean request that the caller only wants scored costs no database work.
    classification = classify_request(subject, description)

    missing = missing_fields(payload)
    if classification["severity_score"] != 0 and missing:
        # Only a diverted request has to be persisted, so only then do the
        # columns the insert needs become mandatory.
        return build_response(422, {
            "error": "request cannot be diverted without: {}".format(
                ", ".join(missing)),
            "severity_score": classification["severity_score"],
            "severity_label": classification["severity_label"],
        })

    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=RealDictCursor)

        decision = route(cursor, payload, classification)

        if decision["action"] == DIVERT:
            conn.commit()

        return build_response(200, {
            "severity_score": decision["severity_score"],
            "severity_label": decision["severity_label"],
            "severity_description": decision["severity_description"],
            "matched_codes": decision["matched_codes"],
            "contains_profanity": classification["contains_profanity"],
            "action": decision["action"],
            "reqId": decision["req_id"],
            "storedIn": decision["stored_in"],
            "requiresHumanReview": decision["requires_human_review"],
            "escalate": decision["escalate"],
            "blocked": decision["blocked"],
        })

    except Exception as exc:
        if conn:
            conn.rollback()
        # The matched terms are deliberately not logged; they are the user's
        # own words and may be sensitive.
        print("profanity routing failed for user {}: {}".format(
            payload.get("req_user_id"), exc))
        return build_response(500, {"error": "Internal server error"})

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
