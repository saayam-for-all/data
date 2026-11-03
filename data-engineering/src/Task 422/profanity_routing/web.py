"""A runnable Flask entry point and an embeddable blueprint."""

from flask import Blueprint, Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from .service import RoutingService, handle_submission


def create_blueprint(service: RoutingService) -> Blueprint:
    """Expose the screening gate at both request and check-profanity routes."""
    blueprint = Blueprint("task422", __name__)

    @blueprint.post("/api/help_requests")
    @blueprint.post("/api/check_profanity")
    def submit_request():
        """Accept JSON and acknowledge only a fully persisted routing result."""
        payload, status = handle_submission(service, request.get_json(silent=True))
        return jsonify(payload), status

    return blueprint


def create_app(service: RoutingService) -> Flask:
    """Build the standalone app without connecting to AWS or creating tables."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16_384
    app.register_blueprint(create_blueprint(service))

    @app.get("/health")
    def health():
        """Report process liveness without touching upstream dependencies."""
        return jsonify({"status": "ok"})

    @app.errorhandler(HTTPException)
    def http_error(error):
        """Use JSON for malformed, oversized, and unsupported HTTP requests."""
        return jsonify({"error_code": "http_error", "message": error.name}), error.code

    return app
