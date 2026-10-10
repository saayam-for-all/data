"""Profanity API integration and severity-based routing for Help Requests (#422).

Flow:
    1. ``get_severity_scores`` sends the Help Request subject + description to the
       existing Profanity API (``inappropriate_content_filter`` Lambda) and returns
       the severity scores it reports.
    2. ``resolve_severity`` turns those scores into one routing score (0-3).
    3. ``route_for_score`` maps the score to the database table / workflow the
       Help Request must go to.

Severity scores returned by the Profanity API:
    0 - normal request
    1 - profanity
    2 - depressive / suicidal content
    3 - threatening content

The API URL is read from the ``PROFANITY_API_URL`` environment variable, so no
endpoint or credential is hard-coded. All HTTP calls go through ``requests`` and
can be mocked in tests.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 10

SEVERITY_CATEGORIES: dict[int, str] = {
    0: "normal",
    1: "profanity",
    2: "depressive_suicidal",
    3: "threatening",
}

# Response flags the Profanity API sets for each non-zero severity.
SEVERITY_FLAGS: dict[int, tuple[str, ...]] = {
    1: ("contains_profanity",),
    2: ("contains_depressive_content", "contains_suicidal_content"),
    3: ("contains_threatening_content",),
}


class ProfanityApiError(Exception):
    """Raised when the Profanity API cannot be reached or returns bad data."""


@dataclass(frozen=True)
class Route:
    """Where a Help Request goes after the profanity check."""

    route: str
    destination_table: str
    enters_matching: bool
    description: str


# Score -> destination. Score 0 continues into the normal matching workflow;
# every other score is held in the flagged table under its own route so it
# never reaches volunteers until it has been reviewed.
SCORE_ROUTES: dict[int, Route] = {
    0: Route(
        route="matching_workflow",
        destination_table="request",
        enters_matching=True,
        description="Normal request; continue to volunteer matching.",
    ),
    1: Route(
        route="profanity_review",
        destination_table="flagged_help_requests",
        enters_matching=False,
        description="Contains profanity; hold for steward/admin review.",
    ),
    2: Route(
        route="wellbeing_support",
        destination_table="flagged_help_requests",
        enters_matching=False,
        description="Depressive or suicidal content; escalate for support outreach.",
    ),
    3: Route(
        route="blocked_threat",
        destination_table="flagged_help_requests",
        enters_matching=False,
        description="Threatening content; block from matching and escalate to admin.",
    ),
}

# Used when the Profanity API is unavailable: fail closed so unchecked
# content never enters the matching workflow.
MANUAL_REVIEW_ROUTE = Route(
    route="manual_review",
    destination_table="flagged_help_requests",
    enters_matching=False,
    description="Profanity API unavailable; hold for manual review.",
)


def get_profanity_api_url() -> str:
    """Return the Profanity API URL from the environment."""
    url = os.getenv("PROFANITY_API_URL", "").strip()
    if not url:
        raise ProfanityApiError("PROFANITY_API_URL is not set.")
    return url


def call_profanity_api(
    subject: str,
    description: str,
    api_url: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    post: Callable[..., Any] = requests.post,
) -> dict[str, Any]:
    """Call the Profanity API and return its decoded JSON body.

    The Lambda behind API Gateway may return either the JSON body directly or
    a proxy response (``{"statusCode": ..., "body": "<json string>"}``); both
    are handled.
    """
    url = api_url or get_profanity_api_url()
    payload = {"subject": subject or "", "description": description or ""}

    try:
        response = post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ProfanityApiError(f"Profanity API call failed: {exc}") from exc

    # Unwrap a Lambda proxy-style response if the gateway passed it through.
    if isinstance(data, dict) and isinstance(data.get("body"), str):
        try:
            data = json.loads(data["body"])
        except ValueError as exc:
            raise ProfanityApiError("Profanity API returned an invalid body.") from exc

    if not isinstance(data, dict):
        raise ProfanityApiError("Profanity API returned an unexpected payload.")
    return data


def _valid_score(value: Any) -> Optional[int]:
    """Return ``value`` as an int if it is a valid severity score, else None."""
    if isinstance(value, bool):
        return None
    try:
        score = int(value)
    except (TypeError, ValueError):
        return None
    return score if score in SEVERITY_CATEGORIES else None


def extract_severity_scores(api_response: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the list of severity scores from a Profanity API response.

    Supports the three shapes the API can return:
      * ``severity_scores``: list of ``{"score", "category", "flagged"}``
      * ``severity_score`` / ``score``: a single integer 0-3
      * only the ``contains_*`` flags (original API contract)

    Returns one entry per score 0-3, each with ``score``, ``category`` and
    ``flagged``. Exactly score 0 is flagged when nothing else is.
    """
    flagged: set[int] = set()

    if isinstance(api_response.get("severity_scores"), list):
        for item in api_response["severity_scores"]:
            if not isinstance(item, dict):
                continue
            score = _valid_score(item.get("score"))
            if score is not None and item.get("flagged"):
                flagged.add(score)
    else:
        single = api_response.get("severity_score", api_response.get("score"))
        if single is not None:
            score = _valid_score(single)
            if score is None:
                raise ProfanityApiError(f"Invalid severity score: {single!r}")
            flagged.add(score)
        else:
            for score, flags in SEVERITY_FLAGS.items():
                if any(bool(api_response.get(flag)) for flag in flags):
                    flagged.add(score)

    non_zero_flagged = flagged - {0}
    return [
        {
            "score": score,
            "category": category,
            "flagged": (score in non_zero_flagged) if score else not non_zero_flagged,
        }
        for score, category in SEVERITY_CATEGORIES.items()
    ]


