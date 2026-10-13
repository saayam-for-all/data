"""Client for the Profanity API that screens help requests (issue #422).

The Profanity API classifies the subject and description of a help request.
This module calls it and reduces the response to a single severity score:

    0  Good Request              clean, no harmful content
    1  Foul Language             offensive or foul language
    2  Depressive or Suicidal    depressive or suicidal language
    3  Threatening               threatening language

The labels mirror the `sentiment_codes` lookup table from the database team.

The response may carry, in order of preference:
  - the score directly (`severity_score` or `score`),
  - a `severity_scores` list of {"score", "category", "flagged"} entries, as
    returned by the inappropriate content filter since PR #467, or
  - only the filter's `contains_*` flags.
In the last two cases the most severe flagged category sets the score.

A response that reports an internal error (the filter returns HTTP 200 with
`"status_code": 500` and an `"Error"` message when its LLM check fails) is
treated as a failure, because its depressive/threatening checks did not run.

The API URL and key come from environment variables (see .env.example).
"""
import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

PROFANITY_API_URL_ENV = "PROFANITY_API_URL"
PROFANITY_API_KEY_ENV = "PROFANITY_API_KEY"
PROFANITY_API_TIMEOUT_ENV = "PROFANITY_API_TIMEOUT_SECONDS"
DEFAULT_TIMEOUT_SECONDS = 5.0

GOOD_REQUEST = 0
FOUL_LANGUAGE = 1
DEPRESSIVE_OR_SUICIDAL = 2
THREATENING = 3

SEVERITY_LABELS: dict[int, str] = {
    GOOD_REQUEST: "Good Request",
    FOUL_LANGUAGE: "Foul Language",
    DEPRESSIVE_OR_SUICIDAL: "Depressive or Suicidal",
    THREATENING: "Threatening",
}

# Response keys that may hold the score directly, checked in this order.
SCORE_KEYS = ("severity_score", "score")

# Flags returned by the inappropriate content filter, most severe first.
FLAG_SCORES = (
    ("contains_threatening_content", THREATENING),
    ("contains_suicidal_content", DEPRESSIVE_OR_SUICIDAL),
    ("contains_depressive_content", DEPRESSIVE_OR_SUICIDAL),
    ("contains_profanity", FOUL_LANGUAGE),
)

# (url, json_payload, headers, timeout) -> (status_code, response_text)
HttpPost = Callable[
    [str, dict[str, Any], dict[str, str], float], tuple[int, str]]


class ProfanityApiError(RuntimeError):
    """The Profanity API was unreachable or returned an unusable response."""


class InvalidSeverityScoreError(ValueError):
    """The Profanity API response had no valid 0-3 severity score."""


def validate_severity_score(value: Any) -> int:
    """Return `value` as an int if it is a valid severity score (0-3).

    Whole-number floats such as 2.0 are accepted; booleans, strings and
    out-of-range numbers raise InvalidSeverityScoreError.
    """
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if (isinstance(value, bool) or not isinstance(value, int)
            or value not in SEVERITY_LABELS):
        raise InvalidSeverityScoreError(f"Invalid severity score: {value!r}")
    return value


def unwrap_response_body(payload: Any) -> dict[str, Any]:
    """Return the JSON object that holds the classification.

    Handles a plain JSON object, a JSON string, or a Lambda proxy response
    (`{"statusCode": ..., "body": ...}`) whose body is either of those.
    """
    payload = _parse_json_object(payload)
    if "body" in payload:
        status_code = payload.get("statusCode", 200)
        if status_code != 200:
            raise ProfanityApiError(
                f"Profanity API returned status {status_code}")
        payload = _parse_json_object(payload["body"])

    embedded_status = payload.get("status_code", 200)
    if (embedded_status != 200 or payload.get("Error")
            or payload.get("error")):
        raise ProfanityApiError(
            "Profanity API reported an internal error "
            f"(status {embedded_status})")
    return payload


