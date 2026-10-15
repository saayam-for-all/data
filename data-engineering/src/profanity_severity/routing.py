"""Severity-based routing for help requests (#422).

Follows the existing ``/api/check_fraud`` convention: a request that must not
proceed is recorded in ``fraud_requests`` (``FraudRequests`` model) with a
reason, and a request that passes is left untouched.

    score 0   -> not flagged, nothing is written (same as a valid request in
                 check_fraud)
    score 1-3 -> a ``fraud_requests`` row is written with the reason below

Routing never invokes active matching: that workflow is not connected to this
service, so ``active_matching_invoked`` is always False and callers must
continue the request workflow themselves when ``is_flagged`` is False.

The session and model are injected so the logic is testable without a database.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

FLAGGED_REASONS = {
    1: "Profanity severity 1: profanity",
    2: "Profanity severity 2: depressive or suicidal content",
    3: "Profanity severity 3: threatening content",
}


class RoutingError(Exception):
    """A flagged request could not be recorded."""


def route_by_severity(severity_score, user_id, session, model, now=None):
    """Route a scored request; returns a routing summary dict.

    Raises ValueError for an invalid score or user_id and RoutingError if the
    flagged request could not be written (the session is rolled back).
    """
    if type(severity_score) is not int or severity_score not in (0, 1, 2, 3):
        raise ValueError("severity_score must be an integer from 0 to 3")

    if severity_score == 0:
        return {
            "is_flagged": False,
            "routing": "none",
            "reason": None,
            "fraud_request_id": None,
            "active_matching_invoked": False,
        }

    if not isinstance(user_id, (str, int)) or isinstance(user_id, bool) or not str(user_id).strip():
        raise ValueError("user_id is required to record a flagged request")

    reason = FLAGGED_REASONS[severity_score]
    record = model(
        user_id=str(user_id).strip(),
        request_datetime=now or datetime.now(),
        reason=reason,
    )

    try:
        session.add(record)
        session.commit()
    except Exception as exc:
        logger.error("Could not record flagged request: %s", type(exc).__name__)
        try:
            session.rollback()
        except Exception:
            logger.error("Rollback after failed write also failed")
        raise RoutingError("flagged request was not recorded") from None

    return {
        "is_flagged": True,
        "routing": "fraud_requests",
        "reason": reason,
        "fraud_request_id": getattr(record, "fraud_request_id", None),
        "active_matching_invoked": False,
    }
