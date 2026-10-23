"""Tests for the Profanity API severity integration (#422).

The upstream API is replaced with fakes: no network, AWS or database access.
"""

import json
import urllib.error
import urllib.request

import pytest

from src.profanity_severity import lambda_function as ps
from src.profanity_severity.lambda_function import (
    SeverityError,
    derive_severity,
    get_severity,
    lambda_handler,
)

API_URL = "https://api.example.test/requests/v0.0.1/checkProfanity"


class FakeResponse:
    def __init__(self, body, status=200):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeApi:
    """Records upstream calls; returns or raises what the test configured."""

    def __init__(self, body=None, status=200, error=None):
        self.body, self.status, self.error = body, status, error
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.body, self.status)


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("PROFANITY_API_URL", API_URL)
    monkeypatch.setenv("PROFANITY_SCORE_FIELD", "severity_score")
    monkeypatch.delenv("PROFANITY_API_TIMEOUT", raising=False)


@pytest.fixture
def api(monkeypatch):
    """Install a FakeApi as the transport used by the handler."""

    def install(**kwargs):
        fake = FakeApi(**kwargs)
        monkeypatch.setattr(ps._OPENER, "open", fake)
        return fake

    return install


def event(subject="Need help", description="Please help with groceries", headers=None):
    ev = {"body": json.dumps({"subject": subject, "description": description})}
    if headers is not None:
        ev["headers"] = headers
    return ev


def invoke(**kwargs):
    result = lambda_handler(event(**kwargs), None)
    return result["statusCode"], json.loads(result["body"])


def assert_not_scored(status, body, expected_status, code):
    assert status == expected_status
    assert body["severity_score"] is None
    assert body["classification_status"] != "complete"
    assert body["error_code"] == code


# ---- scores 0-3 ----------------------------------------------------------

@pytest.mark.parametrize("score", [0, 1, 2, 3])
def test_each_valid_score_is_returned(api, score):
    api(body={"severity_score": score})
    status, body = invoke()
    assert status == 200
    assert body == {
        "classification_status": "complete",
        "severity_score": score,
        "flagged_categories": None,
    }


def test_extra_upstream_fields_are_ignored(api):
    api(body={"severity_score": 2, "contains_profanity": True, "profanity": ["x"]})
    status, body = invoke()
    assert status == 200
    assert body["severity_score"] == 2
    assert "profanity" not in body


def test_nested_score_field_via_dotted_path(api, monkeypatch):
    monkeypatch.setenv("PROFANITY_SCORE_FIELD", "result.severity")
    api(body={"result": {"severity": 3}})
    status, body = invoke()
    assert status == 200
    assert body["severity_score"] == 3


# ---- invalid / malformed scores are rejected ------------------------------

@pytest.mark.parametrize(
    "upstream",
    [
        {},                                  # missing field
        {"severity_score": None},
        {"severity_score": "2"},             # string
        {"severity_score": 2.0},             # float
        {"severity_score": 1.5},
        {"severity_score": True},            # bool is not a score
        {"severity_score": False},
        {"severity_score": -1},
        {"severity_score": 4},
        {"severity_score": [1]},
        {"severity_score": {"v": 1}},
        {"other": 1},
        [],                                  # not an object
        "2",
        2,
        None,
    ],
)
def test_invalid_scores_are_never_clean(api, upstream):
    api(body=upstream)
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_response_invalid")
    assert body["classification_status"] == "degraded"


def test_unparseable_upstream_body_is_invalid_response(api):
    api(body=b"<html>Bad gateway</html>")
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_response_invalid")


def test_non_utf8_upstream_body_is_invalid_response(api):
    api(body=b"\xff\xfe\x00")
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_response_invalid")


def test_nested_field_with_non_object_parent_is_invalid(api, monkeypatch):
    monkeypatch.setenv("PROFANITY_SCORE_FIELD", "result.severity")
    api(body={"result": 3})
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_response_invalid")


# ---- upstream failures never become score 0 --------------------------------

