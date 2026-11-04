"""Flask endpoint for severity-based help-request routing."""

from datetime import datetime

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from src.extensions import db
from src.models.fraud_requests import FraudRequests
from src.profanity import (
    ProfanityAPIError,
    call_profanity_api,
    get_routing_decision,
    parse_profanity_response,
)

profanity_bp = Blueprint("profanity", __name__)


@profanity_bp.route("/api/check_profanity", methods=["POST"])
def check_profanity():
    """Classify a request and record submissions with nonzero severity."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "A JSON object is required"}), 400

    user_id = data.get("user_id")
    subject = data.get("subject")
    description = data.get("description")

    if (
        isinstance(user_id, bool)
        or not isinstance(user_id, (str, int))
        or not str(user_id).strip()
    ):
        return jsonify({"error": "A valid user_id is required"}), 400
    if not isinstance(subject, str) or not subject.strip():
        return jsonify({"error": "A non-empty subject is required"}), 400
    if not isinstance(description, str) or not description.strip():
        return jsonify({"error": "A non-empty description is required"}), 400

    try:
        classification = parse_profanity_response(
            call_profanity_api(subject, description)
        )
    except ProfanityAPIError:
        current_app.logger.exception("Profanity classification failed")
        return jsonify({
            "error": "Unable to classify the request at this time"
        }), 502

    decision = get_routing_decision(classification["severity_score"])
    if classification["is_flagged"]:
        try:
            db.session.add(FraudRequests(
                user_id=str(user_id).strip(),
                request_datetime=datetime.now(),
                reason=decision["reason"],
            ))
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception(
                "Could not record the flagged request"
            )
            return jsonify({
                "error": "Unable to record the flagged request"
            }), 500

    return jsonify({
        "is_flagged": classification["is_flagged"],
        "severity_score": classification["severity_score"],
        "reason": decision["reason"],
        "destination": decision["destination"],
        "flagged_categories": classification["flagged_categories"],
    }), 200
