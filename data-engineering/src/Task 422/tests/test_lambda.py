"""API Gateway and direct invocation use the same routing service."""

import base64
import json

import pytest

import lambda_function


@pytest.mark.parametrize("mode", ["direct", "v1", "v2", "base64"])
def test_lambda_invocation(service, submission, monkeypatch, mode):
    """All supported event forms persist and return the validated score."""
    monkeypatch.setattr(lambda_function, "get_service", lambda: service)
    event = submission
    if mode != "direct":
        event = {"body": json.dumps(submission)}
        if mode == "v1":
            event["httpMethod"] = "POST"
        if mode == "v2":
            event["requestContext"] = {"http": {"method": "POST"}}
        if mode == "base64":
            event.update(
                body=base64.b64encode(event["body"].encode()).decode(), isBase64Encoded=True
            )
    result = lambda_function.lambda_handler(event, None)
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["severity_score"] == 0


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        {"body": "{"},
        {"body": None},
        {"body": "***", "isBase64Encoded": True},
        {"body": "x" * 20_000},
        {"body": "{}", "requestContext": None},
    ],
)
def test_malformed_lambda_event(event):
    """Malformed events fail before configuration or infrastructure is accessed."""
    assert lambda_function.lambda_handler(event, None)["statusCode"] == 400


def test_lambda_wrong_method():
    """The proxy endpoint accepts submissions only through POST."""
    assert (
        lambda_function.lambda_handler({"httpMethod": "GET", "body": "{}"}, None)["statusCode"]
        == 405
    )


def test_lambda_configuration_failure_is_sanitized(monkeypatch, submission):
    """Never return connection strings or API credentials from setup errors."""

    def broken_service():
        """Represent a private configuration failure."""
        raise ValueError("private credential")

    monkeypatch.setattr(lambda_function, "get_service", broken_service)
    result = lambda_function.lambda_handler(submission, None)
    assert result["statusCode"] == 503
    assert "private credential" not in result["body"]