@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("connection refused for https://secret-host"),
        urllib.error.HTTPError(API_URL, 500, "Internal Server Error", {}, None),
        urllib.error.HTTPError(API_URL, 429, "Too Many Requests", {}, None),
        TimeoutError("timed out"),
        ConnectionResetError("reset"),
        OSError("network down"),
    ],
)
def test_upstream_errors_are_degraded_503(api, error):
    api(error=error)
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_unavailable")
    assert body["classification_status"] == "degraded"
    assert "secret-host" not in json.dumps(body)


@pytest.mark.parametrize("http_status", [302, 404, 500, 503])
def test_non_2xx_status_is_never_scored_even_with_score_body(api, http_status):
    api(body={"severity_score": 0}, status=http_status)
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_unavailable")


# ---- redirects must never carry the Authorization header ---------------------

@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_redirect_handler_refuses_every_redirect(code):
    handler = ps._NoRedirectHandler()
    request = urllib.request.Request(API_URL, data=b"{}", headers={"Authorization": "tok"})
    assert handler.redirect_request(request, None, code, "Moved", {}, "https://evil.test/x") is None


@pytest.mark.parametrize("code", [301, 302, 307, 308])
def test_redirect_is_not_followed_and_token_is_not_forwarded(code):
    """Real loopback servers: the redirect target must never receive a request."""
    import http.server
    import threading

    received = []

    class Target(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(("POST", dict(self.headers)))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"severity_score": 0}')

        do_GET = do_POST

        def log_message(self, *args):
            pass

    target = http.server.HTTPServer(("127.0.0.1", 0), Target)
    target_url = "http://127.0.0.1:%d/collect" % target.server_address[1]

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(code)
            self.send_header("Location", target_url)
            self.end_headers()

        def log_message(self, *args):
            pass

    redirector = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
    servers = [target, redirector]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        with pytest.raises(SeverityError) as excinfo:
            ps.call_profanity_api(
                "http://127.0.0.1:%d/check" % redirector.server_address[1],
                "Help", "text", timeout=5, authorization="secret-token",
            )
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()

    assert excinfo.value.code == "profanity_api_unavailable"
    assert received == []


# ---- configuration --------------------------------------------------------

@pytest.mark.parametrize(
    "env",
    [
        {"PROFANITY_API_URL": ""},
        {"PROFANITY_API_URL": "http://insecure.example.test/x"},
        {"PROFANITY_API_URL": "ftp://x"},
        {"PROFANITY_API_TIMEOUT": "abc"},
        {"PROFANITY_API_TIMEOUT": "0"},
        {"PROFANITY_API_TIMEOUT": "-5"},
    ],
)
def test_missing_or_invalid_config_is_503_without_calling_upstream(api, monkeypatch, env):
    fake = api(body={"severity_score": 0})
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_not_configured")
    assert fake.requests == []


def test_unset_url_is_503(api, monkeypatch):
    fake = api(body={"severity_score": 0})
    monkeypatch.delenv("PROFANITY_API_URL")
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_not_configured")
    assert fake.requests == []


def test_timeout_is_configurable_and_defaults_to_ten_seconds(api, monkeypatch):
    fake = api(body={"severity_score": 0})
    invoke()
    monkeypatch.setenv("PROFANITY_API_TIMEOUT", "2.5")
    invoke()
    assert fake.timeouts == [10, 2.5]


# ---- upstream request -----------------------------------------------------

def test_upstream_request_shape(api):
    fake = api(body={"severity_score": 1})
    invoke(subject="Hello", description="World")
    request = fake.requests[0]
    assert request.full_url == API_URL
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"subject": "Hello", "description": "World"}
    assert request.get_header("Content-type") == "application/json"
    assert request.get_header("Authorization") is None


def test_authorization_header_is_forwarded_case_insensitively(api):
    fake = api(body={"severity_score": 1})
    invoke(headers={"authorization": "tok123"})
    assert fake.requests[0].get_header("Authorization") == "tok123"


def test_non_string_authorization_is_not_forwarded(api):
    fake = api(body={"severity_score": 1})
    invoke(headers={"Authorization": 123})
    assert fake.requests[0].get_header("Authorization") is None