def resolve_severity(severity_scores: list[dict[str, Any]]) -> int:
    """Return the routing score: the highest flagged severity (0 if none)."""
    flagged = [s["score"] for s in severity_scores if s.get("flagged")]
    return max(flagged, default=0)


def route_for_score(score: int) -> Route:
    """Map a severity score (0-3) to its destination table / workflow."""
    if score not in SCORE_ROUTES:
        raise ValueError(f"Severity score must be 0-3, got {score!r}")
    return SCORE_ROUTES[score]


def get_severity_scores(
    subject: str,
    description: str,
    api_url: Optional[str] = None,
    post: Callable[..., Any] = requests.post,
) -> list[dict[str, Any]]:
    """Call the Profanity API and return the severity scores for a Help Request."""
    api_response = call_profanity_api(subject, description, api_url=api_url, post=post)
    return extract_severity_scores(api_response)


def evaluate_help_request(
    subject: str,
    description: str,
    api_url: Optional[str] = None,
    post: Callable[..., Any] = requests.post,
) -> dict[str, Any]:
    """Score a Help Request with the Profanity API and decide where it goes.

    Returns a dict with ``severity_score``, ``category``, ``severity_scores``,
    ``route``, ``destination_table``, ``enters_matching``, ``description`` and
    ``api_error`` (None on success). If the API fails, the request is routed to
    manual review instead of the matching workflow.
    """
    try:
        severity_scores = get_severity_scores(subject, description, api_url=api_url, post=post)
    except ProfanityApiError as exc:
        logger.warning("Routing help request to manual review: %s", exc)
        return {
            "severity_score": None,
            "category": None,
            "severity_scores": [],
            **asdict(MANUAL_REVIEW_ROUTE),
            "api_error": str(exc),
        }

    score = resolve_severity(severity_scores)
    route = route_for_score(score)
    logger.info("Help request scored %s; routing to %s", score, route.route)
    return {
        "severity_score": score,
        "category": SEVERITY_CATEGORIES[score],
        "severity_scores": severity_scores,
        **asdict(route),
        "api_error": None,
    }
