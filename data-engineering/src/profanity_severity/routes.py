"""Flask route that scores a help request and routes it by severity (#422)."""

from flask import Blueprint, jsonify, request

from src.extensions import db
from src.models.fraud_requests import FraudRequests
from src.profanity_severity.lambda_function import (
    SeverityError,
    error_body,
    error_status,
    get_severity,
)
from src.profanity_severity.routing import RoutingError, route_by_severity

profanity_bp = Blueprint("profanity", __name__)


def _invalid_input(message):
    return jsonify({
        "classification_status": "not_classified",
        "severity_score": None,
        "flagged_categories": None,
        "error_code": "invalid_input",
        "error": message,
    }), 400


@profanity_bp.route('/api/check_profanity', methods=['POST'])
def check_profanity():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _invalid_input("A JSON object body is required.")

    user_id = data.get('user_id')
    if isinstance(user_id, bool) or not isinstance(user_id, (str, int)) or not str(user_id).strip():
        return _invalid_input("user_id is required.")

    try:
        result = get_severity(
            data.get('subject'),
            data.get('description'),
            authorization=request.headers.get('Authorization'),
        )
    except SeverityError as error:
        return jsonify(error_body(error)), error_status(error)

    try:
        routing = route_by_severity(
            result["severity_score"], user_id, db.session, FraudRequests
        )
    except RoutingError:
        return jsonify({
            **result,
            "is_flagged": True,
            "routing": "failed",
            "error_code": "flagged_request_not_recorded",
            "error": "The request was flagged but could not be recorded.",
        }), 500

    return jsonify({**result, **routing}), 200