def _parse_json_object(value: Any) -> dict[str, Any]:
    """Return `value` as a dict, parsing it first if it is a JSON string."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as e:
            raise ProfanityApiError(
                "Profanity API returned invalid JSON") from e
    if not isinstance(value, dict):
        raise ProfanityApiError("Profanity API response is not a JSON object")
    return value


def extract_severity_score(payload: Any) -> int:
    """Reduce a Profanity API response to a single 0-3 severity score."""
    body = unwrap_response_body(payload)

    for key in SCORE_KEYS:
        if key in body:
            return validate_severity_score(body[key])

    if "severity_scores" in body:
        return _score_from_severity_list(body["severity_scores"])

    if any(flag in body for flag, _ in FLAG_SCORES):
        for flag, score in FLAG_SCORES:
            if body.get(flag) is True:
                return score
        return GOOD_REQUEST

    raise InvalidSeverityScoreError(
        "Response has no severity score or content flags")


def _score_from_severity_list(entries: Any) -> int:
    """Return the highest flagged score in a `severity_scores` list."""
    if not isinstance(entries, list) or not entries:
        raise InvalidSeverityScoreError(
            "severity_scores must be a non-empty list")
    flagged_scores = []
    for entry in entries:
        if (not isinstance(entry, dict)
                or not isinstance(entry.get("flagged"), bool)):
            raise InvalidSeverityScoreError(
                f"Malformed severity_scores entry: {entry!r}")
        score = validate_severity_score(entry.get("score"))
        if entry["flagged"]:
            flagged_scores.append(score)
    return max(flagged_scores, default=GOOD_REQUEST)


def _urllib_post(url: str, payload: dict[str, Any], headers: dict[str, str],
                 timeout: float) -> tuple[int, str]:
    """POST `payload` as JSON and return (status code, response text)."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


class ProfanityClient:
    """Calls the Profanity API and returns a validated severity score.

    `http_post` can be replaced in tests so no network call is made.
    """

    def __init__(self, api_url: str, api_key: Optional[str] = None,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 http_post: Optional[HttpPost] = None) -> None:
        """Create a client for the API at `api_url`."""
        if not api_url:
            raise ValueError(f"{PROFANITY_API_URL_ENV} is not set")
        self.api_url = api_url
        self._api_key = api_key
        self.timeout = timeout
        self._http_post = http_post or _urllib_post

    @classmethod
    def from_env(cls) -> "ProfanityClient":
        """Create a client from the PROFANITY_API_* environment variables."""
        timeout_raw = os.getenv(PROFANITY_API_TIMEOUT_ENV)
        try:
            timeout = (float(timeout_raw) if timeout_raw
                       else DEFAULT_TIMEOUT_SECONDS)
        except ValueError as e:
            raise ValueError(
                f"{PROFANITY_API_TIMEOUT_ENV} must be a number") from e
        return cls(
            api_url=os.getenv(PROFANITY_API_URL_ENV, ""),
            api_key=os.getenv(PROFANITY_API_KEY_ENV) or None,
            timeout=timeout,
        )

    def get_severity_score(self, subject: str, description: str) -> int:
        """Classify a help request's text and return its 0-3 severity score.

        Raises ProfanityApiError if the API is unreachable or errors, and
        InvalidSeverityScoreError if the response has no valid score.
        """
        headers = {"x-api-key": self._api_key} if self._api_key else {}
        payload = {"subject": subject, "description": description}
        try:
            status_code, response_text = self._http_post(
                self.api_url, payload, headers, self.timeout)
        except OSError as e:  # URLError, timeouts and connection errors
            raise ProfanityApiError(
                f"Profanity API request failed: {e.__class__.__name__}") from e

        if status_code != 200:
            raise ProfanityApiError(
                f"Profanity API returned HTTP {status_code}")
        return extract_severity_score(response_text)
