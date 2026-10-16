"""Where a Help Request goes for each severity score.

This table is the single place to change routing. The mapping for scores
1-3 is provisional and needs maintainer confirmation: score 2 (depressive
or suicidal content) may belong on a welfare or manual-review path rather
than alongside fraud.
"""
from enum import Enum
from typing import Dict

from src.profanity_severity.scoring import SeverityResult


class Destination(str, Enum):
    """Workflow a scored Help Request is routed to."""

    ACTIVE_MATCHING = "active_matching"
    FRAUD_REQUESTS = "fraud_requests"


ROUTING: Dict[int, Destination] = {
    0: Destination.ACTIVE_MATCHING,
    1: Destination.FRAUD_REQUESTS,
    2: Destination.FRAUD_REQUESTS,
    3: Destination.FRAUD_REQUESTS,
}


def route_for(score: int) -> Destination:
    """Return the destination for a severity score."""
    return ROUTING[score]


def build_reason(result: SeverityResult) -> str:
    """Reason text stored with a flagged request (fits fraud_requests.reason)."""
    reason = f"profanity_severity_{result.score}:{','.join(result.categories)}"
    return reason[:255]