# ---- input validation -----------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"subject": "Help"},
        {"description": "text"},
        {"subject": None, "description": "text"},
        {"subject": 5, "description": "text"},
        {"subject": "Help", "description": ["x"]},
        {"subject": "   ", "description": ""},
    ],
)
def test_invalid_input_returns_400_without_calling_upstream(api, payload):
    fake = api(body={"severity_score": 0})
    result = lambda_handler({"body": json.dumps(payload)}, None)
    body = json.loads(result["body"])
    assert_not_scored(result["statusCode"], body, 400, "invalid_input")
    assert body["classification_status"] == "not_classified"
    assert fake.requests == []


@pytest.mark.parametrize("bad_event", [{"body": "not json"}, {"body": "[1]"}, {"body": None}, None, "text"])
def test_unparseable_event_returns_400(api, bad_event):
    fake = api(body={"severity_score": 0})
    result = lambda_handler(bad_event, None)
    assert result["statusCode"] == 400
    assert json.loads(result["body"])["severity_score"] is None
    assert fake.requests == []


def test_direct_invocation_without_body_wrapper(api):
    api(body={"severity_score": 2})
    result = lambda_handler({"subject": "Help", "description": "food please"}, None)
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["severity_score"] == 2


def test_subject_only_is_allowed(api):
    api(body={"severity_score": 0})
    status, body = invoke(subject="Need food", description="")
    assert status == 200
    assert body["severity_score"] == 0


# ---- response format ------------------------------------------------------

def test_response_uses_lambda_proxy_format(api):
    api(body={"severity_score": 0})
    result = lambda_handler(event(), None)
    assert set(result) == {"statusCode", "headers", "body"}
    assert result["headers"]["Content-Type"] == "application/json"
    assert result["headers"]["Access-Control-Allow-Origin"] == "*"
    assert isinstance(result["body"], str)


def test_error_response_has_same_keys_as_success_plus_error_fields(api):
    api(body={"severity_score": 1})
    _, ok = invoke()
    api(error=TimeoutError())
    _, failed = invoke()
    assert set(ok) <= set(failed)
    assert set(failed) - set(ok) == {"error_code", "error"}


# ---- unit-level helpers ---------------------------------------------------

def test_derive_severity_rejects_bool_score():
    with pytest.raises(SeverityError):
        derive_severity({"s": True}, "s")


def test_derive_severity_reports_source():
    assert derive_severity({"severity_score": 2})["source"] == "score"
    assert derive_severity({"contains_profanity": True, "contains_depressive_content": False,
                            "contains_suicidal_content": False,
                            "contains_threatening_content": False})["source"] == "flags"


def test_get_severity_accepts_injected_opener():
    fake = FakeApi(body={"severity_score": 3})
    assert get_severity("Help", "text", opener=fake)["severity_score"] == 3


# ---- scoring from classification flags ------------------------------------

