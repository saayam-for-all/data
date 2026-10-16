import json
import os
import urllib.request

MIN_SCORE = 0
MAX_SCORE = 3
MAX_RESPONSE_BYTES = 1_000_000


class SeverityCheckError(RuntimeError):
    """
    Callers must treat this as "not checked", never as a clean request.
    """

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so the request cannot be sent somewhere unexpected."""

    def redirect_request(self, *args, **kwargs):
        return None


def _checked_score(value):
    # type() rather than isinstance(): True/False must not pass as 1/0
    if type(value) is not int or not MIN_SCORE <= value <= MAX_SCORE:
        raise SeverityCheckError(f"Invalid severity score: {value!r}")
    return value


def extract_score(payload):
    """Pulls a single 0-3 score out of the API's JSON reply.

    Accepts "severity_score" (one int) and/or "severity_scores" (a list of
    ints, one per matched category). When only the list is given, the highest
    score is used. If both are given they must agree. A reply wrapped in a
    Lambda-style {"statusCode": ..., "body": ...} envelope is unwrapped once.
    """
    if (
        isinstance(payload, dict)
        and "severity_score" not in payload
        and "severity_scores" not in payload
        and "body" in payload
    ):
        status = payload.get("statusCode")
        if status is not None and (type(status) is not int or not 200 <= status < 300):
            raise SeverityCheckError(f"Profanity API reported status {status!r}")
        body = payload["body"]
        try:
            payload = json.loads(body) if isinstance(body, str) else body
        except ValueError as error:
            raise SeverityCheckError("Profanity API body is not valid JSON") from error

    if not isinstance(payload, dict):
        raise SeverityCheckError("Profanity API reply is not a JSON object")
    if payload.get("error"):
        raise SeverityCheckError("Profanity API reported an error")

    single = payload.get("severity_score")
    many = payload.get("severity_scores")
    if single is None and many is None:
        raise SeverityCheckError("Profanity API reply has no severity score")

    score = None
    if single is not None:
        score = _checked_score(single)
    if many is not None:
        if not isinstance(many, list) or not many:
            raise SeverityCheckError("severity_scores must be a non-empty list")
        highest = max(_checked_score(item) for item in many)
        if score is not None and score != highest:
            raise SeverityCheckError("severity_score and severity_scores disagree")
        score = highest

    return score


def get_severity_score(subject, description, *, timeout=10, url=None, api_key=None):
    """Sends a help request to the profanity API and returns its score (0-3).

    Raises ValueError for unusable input and SeverityCheckError for anything
    that goes wrong with the API call or its reply. It never falls back to 0.

    Configuration (arguments win over environment variables):
        PROFANITY_API_URL  - required, must be an https:// endpoint
        PROFANITY_API_KEY  - optional, sent as the x-api-key header
    """
    if not isinstance(subject, str) or not isinstance(description, str):
        raise ValueError("subject and description must be strings")
    if not (subject.strip() or description.strip()):
        raise ValueError("subject and description cannot both be empty")

    url = (url or os.environ.get("PROFANITY_API_URL", "")).strip()
    if not url.startswith("https://"):
        raise SeverityCheckError("PROFANITY_API_URL must be an https:// URL")

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = api_key or os.environ.get("PROFANITY_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    request = urllib.request.Request(
        url,
        data=json.dumps({"subject": subject, "description": description}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect)

    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES)
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as error:
        # OSError covers URLError/HTTPError (4xx, 5xx, redirects) and timeouts;
        # ValueError covers bad JSON and bad encoding.
        raise SeverityCheckError("Could not get a severity score from the profanity API") from error

    return extract_score(payload)


# ---- Routing ----

SCORE_LABELS = {
    0: "Normal request",
    1: "Profanity",
    2: "Depressive/Suicidal content",
    3: "Threatening content",
}

# Destinations a help request can be routed to
ACTIVE_MATCHING = "active_matching"
FRAUD_REQUESTS = "fraud_requests"

# Approved mapping: score 0 goes to active matching, scores 1-3 are recorded
# in proposed_saayam.fraud_requests.
FRAUD_SCORES = frozenset({1, 2, 3})


def route_help_request(user_id, score, request_datetime=None, *, session=None, fraud_model=None):
    """Routes a help request using its severity score.

    Scores 1-3 are recorded in the fraud_requests table
    with the score in the reason. Score 0 writes nothing here: the request
    goes on to active matching and the caller carries on with its workflow.

    Returns {"severity_score", "routed_to", ["fraud_request_id"]}, where
    routed_to is "active_matching" or "fraud_requests".
    Needs a Flask app context when the default session/model are used.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id must be a non-empty string")
    if type(score) is not int or score not in SCORE_LABELS:
        raise ValueError(f"score must be an integer from {MIN_SCORE} to {MAX_SCORE}")

    if score not in FRAUD_SCORES:
        return {"severity_score": score, "routed_to": ACTIVE_MATCHING}

    if session is None:
        from src.extensions import db
        session = db.session
    if fraud_model is None:
        from src.models.fraud_requests import FraudRequests as fraud_model

    fields = {
        "user_id": user_id,
        "reason": f"Profanity API severity score {score}: {SCORE_LABELS[score]}",
    }
    if request_datetime is not None:
        fields["request_datetime"] = request_datetime

    row = fraud_model(**fields)
    try:
        session.add(row)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return {
        "severity_score": score,
        "routed_to": FRAUD_REQUESTS,
        "fraud_request_id": row.fraud_request_id,
    }


def check_and_route(subject, description, user_id, request_datetime=None, **route_options):
    """Gets the severity score from the API, then routes the request.

    A SeverityCheckError propagates and nothing is written, so a request that
    could not be checked is never filed as clean or as flagged.
    """
    score = get_severity_score(subject, description)
    return route_help_request(user_id, score, request_datetime, **route_options)