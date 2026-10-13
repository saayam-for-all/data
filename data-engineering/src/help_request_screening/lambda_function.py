"""Help request screening Lambda (issue #422).

Sends a help request's subject and description to the Profanity API, returns
the 0-3 severity score, and routes the request: clean requests go on to
active matching, flagged ones are saved to the flagged_help_requests table.

Input:  {"req_id": "...", "req_subj": "...", "req_desc": "..."}
        ("subject" / "description" are accepted too)
Output: {"req_id", "severity_score", "severity_label", "route", "flagged"}
        plus "error" when the request was held because the API was unavailable.
"""
import json
import logging
from typing import Any, Optional

from helpers import (
    DESCRIPTION_KEYS,
    SUBJECT_KEYS,
    get_text_field,
    parse_event_body,
    route_by_severity_score,
    unscored_decision,
)
from utils.db_client import DatabaseClient
from utils.profanity_client import (
    InvalidSeverityScoreError,
    ProfanityApiError,
    ProfanityClient,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

RESPONSE_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

# Created on first use and reused across warm invocations.
_profanity_client: Optional[ProfanityClient] = None
_db_client: Optional[DatabaseClient] = None


def get_profanity_client() -> ProfanityClient:
    """Return the shared Profanity API client, creating it from env vars."""
    global _profanity_client
    if _profanity_client is None:
        _profanity_client = ProfanityClient.from_env()
    return _profanity_client


def get_db_client() -> DatabaseClient:
    """Return the shared database client."""
    global _db_client
    if _db_client is None:
        _db_client = DatabaseClient()
    return _db_client


def build_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Build an API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": RESPONSE_HEADERS,
        "body": json.dumps(body),
    }


def screen_help_request(
        body: dict[str, Any], profanity_client: ProfanityClient,
        db_client: DatabaseClient) -> tuple[int, dict[str, Any]]:
    """Score and route one help request; return (status code, response body).

    If the Profanity API fails, the request is held for review rather than
    let through unchecked.
    """
    req_id = str(body.get("req_id") or "").strip()
    if not req_id:
        return 400, {"error": "req_id is required"}

    subject = get_text_field(body, SUBJECT_KEYS)
    description = get_text_field(body, DESCRIPTION_KEYS)
    if not subject and not description:
        return 400, {"error": "A subject or description is required"}

    error = None
    try:
        score = profanity_client.get_severity_score(subject, description)
        decision = route_by_severity_score(score)
    except (ProfanityApiError, InvalidSeverityScoreError) as e:
        logger.warning("Profanity check failed for request %s: %s", req_id, e)
        decision = unscored_decision()
        error = "Profanity API unavailable; request held for manual review"

    if decision.flagged:
        try:
            db_client.record_flagged_request(
                req_id, decision.severity_score, decision.severity_label,
                decision.route)
        except Exception:
            logger.exception("Could not save flagged request %s", req_id)
            return 500, {"error": "Could not save the screening result"}

    result = {"req_id": req_id, **decision.to_dict()}
    if error:
        result["error"] = error
    return 200, result


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point."""
    try:
        body = parse_event_body(event)
    except ValueError as e:
        return build_response(400, {"error": f"Invalid request body: {e}"})

    try:
        status_code, result = screen_help_request(
            body, get_profanity_client(), get_db_client())
    except Exception:
        logger.exception("Help request screening failed")
        return build_response(500, {"error": "Internal server error"})
    return build_response(status_code, result)
