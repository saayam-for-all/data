"""Profanity severity scoring and routing logic for the Help Request workflow (Issue #422).

Background
----------
The Help Request workflow is the entry point into Saayam For All's
request-to-volunteer matching process.
When a user submits a Help Request, the request must be evaluated before
it is allowed to enter the active matching workflow.
An external Profanity API analyzes the submitted Help Request content and returns a classification score:
    0 = Good Request                (clean content -> routes to active matching)
    1 = Foul Language               (offensive or foul language -> flagged, routes to fraud_requests)
    2 = Depressive or Suicidal Content (depressive or suicidal content -> flagged, routes to fraud_requests)
    3 = Threatening Content         (threatening language or weapons -> flagged, routes to fraud_requests)

Based on the returned score, the Help Request is routed:
- Score 0: routed to active matching (workflow: active_matching, table: proposed_saayam.request)
- Scores 1-3: routed to fraud_requests (workflow: fraud_requests, table: proposed_saayam.fraud_requests)
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

import requests

# ---------------------------------------------------------------------------
# Severity labels and constants
# ---------------------------------------------------------------------------

SEVERITY_LABELS: Dict[int, str] = {
    0: "Good Request",
    1: "Foul Language",
    2: "Depressive or Suicidal Content",
    3: "Threatening Content",
}

SEVERITY_REASONS = SEVERITY_LABELS

VALID_SEVERITY_SCORES = frozenset(SEVERITY_LABELS.keys())

PROFANITY_API_URL_ENV = "PROFANITY_API_URL"
PROFANITY_API_KEY_ENV = "PROFANITY_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 5

_SCORE_FIELD_NAMES = (
    "severity_score",
    "severityScore",
    "classification_score",
    "classificationScore",
    "score",
)

TEXT_FIELDS = (
    "subject",
    "req_subj",
    "title",
    "description",
    "req_desc",
    "request_description",
    "content",
    "request_content",
    "text",
)


class ProfanityApiError(RuntimeError):
    """Raised when the Profanity API cannot be reached or returns an unusable response."""


ProfanityAPIError = ProfanityApiError


class InvalidSeverityScoreError(ValueError):
    """Raised when a severity score is not an integer in {0, 1, 2, 3}."""


def _coerce_score(value: Any) -> int:
    """Validate and coerce a candidate score into an int in {0, 1, 2, 3}.

    Rejects booleans (e.g. True == 1), non-integral floats (e.g. 1.5),
    non-numeric types, and values outside {0, 1, 2, 3}.
    """
    if isinstance(value, bool):
        raise InvalidSeverityScoreError(f"Severity score cannot be boolean, got {value!r}")

    if isinstance(value, float):
        if not value.is_integer():
            raise InvalidSeverityScoreError(f"Severity score must be an integer, got float {value!r}")
        value = int(value)

    if isinstance(value, str):
        value_str = value.strip()
        if value_str in {"0", "1", "2", "3"}:
            return int(value_str)
        raise InvalidSeverityScoreError(f"Severity score must be an integer 0-3, got {value!r}")

    if not isinstance(value, int):
        raise InvalidSeverityScoreError(f"Severity score must be an integer 0-3, got {value!r}")

    if value not in VALID_SEVERITY_SCORES:
        raise InvalidSeverityScoreError(f"Severity score must be 0, 1, 2, or 3, got {value!r}")

    return value


def extract_help_request_text(payload: dict[str, Any]) -> str:
    """Extract and combine subject and description text from a Help Request payload.

    Args:
        payload: Dictionary containing request fields.

    Returns:
        Combined non-empty text to be evaluated.

    Raises:
        ValueError: If payload is not a dict or no non-empty text fields are found.
    """
    if not isinstance(payload, dict):
        raise ValueError("Help request payload must be a JSON object")

    parts: List[str] = []
    for field in TEXT_FIELDS:
        val = payload.get(field)
        if isinstance(val, str) and val.strip():
            clean = val.strip()
            if clean not in parts:
                parts.append(clean)

    combined = " ".join(parts).strip()
    if not combined:
        raise ValueError("Help request text (subject/description/content) is required")

    return combined


def call_profanity_api(
    subject_or_text: str,
    description: Optional[str] = None,
    *,
    subject: Optional[str] = None,
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Call the external Profanity API with the Help Request content.

    Supports both signatures:
    - call_profanity_api(subject, description)
    - call_profanity_api(text)

    Args:
        subject_or_text: Request subject or full combined text to evaluate.
        description: Optional request description.
        subject: Optional explicit subject override.
        api_url: Optional override for the Profanity API URL.
        api_key: Optional override for the API authentication key.
        timeout: Request timeout in seconds.

    Returns:
        Decoded JSON response dictionary from the API.

    Raises:
        ValueError: If text or subject is empty or not a string.
        ProfanityApiError: If URL is missing, request fails, or response is invalid JSON.
    """
    if not isinstance(subject_or_text, str) or not subject_or_text.strip():
        raise ValueError("Text/subject to classify must be a non-empty string")

    if subject is not None:
        eff_subject = subject.strip() if subject else None
        eff_desc = description.strip() if description else None
        text = subject_or_text.strip()
    elif description is not None:
        if not isinstance(description, str) or not description.strip():
            raise ValueError("description must be a non-empty string")
        eff_subject = subject_or_text.strip()
        eff_desc = description.strip()
        text = f"{eff_subject} {eff_desc}".strip()
    else:
        text = subject_or_text.strip()
        eff_subject = None
        eff_desc = None

    resolved_url = (api_url or os.environ.get(PROFANITY_API_URL_ENV, "")).strip()
    if not resolved_url:
        raise ProfanityApiError(f"{PROFANITY_API_URL_ENV} is not configured")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    resolved_key = (api_key or os.environ.get(PROFANITY_API_KEY_ENV, "")).strip()
    if resolved_key:
        headers["Authorization"] = f"Bearer {resolved_key}"

    body: dict[str, Any] = {
        "text": text,
        "content": text,
    }
    if eff_subject:
        body["subject"] = eff_subject
    if eff_desc:
        body["description"] = eff_desc

    try:
        response = requests.post(
            resolved_url,
            json=body,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ProfanityApiError(
            "Profanity API request failed (network error, timeout, or non-2xx status)"
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise ProfanityApiError("Profanity API returned invalid JSON response") from exc

    if not isinstance(data, dict):
        raise ProfanityApiError("Profanity API response must be a JSON object")

    return data


def parse_profanity_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a Profanity API response into a validated severity classification.

    Supports:
    1. Single score format:
       {"severity_score": 2} or {"score": 2}
    2. Multi-category breakdown format:
       {"severity_scores": [{"score": 1, "category": "Foul Language", "flagged": True}, ...]}
       (Effective score is the highest flagged score > 0; 0 if nothing flagged).
    3. Nested payload under "result", "data", or "classification":
       {"result": {"severity_score": 2}}

    Returns:
        dict with keys:
            severity_score: int in {0, 1, 2, 3}
            is_flagged: bool
            reason: str label
            flagged_categories: list of {"score": int, "category": str}

    Raises:
        ProfanityApiError: If response is malformed or missing score fields.
        InvalidSeverityScoreError: If score is invalid.
    """
    if not isinstance(payload, dict):
        raise ProfanityApiError("Profanity API response must be a JSON object")

    result = _parse_known_shape(payload)
    if result is not None:
        return result

    for wrapper in ("result", "data", "classification"):
        nested = payload.get(wrapper)
        if isinstance(nested, dict):
            result = _parse_known_shape(nested)
            if result is not None:
                return result

    raise ProfanityApiError("Profanity API response did not include a recognizable severity score")


def _parse_known_shape(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    if "severity_scores" in payload:
        return _parse_multi_category_response(payload["severity_scores"])

    for field in _SCORE_FIELD_NAMES:
        if field in payload:
            return _parse_single_score_response(payload[field])

    return None


def _parse_single_score_response(candidate: Any) -> dict[str, Any]:
    score = _coerce_score(candidate)
    is_flagged = score > 0
    flagged_categories: List[dict[str, Any]] = []
    if is_flagged:
        flagged_categories.append({
            "score": score,
            "category": SEVERITY_LABELS[score],
        })

    return {
        "severity_score": score,
        "is_flagged": is_flagged,
        "reason": SEVERITY_LABELS[score],
        "flagged_categories": flagged_categories,
    }


def _parse_multi_category_response(entries: Any) -> dict[str, Any]:
    if not isinstance(entries, list) or not entries:
        raise ProfanityApiError("severity_scores must be a non-empty list")

    flagged_categories: List[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ProfanityApiError("Each severity_scores entry must be a JSON object")

        score_raw = entry.get("score")
        category = entry.get("category")
        flagged = entry.get("flagged")

        score = _coerce_score(score_raw)
        if not isinstance(category, str) or not category.strip():
            raise ProfanityApiError("severity_scores entry is missing a valid 'category'")
        if not isinstance(flagged, bool):
            raise ProfanityApiError(f"severity_scores entry has a non-boolean 'flagged': {flagged!r}")

        if flagged and score > 0:
            flagged_categories.append({
                "score": score,
                "category": category.strip(),
            })

    highest_score = max((item["score"] for item in flagged_categories), default=0)

    return {
        "severity_score": highest_score,
        "is_flagged": bool(flagged_categories),
        "reason": SEVERITY_LABELS[highest_score],
        "flagged_categories": flagged_categories,
    }


def get_routing_decision(score: int) -> dict[str, Any]:
    """Determine the destination database table and workflow based on severity score.

    Args:
        score: Severity score (0, 1, 2, or 3).

    Returns:
        dict containing routing metadata:
            severity_score: int
            destination: "active_matching" | "fraud_requests"
            database_table: "proposed_saayam.request" | "proposed_saayam.fraud_requests"
            action: "accept_request" | "route_to_fraud_requests"
            allow_active_matching: bool
            reason: str label
            is_flagged: bool

    Raises:
        InvalidSeverityScoreError: If score is not an integer in {0, 1, 2, 3}.
    """
    valid_score = _coerce_score(score)

    if valid_score == 0:
        destination = "active_matching"
        database_table = "proposed_saayam.request"
        action = "accept_request"
        allow_active_matching = True
    else:
        destination = "fraud_requests"
        database_table = "proposed_saayam.fraud_requests"
        action = "route_to_fraud_requests"
        allow_active_matching = False

    return {
        "severity_score": valid_score,
        "destination": destination,
        "database_table": database_table,
        "action": action,
        "allow_active_matching": allow_active_matching,
        "reason": SEVERITY_LABELS[valid_score],
        "is_flagged": valid_score > 0,
    }


def evaluate_help_request(
    payload: dict[str, Any],
    api_client: Optional[Callable[[str], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Evaluate a Help Request and determine its severity score and routing.

    Args:
        payload: Request payload dictionary containing help request text fields.
        api_client: Optional function/mock to call instead of default HTTP API caller.

    Returns:
        Complete evaluation result dictionary.
    """
    text = extract_help_request_text(payload)
    subject = payload.get("subject") or payload.get("title") or payload.get("req_subj")
    description = payload.get("description") or payload.get("content") or payload.get("req_desc")

    if api_client is not None:
        api_response = api_client(text)
    else:
        api_response = call_profanity_api(
            subject_or_text=text,
            subject=str(subject) if subject else None,
            description=str(description) if description else None,
        )

    parsed = parse_profanity_response(api_response)
    score = parsed["severity_score"]
    routing = get_routing_decision(score)

    return {
        "is_flagged": parsed["is_flagged"],
        "severity_score": score,
        "reason": routing["reason"],
        "destination": routing["destination"],
        "database_table": routing["database_table"],
        "action": routing["action"],
        "allow_active_matching": routing["allow_active_matching"],
        "flagged_categories": parsed.get("flagged_categories", []),
    }
