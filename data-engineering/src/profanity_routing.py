"""Profanity severity integration for help request routing."""

import os
from dataclasses import asdict, dataclass
from typing import Any, Callable


PROFANITY_API_URL_ENV = "PROFANITY_API_URL"
PROFANITY_API_KEY_ENV = "PROFANITY_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 5


class ProfanityApiError(RuntimeError):
    """Raised when the profanity API cannot return a usable response."""


class InvalidProfanityScoreError(ValueError):
    """Raised when a profanity API response does not contain score 0, 1, 2, or 3."""


@dataclass(frozen=True)
class ProfanityRoute:
    """Routing metadata for a help request profanity severity score."""

    severity_score: int
    action: str
    workflow: str
    database_table: str
    allow_active_matching: bool


ROUTES_BY_SCORE = {
    0: ProfanityRoute(
        severity_score=0,
        action="accept_request",
        workflow="active_matching",
        database_table="proposed_saayam.request",
        allow_active_matching=True,
    ),
    1: ProfanityRoute(
        severity_score=1,
        action="send_to_initial_review",
        workflow="content_review",
        database_table="proposed_saayam.request_review_queue",
        allow_active_matching=False,
    ),
    2: ProfanityRoute(
        severity_score=2,
        action="send_to_moderation",
        workflow="moderation_review",
        database_table="proposed_saayam.flagged_requests",
        allow_active_matching=False,
    ),
    3: ProfanityRoute(
        severity_score=3,
        action="reject_request",
        workflow="blocked_request",
        database_table="proposed_saayam.rejected_requests",
        allow_active_matching=False,
    ),
}


def build_help_request_text(payload: dict[str, Any]) -> str:
    """Combine the help request text fields used by the profanity API."""
    text_fields = (
        payload.get("content"),
        payload.get("request_content"),
        payload.get("description"),
        payload.get("request_description"),
        payload.get("subject"),
        payload.get("title"),
    )
    request_text = " ".join(str(value).strip() for value in text_fields if value)
    if not request_text:
        raise ValueError("Help request content is required for profanity routing")
    return request_text


def route_for_score(score: int) -> dict[str, Any]:
    """Return the workflow/table route for a profanity severity score."""
    if score not in ROUTES_BY_SCORE:
        raise InvalidProfanityScoreError("Profanity severity score must be 0, 1, 2, or 3")
    return asdict(ROUTES_BY_SCORE[score])


def extract_severity_score(response_payload: dict[str, Any]) -> int:
    """Extract a severity score from common profanity API response shapes."""
    candidate = _find_score(response_payload)
    if candidate is None:
        raise InvalidProfanityScoreError("Profanity API response did not include a severity score")

    try:
        score = int(candidate)
    except (TypeError, ValueError) as exc:
        raise InvalidProfanityScoreError("Profanity severity score must be an integer") from exc

    if score not in ROUTES_BY_SCORE:
        raise InvalidProfanityScoreError("Profanity severity score must be 0, 1, 2, or 3")
    return score


def call_profanity_api(
    text: str,
    api_url: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Call the configured profanity API and return its JSON payload."""
    import requests

    resolved_url = api_url or os.getenv(PROFANITY_API_URL_ENV)
    if not resolved_url:
        raise ProfanityApiError(f"{PROFANITY_API_URL_ENV} must be configured")

    headers = {}
    api_key = os.getenv(PROFANITY_API_KEY_ENV)
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


def evaluate_help_request_profanity(
    payload: dict[str, Any],
    profanity_client: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyze help request text and return severity plus routing metadata."""
    request_text = build_help_request_text(payload)
    client = profanity_client or call_profanity_api
    api_response = client(request_text)
    score = extract_severity_score(api_response)

    return {
        "severity_score": score,
        "route": route_for_score(score),
    }


def _find_score(payload: dict[str, Any]) -> Any:
    score_keys = (
        "severity_score",
        "severityScore",
        "classification_score",
        "classificationScore",
        "score",
    )
    for key in score_keys:
        if key in payload:
            return payload[key]

    for key in ("data", "result", "classification"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            nested_score = _find_score(nested)
            if nested_score is not None:
                return nested_score

    return None
