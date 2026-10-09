"""Profanity severity scoring and routing for the Help Request workflow (#422).

The profanity API itself is a separate, already-built service (not part of this
change) that classifies a piece of text and returns a severity score of 0-3.
This module calls that API, interprets the score and decides where the help
request belongs:

    score 0 -> clean ("Good Request"): proceeds into the normal active-matching
               workflow; nothing written here.
    score 1-3 -> flagged: the request must not enter active matching. A row is
               written to fraud_requests instead, with `reason` set to the
               matching label below, so the flagged request is tracked and the
               reason is visible later.

The four codes and their labels mirror the `sentiment_codes` lookup table
(saayam-for-all/database wiki, "Changes to the Database" page):

    0  Good Request              clean, no harmful or negative content
    1  Foul Language             offensive or foul language
    2  Depressive or Suicidal    depressive or suicidal language
    3  Threatening               threatening language or references to weapons
"""

import os
from typing import Any, Callable, Optional

PROFANITY_API_URL_ENV = "PROFANITY_API_URL"
PROFANITY_API_KEY_ENV = "PROFANITY_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 5

SENTIMENT_LABELS = {
    0: "Good Request",
    1: "Foul Language",
    2: "Depressive or Suicidal",
    3: "Threatening",
}

# Keys the help-request payload might carry its text under. Subject-like fields
# come first so a combined "Subject Description" string reads in a natural order.
TEXT_FIELDS = ("req_subj", "subject", "title", "req_desc", "description",
               "request_description", "content", "request_content")


class ProfanityApiError(RuntimeError):
    """The profanity API could not be reached or did not return usable JSON."""


class InvalidSeverityScoreError(ValueError):
    """The profanity API's response did not contain a severity score of 0-3."""


def extract_help_request_text(payload: dict[str, Any]) -> str:
    """Pull the text to classify out of a help-request-shaped payload.

    Combines req_desc and req_subj (description + subject) when both are
    present, since either alone could carry profanity the other misses.
    """
    parts = [str(payload[key]).strip() for key in TEXT_FIELDS
             if payload.get(key) not in (None, "")]
    text = " ".join(dict.fromkeys(parts))  # de-dupe while keeping first-seen order
    if not text:
        raise ValueError("Help request content is required for profanity scoring")
    return text


def call_profanity_api(text: str, api_url: Optional[str] = None,
                       timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    """POST `text` to the configured profanity API and return its JSON body."""
    import requests  # imported lazily so unit tests never need a real network stack

    resolved_url = api_url or os.environ.get(PROFANITY_API_URL_ENV)
    if not resolved_url:
        raise ProfanityApiError(f"{PROFANITY_API_URL_ENV} must be configured")

    headers = {}
    api_key = os.environ.get(PROFANITY_API_KEY_ENV)
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.post(resolved_url, json={"text": text}, headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise ProfanityApiError(f"Profanity API request failed: {exc}") from exc
    except ValueError as exc:
        raise ProfanityApiError("Profanity API returned invalid JSON") from exc

    if not isinstance(payload, dict):
        raise ProfanityApiError("Profanity API response must be a JSON object")
    return payload


def extract_severity_score(response_payload: dict[str, Any]) -> int:
    """Pull a 0-3 severity score out of a profanity API JSON response."""
    candidate = _find_score(response_payload)
    if candidate is None:
        raise InvalidSeverityScoreError("Profanity API response did not include a severity score")
    # bool is a subtype of int in Python (True == 1), and a non-whole float like 1.5
    # would otherwise silently truncate to a "valid" score via int() - reject both
    # rather than guess at what the API meant.
    if isinstance(candidate, bool):
        raise InvalidSeverityScoreError(f"Severity score must be an integer, got {candidate!r}")
    if isinstance(candidate, float) and not candidate.is_integer():
        raise InvalidSeverityScoreError(f"Severity score must be an integer, got {candidate!r}")
    try:
        score = int(candidate)
    except (TypeError, ValueError) as exc:
        raise InvalidSeverityScoreError(f"Severity score must be an integer, got {candidate!r}") from exc
    if score not in SENTIMENT_LABELS:
        raise InvalidSeverityScoreError(f"Severity score must be 0, 1, 2 or 3, got {score}")
    return score


def _find_score(payload: dict[str, Any]) -> Any:
    for key in ("severity_score", "severityScore", "classification_score", "classificationScore", "score"):
        if key in payload:
            return payload[key]
    for key in ("data", "result", "classification"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = _find_score(nested)
            if found is not None:
                return found
    return None


def evaluate_help_request(payload: dict[str, Any],
                          profanity_client: Optional[Callable[[str], dict[str, Any]]] = None) -> dict[str, Any]:
    """Score a help request's text and decide whether it's flagged.

    `profanity_client` defaults to the real `call_profanity_api`; tests pass a
    stand-in so no network call is made. Returns {"severity_score", "reason",
    "is_flagged"} - never writes to the database itself (the Flask route does
    that, since this function has no DB dependency and stays easy to unit test).
    """
    text = extract_help_request_text(payload)
    client = profanity_client or call_profanity_api
    score = extract_severity_score(client(text))
    return {
        "severity_score": score,
        "reason": SENTIMENT_LABELS[score],
        "is_flagged": score != 0,
    }
