"""POST /api/check_profanity: score a Help Request and route it."""
from flask import Blueprint, jsonify, request

from src.profanity_severity import client, routing, scoring, store

profanity_bp = Blueprint("profanity_severity", __name__)


def _error(status: int, error_code: str, message: str):
    """A response for a request that was not scored (never severity 0)."""
    body = {
        "classification_status": "not_scored",
        "severity_score": None,
        "route": None,
        "proceed_to_matching": False,
        "error_code": error_code,
        "message": message,
    }
    return jsonify(body), status


@profanity_bp.route("/api/check_profanity", methods=["POST"])
def check_profanity():
    """Score a Help Request with the Profanity API and route it.

    Body: {"user_id": str, "subject": str, "description": str}

    200: scored. Score 0 -> route "active_matching", nothing is written and
         the caller continues the normal workflow. Scores 1-3 -> a row is
         written to fraud_requests and proceed_to_matching is false.
    400: invalid input.
    500: flagged but the database write failed (score is still returned).
    503: could not be scored; proceed_to_matching is false.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error(400, "invalid_input", "JSON object body required")

    user_id = data.get("user_id")
    subject = data.get("subject", "")
    description = data.get("description", "")
    if not isinstance(user_id, str) or not user_id.strip():
        return _error(400, "invalid_input", "user_id is required")
    if not isinstance(subject, str) or not isinstance(description, str):
        return _error(400, "invalid_input", "subject and description must be strings")
    if not subject.strip() and not description.strip():
        return _error(400, "invalid_input", "subject or description is required")

    try:
        result = scoring.extract_severity(client.call_profanity_api(subject, description))
    except scoring.ScoringError as exc:
        return _error(503, exc.error_code, "Request could not be scored")

    destination = routing.route_for(result.score)
    body = {
        "classification_status": "complete",
        "severity_score": result.score,
        "flagged_categories": list(result.categories),
        "route": destination.value,
        "proceed_to_matching": destination is routing.Destination.ACTIVE_MATCHING,
    }

    if destination is routing.Destination.FRAUD_REQUESTS:
        try:
            store.record_flagged_request(user_id, routing.build_reason(result))
        except Exception:
            body["recorded"] = False
            body["error_code"] = "db_error"
            return jsonify(body), 500
        body["recorded"] = True

    return jsonify(body), 200
