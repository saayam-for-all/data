"""Profanity severity scoring and routing logic for the Help Request workflow (#422).

Background
----------
A Profanity API has already been built elsewhere (it is *not* implemented by
this module). When a Help Request is submitted, its content must be scored by
that API before the request is allowed to enter active matching. The API
returns a severity classification:

    0 = Good Request                (clean content)
    1 = Foul Language
    2 = Depressive or Suicidal Content
    3 = Threatening Content

This module is responsible only for:
    1. Calling the external Profanity API with a Help Request's subject and
       description (``call_profanity_api``).
    2. Normalizing whatever response shape it returns into a single severity
       score (``parse_profanity_response``).
    3. Deciding where a Help Request should be routed based on that score
       (``get_routing_decision``).

Assumptions (the live API contract is not documented anywhere in this repo)
-----------------------------------------------------------------------
- The request payload sent to the API combines ``subject`` and
  ``description`` into a single ``content`` string, while also sending the
  two fields individually, since the real request shape is unconfirmed.
- The response may come back in either of two reasonable shapes, so both are
  supported defensively:
    A. A single score under one of several equivalent field names
       (``severity_score``, ``severityScore``, ``classification_score``,
       ``classificationScore``, ``score``).
    B. A multi-category breakdown under ``severity_scores``, a list of
       ``{"score": int, "category": str, "flagged": bool}`` entries, where
       the effective severity is the highest *flagged* score greater than 0.
    - Either shape above may also be nested one level down under a
      ``"result"`` key (e.g. ``{"result": {"severity_score": 2}}``), since
      some APIs wrap their actual payload that way.
- Routing destinations (``active_matching`` for score 0, ``fraud_requests``
  for scores 1-3) are per explicit instruction for this task. This has not
  been verified against a live, deployed API or an approved team decision,
  and should be confirmed before this module is wired into a real route.

This module is intentionally free of Flask and database dependencies so it
stays simple to unit test in isolation.
"""

import os
from typing import Any, Dict, List, Optional

import requests

# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------

SEVERITY_LABELS: Dict[int, str] = {
    0: "Good Request",
    1: "Foul Language",
    2: "Depressive or Suicidal Content",
    3: "Threatening Content",
}

VALID_SEVERITY_SCORES = frozenset(SEVERITY_LABELS)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PROFANITY_API_URL_ENV = "PROFANITY_API_URL"
PROFANITY_API_KEY_ENV = "PROFANITY_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 5

# Field names the real API's single-score response might use. Order matters
# only in that the first match wins if a response somehow contained more
# than one (which should not happen in practice).
_SCORE_FIELD_NAMES = (
    "severity_score",
    "severityScore",
    "classification_score",
    "classificationScore",
    "score",
)


class ProfanityAPIError(RuntimeError):
    """Raised when the Profanity API cannot be reached or returns an unusable response.

    Messages on this exception are deliberately generic: they never include
    the configured URL, API key, or the raw underlying network/HTTP error
    text, so nothing sensitive can leak through logs or an HTTP response body.
    """


def _is_valid_score(value: Any) -> bool:
    """Return True only for a genuine ``int`` in ``{0, 1, 2, 3}``.

    ``bool`` is a subclass of ``int`` in Python (``True == 1``), so booleans
    are explicitly rejected rather than silently accepted as scores.
    """
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value in VALID_SEVERITY_SCORES
    )


# ---------------------------------------------------------------------------
# 1. Calling the external Profanity API
# ---------------------------------------------------------------------------


