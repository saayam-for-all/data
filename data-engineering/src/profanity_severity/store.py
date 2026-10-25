"""Persistence for flagged Help Requests."""
from datetime import datetime

from src.extensions import db
from src.models.fraud_requests import FraudRequests


def record_flagged_request(user_id: str, reason: str) -> None:
    """Write a flagged request to fraud_requests, same as check_fraud does.

    Raises:
        Exception: any database error, after rolling back the session.
    """
    row = FraudRequests(
        user_id=user_id,
        request_datetime=datetime.now(),
        reason=reason,
    )
    try:
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
