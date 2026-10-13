"""Routing logic for help request screening (issue #422).

Pure functions only (no network or database access), so the routing rules
can be tested on their own.

    score 0      -> active_matching     enters the normal matching workflow
    score 1, 3   -> hold_for_review     held back for a moderator
    score 2      -> support_follow_up   held back; requester may need support
    no score     -> hold_for_review     Profanity API unavailable (fail closed)
"""
import json
from dataclasses import dataclass
from typing import Any, Optional

from utils.profanity_client import (
    DEPRESSIVE_OR_SUICIDAL,
    FOUL_LANGUAGE,
    GOOD_REQUEST,
    SEVERITY_LABELS,
    THREATENING,
    validate_severity_score,
)

ROUTE_ACTIVE_MATCHING = "active_matching"
ROUTE_HOLD_FOR_REVIEW = "hold_for_review"
ROUTE_SUPPORT_FOLLOW_UP = "support_follow_up"

SCORE_ROUTES: dict[int, str] = {
    GOOD_REQUEST: ROUTE_ACTIVE_MATCHING,
    FOUL_LANGUAGE: ROUTE_HOLD_FOR_REVIEW,
    DEPRESSIVE_OR_SUICIDAL: ROUTE_SUPPORT_FOLLOW_UP,
    THREATENING: ROUTE_HOLD_FOR_REVIEW,
}

UNSCORED_LABEL = "Unscored - Profanity API unavailable"

# Help request fields, as named in the request table and in the API payload.
SUBJECT_KEYS = ("req_subj", "subject")
DESCRIPTION_KEYS = ("req_desc", "description")


@dataclass(frozen=True)
class RoutingDecision:
    """Where a help request goes after screening."""

    severity_score: Optional[int]
    severity_label: str
    route: str

    @property
    def flagged(self) -> bool:
        """True if the request is held back from active matching."""
        return self.route != ROUTE_ACTIVE_MATCHING

    def to_dict(self) -> dict[str, Any]:
        """Return the decision as a JSON-serializable dict."""
        return {
            "severity_score": self.severity_score,
            "severity_label": self.severity_label,
            "route": self.route,
            "flagged": self.flagged,
        }


def route_by_severity_score(score: int) -> RoutingDecision:
    """Return the routing decision for a 0-3 severity score."""
    score = validate_severity_score(score)
    return RoutingDecision(score, SEVERITY_LABELS[score], SCORE_ROUTES[score])


def unscored_decision() -> RoutingDecision:
    """Return the fail-closed decision used when no score is available."""
    return RoutingDecision(None, UNSCORED_LABEL, ROUTE_HOLD_FOR_REVIEW)


def parse_event_body(event: dict[str, Any]) -> dict[str, Any]:
    """Return the request body from a Lambda event.

    Accepts API Gateway events (body as a JSON string or dict) and direct
    invocations where the event itself is the body. Raises ValueError on
    invalid JSON or a non-object body.
    """
    body = event.get("body", event)
    if isinstance(body, str):
        body = json.loads(body)
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object")
    return body


def get_text_field(body: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Return the first non-empty text value among `keys`, stripped."""
    for key in keys:
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