def call_profanity_api(subject: str, description: str) -> Dict[str, Any]:
    """Submit a Help Request's subject and description to the Profanity API.

    Args:
        subject: The Help Request's subject/title. Must be a non-empty string.
        description: The Help Request's description. Must be a non-empty string.

    Returns:
        The API's decoded JSON response body as a ``dict``. The shape of this
        dict is not validated here; use ``parse_profanity_response`` for that.

    Raises:
        ValueError: ``subject`` or ``description`` is missing/empty/not a string.
        ProfanityAPIError: The API URL is not configured, or the request
            failed (network error, timeout, non-2xx status, or a response
            body that isn't valid JSON).
    """
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("subject must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description must be a non-empty string")

    api_url = os.environ.get(PROFANITY_API_URL_ENV, "").strip()
    if not api_url:
        raise ProfanityAPIError(f"{PROFANITY_API_URL_ENV} is not configured")

    subject = subject.strip()
    description = description.strip()
    content = f"{subject} {description}".strip()

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    api_key = os.environ.get(PROFANITY_API_KEY_ENV, "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.post(
            api_url,
            json={"subject": subject, "description": description, "content": content},
            headers=headers,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        # Deliberately generic: do not surface exc's own message, since it
        # can include the request URL and (for some adapters) header data.
        raise ProfanityAPIError(
            "Profanity API request failed (network error, timeout, or non-2xx status)"
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise ProfanityAPIError("Profanity API returned a response that was not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ProfanityAPIError("Profanity API response must be a JSON object")

    return payload


# ---------------------------------------------------------------------------
# 2. Normalizing the API response into a single severity score
# ---------------------------------------------------------------------------


def parse_profanity_response(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a Profanity API response into a single severity decision.

    Supports two response shapes (see module docstring for why both are
    supported):

    A. Single score, under any of ``severity_score``/``severityScore``/
       ``classification_score``/``classificationScore``/``score``::

           {"severity_score": 2}

    B. Multi-category breakdown::

           {
               "severity_scores": [
                   {"score": 1, "category": "Foul Language", "flagged": True},
                   {"score": 2, "category": "Depressive or Suicidal Content", "flagged": False},
               ]
           }

       For this shape, the effective score is the *highest* entry with
       ``flagged is True`` and ``score > 0``. If nothing is flagged, the
       effective score is 0.

    Either shape may also be nested one level down under a ``"result"``
    key, e.g. ``{"result": {"severity_score": 2}}``.

    Args:
        payload: The decoded JSON body returned by ``call_profanity_api``.

    Returns:
        A normalized dict::

            {
                "severity_score": <int 0-3>,
                "is_flagged": <bool>,
                "flagged_categories": [{"score": <int>, "category": <str>}, ...],
            }

    Raises:
        ProfanityAPIError: ``payload`` is not a dict, contains no recognizable
            score field, or contains a malformed/invalid score, category, or
            ``flagged`` value.
    """
    if not isinstance(payload, dict):
        raise ProfanityAPIError("Profanity API response must be a JSON object")

    result = _parse_known_shape(payload)
    if result is not None:
        return result

    # Some APIs nest the actual classification one level down, e.g.
    # {"result": {"severity_score": 2}}. If nothing was found at the top
    # level, look inside a "result" object exactly one level deep before
    # giving up. This intentionally does NOT recurse further: an API
    # response is never expected to nest more than one level, and recursing
    # on arbitrary/adversarial input (e.g. "result" nested thousands of
    # levels deep) would raise an uncaught RecursionError instead of the
    # clean ProfanityAPIError callers already handle.
    nested = payload.get("result")
    if isinstance(nested, dict):
        result = _parse_known_shape(nested)
        if result is not None:
            return result

    raise ProfanityAPIError("Profanity API response did not include a recognizable severity score")


def _parse_known_shape(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Try the two known (non-nested) response shapes against ``payload``.

    Returns the normalized result if ``payload`` contains a recognizable
    ``severity_scores`` list or one of the single-score field names;
    otherwise returns ``None`` (not an error - the caller decides what to do
    when nothing is recognized, e.g. trying one level of ``"result"``
    nesting, or giving up).
    """
    if "severity_scores" in payload:
        return _parse_multi_category_response(payload["severity_scores"])

    for field in _SCORE_FIELD_NAMES:
        if field in payload:
            return _parse_single_score_response(payload[field])

    return None


def _parse_single_score_response(candidate: Any) -> Dict[str, Any]:
    """Build the normalized result for the single-score response format."""
    if not _is_valid_score(candidate):
        raise ProfanityAPIError(f"Severity score must be an integer 0-3, got {candidate!r}")

    score = candidate
    is_flagged = score > 0
    flagged_categories: List[Dict[str, Any]] = []
    if is_flagged:
        flagged_categories.append({"score": score, "category": SEVERITY_LABELS[score]})

    return {
        "severity_score": score,
        "is_flagged": is_flagged,
        "flagged_categories": flagged_categories,
    }


def _parse_multi_category_response(entries: Any) -> Dict[str, Any]:
    """Build the normalized result for the multi-category response format."""
    if not isinstance(entries, list) or not entries:
        raise ProfanityAPIError("severity_scores must be a non-empty list")

    flagged_categories: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ProfanityAPIError("Each severity_scores entry must be a JSON object")

        score = entry.get("score")
        category = entry.get("category")
        flagged = entry.get("flagged")

        if not _is_valid_score(score):
            raise ProfanityAPIError(f"severity_scores entry has an invalid 'score': {score!r}")
        if not isinstance(category, str) or not category.strip():
            raise ProfanityAPIError("severity_scores entry is missing a valid 'category'")
        if not isinstance(flagged, bool):
            raise ProfanityAPIError(f"severity_scores entry has a non-boolean 'flagged': {flagged!r}")

        if flagged and score > 0:
            flagged_categories.append({"score": score, "category": category.strip()})

    highest_flagged_score = max((item["score"] for item in flagged_categories), default=0)

    return {
        "severity_score": highest_flagged_score,
        "is_flagged": bool(flagged_categories),
        "flagged_categories": flagged_categories,
    }


# ---------------------------------------------------------------------------
# 3. Routing decision
# ---------------------------------------------------------------------------


def get_routing_decision(score: int) -> Dict[str, Any]:
    """Decide where a Help Request should be routed based on its severity score.

    Args:
        score: A severity score of 0, 1, 2, or 3.

    Returns:
        A dict::

            {
                "severity_score": <int 0-3>,
                "destination": "active_matching" | "fraud_requests",
                "reason": <str, the SEVERITY_LABELS label for this score>,
            }

        Score 0 routes to ``"active_matching"``; scores 1-3 route to
        ``"fraud_requests"``.

    Raises:
        ValueError: ``score`` is not an integer in ``{0, 1, 2, 3}``.
    """
    if not _is_valid_score(score):
        raise ValueError(f"Severity score must be an integer 0-3, got {score!r}")

    destination = "active_matching" if score == 0 else "fraud_requests"

    return {
        "severity_score": score,
        "destination": destination,
        "reason": SEVERITY_LABELS[score],
    }
