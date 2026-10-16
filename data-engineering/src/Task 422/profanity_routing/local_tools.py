"""Explicit local fixtures and loopback servers; never a production classifier."""

from contextlib import contextmanager
import json
from threading import Thread

from flask import Flask, jsonify, request
from werkzeug.serving import WSGIRequestHandler, make_server


FIXTURE_SCORES = {
    "Normal fixture": (),
    "Profanity fixture": (1,),
    "Support fixture": (2,),
    "Threat fixture": (3,),
    "Mixed fixture": (1, 2, 3),
}


def legacy_flags(scores: tuple[int, ...]) -> dict:
    """Produce the four booleans exposed by the original API source."""
    return {
        "contains_profanity": 1 in scores,
        "contains_depressive_content": 2 in scores,
        "contains_suicidal_content": False,
        "contains_threatening_content": 3 in scores,
    }


def create_mock_api() -> Flask:
    """Return fixed test responses selected by subject, without analyzing text."""
    app = Flask("task422_mock_profanity")

    @app.post("/check-profanity")
    def classify_fixture():
        """Mirror the existing Lambda's success and embedded-error envelopes."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"subject", "description"}:
            return jsonify({"error": "Expected subject and description."}), 400
        subject = payload["subject"]
        if subject == "API outage fixture":
            return jsonify({"error": "Simulated outage."}), 503
        if subject == "Model failure fixture":
            body = {
                **legacy_flags(()),
                "status_code": 500,
                "Error": "Simulated model failure.",
            }
        elif subject in FIXTURE_SCORES:
            body = legacy_flags(FIXTURE_SCORES[subject])
        else:
            return jsonify({"error": "Unknown fixture subject; this is not a classifier."}), 400
        return jsonify({"statusCode": 200, "body": json.dumps(body)})

    return app


class QuietRequestHandler(WSGIRequestHandler):
    """Keep local demo output readable and avoid logging request data."""

    def log(self, log_type, message, *args):
        """Suppress Werkzeug's per-request access log in the local harness."""


@contextmanager
def local_server(app):
    """Run a temporary loopback HTTP server and close it deterministically."""
    server = make_server("127.0.0.1", 0, app, request_handler=QuietRequestHandler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
