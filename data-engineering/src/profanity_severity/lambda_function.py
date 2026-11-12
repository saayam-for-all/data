"""Severity-score integration for the existing Profanity API (#422).

Calls the already-deployed Profanity API for a help request and derives a
validated severity score (0-3) from its response. This module does not
classify content itself and does not touch a database; routing by score lives
in ``routing.py``.

A request that could not be scored is never reported as score 0: every failure
returns HTTP 503 with a null ``severity_score``.

Scoring rules (see ``derive_severity``):
    * Classification flags, strictly boolean:
        contains_profanity                                       -> 1
        contains_depressive_content / contains_suicidal_content  -> 2
        contains_threatening_content                             -> 3
      Without a numeric score all four are required: a missing or
      non-boolean flag is an error, never "false".
    * A numeric score (field ``PROFANITY_SCORE_FIELD``, default
      ``severity_score``) must be an int 0-3 when present.
    * If both are present the higher value wins, so a disagreement or a
      partial set of flags can only escalate the score. If several categories
      match, the highest score is used (provisional, pending maintainer
      confirmation).
    * Neither present, or a degraded/error payload (``status_code`` outside
      2xx, ``Error``/``error``/``error_code`` fields, or a
      ``classification_status`` other than "complete") -> error.

Configuration (environment variables):
    PROFANITY_API_URL      required: full HTTPS URL of the Profanity API
    PROFANITY_SCORE_FIELD  optional: response field with the 0-3 score; a
                           dotted path ("a.b") reads a nested field
                           (default "severity_score")
    PROFANITY_API_TIMEOUT  optional: seconds (default 10)

Upstream request:  POST {"subject": ..., "description": ...}  (JSON). The
caller's Authorization header, if present, is forwarded unchanged.

Event:    {"subject": "...", "description": "..."}  (optionally under "body")
Response: API Gateway proxy format (statusCode / headers / JSON string body).
"""

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_SCORE_FIELD = "severity_score"
VALID_SCORES = (0, 1, 2, 3)

# Classification flag -> (severity score, category name).
FLAG_SEVERITY = {
    "contains_profanity": (1, "profanity"),
    "contains_depressive_content": (2, "depressive_or_suicidal"),
    "contains_suicidal_content": (2, "depressive_or_suicidal"),
    "contains_threatening_content": (3, "threatening"),
}

# Keys whose presence marks an upstream payload as an error/degraded result.
ERROR_KEYS = ("Error", "error", "error_code", "errorMessage")

ERROR_INVALID_INPUT = "invalid_input"
ERROR_NOT_CONFIGURED = "profanity_api_not_configured"
ERROR_UNAVAILABLE = "profanity_api_unavailable"
ERROR_INVALID_RESPONSE = "profanity_api_response_invalid"

ERROR_MESSAGES = {
    ERROR_INVALID_INPUT: "subject and description must be strings and at least one must not be blank.",
    ERROR_NOT_CONFIGURED: "The Profanity API integration is not configured; the request was not scored.",
    ERROR_UNAVAILABLE: "The Profanity API is unavailable; the request was not scored.",
    ERROR_INVALID_RESPONSE: "The Profanity API returned an unusable response; the request was not scored.",
}