def flags(**overrides):
    body = {
        "contains_profanity": False,
        "contains_depressive_content": False,
        "contains_suicidal_content": False,
        "contains_threatening_content": False,
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize(
    "overrides, score, categories",
    [
        ({}, 0, []),
        ({"contains_profanity": True}, 1, ["profanity"]),
        ({"contains_depressive_content": True}, 2, ["depressive_or_suicidal"]),
        ({"contains_suicidal_content": True}, 2, ["depressive_or_suicidal"]),
        ({"contains_threatening_content": True}, 3, ["threatening"]),
    ],
)
def test_single_flag_scores(api, overrides, score, categories):
    api(body=flags(**overrides))
    status, body = invoke()
    assert status == 200
    assert body["severity_score"] == score
    assert [c["category"] for c in body["flagged_categories"]] == categories


def test_depressive_and_suicidal_together_list_one_category(api):
    api(body=flags(contains_depressive_content=True, contains_suicidal_content=True))
    _, body = invoke()
    assert body["severity_score"] == 2
    assert body["flagged_categories"] == [{"score": 2, "category": "depressive_or_suicidal"}]


@pytest.mark.parametrize(
    "overrides, score, categories",
    [
        ({"contains_profanity": True, "contains_depressive_content": True}, 2, [1, 2]),
        ({"contains_profanity": True, "contains_threatening_content": True}, 3, [1, 3]),
        ({"contains_suicidal_content": True, "contains_threatening_content": True}, 3, [2, 3]),
        (
            {
                "contains_profanity": True,
                "contains_depressive_content": True,
                "contains_threatening_content": True,
            },
            3,
            [1, 2, 3],
        ),
    ],
)
def test_mixed_classifications_use_highest_score_and_list_all(api, overrides, score, categories):
    api(body=flags(**overrides))
    _, body = invoke()
    assert body["severity_score"] == score
    assert [c["score"] for c in body["flagged_categories"]] == categories


@pytest.mark.parametrize("missing", list(flags()))
def test_missing_flag_is_an_error_not_false(api, missing):
    payload = flags(contains_threatening_content=True)
    payload.pop(missing)
    api(body=payload)
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_response_invalid")


@pytest.mark.parametrize("bad", [None, "false", "true", 0, 1, [], {}])
@pytest.mark.parametrize("flag", list(flags()))
def test_non_boolean_flag_is_an_error(api, flag, bad):
    api(body=flags(**{flag: bad}))
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_response_invalid")


def test_partial_flags_with_only_one_present_is_an_error(api):
    api(body={"contains_threatening_content": True})
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_response_invalid")


# ---- numeric score together with flags -------------------------------------

def test_score_and_matching_flags_agree(api):
    api(body={**flags(contains_profanity=True), "severity_score": 1})
    _, body = invoke()
    assert body["severity_score"] == 1
    assert body["flagged_categories"] == [{"score": 1, "category": "profanity"}]


def test_conflicting_values_escalate_to_the_higher_score(api):
    api(body={**flags(contains_threatening_content=True), "severity_score": 0})
    _, body = invoke()
    assert body["severity_score"] == 3

    api(body={**flags(), "severity_score": 2})
    _, body = invoke()
    assert body["severity_score"] == 2


def test_partial_flags_with_valid_score_can_only_escalate(api):
    api(body={"severity_score": 1, "contains_threatening_content": True})
    _, body = invoke()
    assert body["severity_score"] == 3

    api(body={"severity_score": 2, "contains_profanity": False})
    _, body = invoke()
    assert body["severity_score"] == 2          # a false partial flag never lowers it


def test_partial_flags_with_score_are_still_type_checked(api):
    api(body={"severity_score": 0, "contains_threatening_content": "false"})
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_response_invalid")


def test_invalid_score_is_an_error_even_when_flags_are_valid(api):
    api(body={**flags(), "severity_score": "1"})
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_response_invalid")


def test_null_score_is_an_error_not_absent(api):
    api(body={**flags(), "severity_score": None})
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_response_invalid")


def test_custom_score_field_with_flags_present(api, monkeypatch):
    monkeypatch.setenv("PROFANITY_SCORE_FIELD", "result.level")
    api(body={**flags(), "result": {"level": 2}})
    _, body = invoke()
    assert body["severity_score"] == 2


# ---- degraded / error payloads must never score as clean --------------------

LEGACY_DEGRADED = {
    "status_code": 500,
    "Error": "Invalid API key or issue with the model",
    **flags(),
    "0. This is a normal request": [],
}


@pytest.mark.parametrize(
    "payload",
    [
        LEGACY_DEGRADED,
        {**flags(), "status_code": 500},
        {**flags(), "status_code": "200"},
        {**flags(), "Error": "model unavailable"},
        {**flags(), "error": "model unavailable"},
        {**flags(), "error_code": "classifier_unavailable"},
        {**flags(), "errorMessage": "boom"},
        {**flags(), "classification_status": "degraded"},
        {"severity_score": 0, "classification_status": "degraded"},
        {"severity_score": 0, "error": "upstream failure"},
    ],
)
def test_degraded_upstream_payload_is_never_clean(api, payload):
    api(body=payload)
    status, body = invoke()
    assert_not_scored(status, body, 503, "profanity_api_response_invalid")


def test_successful_status_code_field_is_accepted(api):
    api(body={**flags(contains_profanity=True), "status_code": 200, "Error": None})
    status, body = invoke()
    assert status == 200
    assert body["severity_score"] == 1


def test_classification_status_complete_is_accepted(api):
    api(body={**flags(), "classification_status": "complete"})
    status, body = invoke()
    assert status == 200
    assert body["severity_score"] == 0