class SeverityError(Exception):
    """The request was not scored. Carries a safe, fixed error code."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the Authorization header is never sent to another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# A redirect now surfaces as an HTTPError (unavailable) instead of being followed.
_OPENER = urllib.request.build_opener(_NoRedirectHandler())


def _read_config():
    url = os.environ.get("PROFANITY_API_URL", "").strip()
    field = os.environ.get("PROFANITY_SCORE_FIELD", "").strip() or DEFAULT_SCORE_FIELD

    if not url.startswith("https://"):
        raise SeverityError(ERROR_NOT_CONFIGURED)

    try:
        timeout = float(os.environ.get("PROFANITY_API_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        raise SeverityError(ERROR_NOT_CONFIGURED) from None
    if timeout <= 0:
        raise SeverityError(ERROR_NOT_CONFIGURED)

    return url, field, timeout


def call_profanity_api(url, subject, description, timeout, authorization=None, opener=None):
    """POST the help request to the Profanity API and return its JSON object."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if authorization:
        headers["Authorization"] = authorization

    request = urllib.request.Request(
        url,
        data=json.dumps({"subject": subject, "description": description}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    send = opener or _OPENER.open

    try:
        with send(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            raw = response.read()
    except Exception as exc:
        # Only the exception type is logged: messages may contain URLs or tokens.
        logger.error("Profanity API request failed: %s", type(exc).__name__)
        raise SeverityError(ERROR_UNAVAILABLE) from None

    if type(status) is not int or not 200 <= status < 300:
        raise SeverityError(ERROR_UNAVAILABLE)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, AttributeError):
        raise SeverityError(ERROR_INVALID_RESPONSE) from None

    if not isinstance(payload, dict):
        raise SeverityError(ERROR_INVALID_RESPONSE)

    return payload


def _reject_degraded_payload(payload):
    """Refuse payloads that are themselves error or degraded results.

    The existing filter answers HTTP 200 with ``status_code: 500`` and an
    ``Error`` field when its model call fails, while its flags read false.
    """
    status = payload.get("classification_status")
    if status is not None and status != "complete":
        raise SeverityError(ERROR_INVALID_RESPONSE)

    if "status_code" in payload:
        code = payload["status_code"]
        if type(code) is not int or not 200 <= code < 300:
            raise SeverityError(ERROR_INVALID_RESPONSE)

    for key in ERROR_KEYS:
        if payload.get(key) not in (None, "", False):
            raise SeverityError(ERROR_INVALID_RESPONSE)


def _read_numeric_score(payload, field):
    """Return the int score at ``field`` (dotted path), or None if absent."""
    value = payload
    for key in field.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]

    # Present but not a genuine int 0-3 (null, bool, float, string...) is an
    # error, not "absent".
    if type(value) is not int or value not in VALID_SCORES:
        raise SeverityError(ERROR_INVALID_RESPONSE)

    return value


def _read_flags(payload, require_all):
    """Return {flag: bool} for the flags supplied, or None if there are none.

    Every flag that is present must be a real boolean. With ``require_all`` a
    missing flag is an error: it must never be read as "false" when the flags
    are the only basis for a score.
    """
    present = [flag for flag in FLAG_SEVERITY if flag in payload]
    if not present:
        return None

    if require_all and len(present) != len(FLAG_SEVERITY):
        raise SeverityError(ERROR_INVALID_RESPONSE)

    flags = {}
    for flag in present:
        if type(payload[flag]) is not bool:
            raise SeverityError(ERROR_INVALID_RESPONSE)
        flags[flag] = payload[flag]

    return flags


def derive_severity(payload, score_field=DEFAULT_SCORE_FIELD):
    """Derive a validated severity from an upstream payload, or raise SeverityError.

    Returns {"severity_score": int, "flagged_categories": list | None,
    "source": "flags" | "score" | "flags+score"}.
    """
    _reject_degraded_payload(payload)

    score = _read_numeric_score(payload, score_field)
    # With a valid score, partial flags can only escalate it; without one the
    # flags must be complete because they are the only basis for the score.
    flags = _read_flags(payload, require_all=score is None)

    if score is None and flags is None:
        raise SeverityError(ERROR_INVALID_RESPONSE)

    categories = None
    flag_score = None
    if flags is not None:
        categories = []
        for flag, is_set in flags.items():
            if is_set:
                severity, category = FLAG_SEVERITY[flag]
                item = {"score": severity, "category": category}
                if item not in categories:
                    categories.append(item)
        categories.sort(key=lambda item: item["score"])
        flag_score = max((item["score"] for item in categories), default=0)

    if score is not None and flags is not None:
        source = "flags+score"
    else:
        source = "score" if score is not None else "flags"

    return {
        "severity_score": max(v for v in (score, flag_score) if v is not None),
        "flagged_categories": categories,
        "source": source,
    }


def get_severity(subject, description, authorization=None, opener=None):
    """Score a help request. Returns a complete result or raises SeverityError."""
    if not isinstance(subject, str) or not isinstance(description, str):
        raise SeverityError(ERROR_INVALID_INPUT)
    if not (subject + description).strip():
        raise SeverityError(ERROR_INVALID_INPUT)

    url, field, timeout = _read_config()
    payload = call_profanity_api(
        url, subject, description, timeout, authorization=authorization, opener=opener
    )
    derived = derive_severity(payload, field)

    return {
        "classification_status": "complete",
        "severity_score": derived["severity_score"],
        "flagged_categories": derived["flagged_categories"],
    }


def error_status(error):
    """HTTP status for a SeverityError: 400 for bad input, 503 when not scored."""
    return 400 if error.code == ERROR_INVALID_INPUT else 503


def error_body(error):
    """Response body for a SeverityError. ``severity_score`` is always null."""
    invalid = error.code == ERROR_INVALID_INPUT
    return {
        "classification_status": "not_classified" if invalid else "degraded",
        "severity_score": None,
        "flagged_categories": None,
        "error_code": error.code,
        "error": ERROR_MESSAGES[error.code],
    }


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*"
        },
        "body": json.dumps(body)
    }


def _parse_event(event):
    body = event.get("body", event) if isinstance(event, dict) else None

    if isinstance(body, (str, bytes)):
        try:
            body = json.loads(body)
        except ValueError:
            raise SeverityError(ERROR_INVALID_INPUT) from None

    if not isinstance(body, dict):
        raise SeverityError(ERROR_INVALID_INPUT)

    return body.get("subject"), body.get("description")


def _authorization_header(event):
    headers = event.get("headers") if isinstance(event, dict) else None
    if not isinstance(headers, dict):
        return None
    for name, value in headers.items():
        if isinstance(name, str) and name.lower() == "authorization" and isinstance(value, str):
            return value
    return None


def lambda_handler(event, context):
    try:
        subject, description = _parse_event(event)
        result = get_severity(
            subject, description, authorization=_authorization_header(event)
        )
        return build_response(200, result)

    except SeverityError as error:
        return build_response(error_status(error), error_body(error))
