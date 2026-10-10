from datetime import datetime

from src.extensions import db


class FlaggedHelpRequests(db.Model):
    """Help Requests held out of volunteer matching by the profanity check (#422).

    One row per Help Request whose Profanity API severity score is 1-3, or
    that could not be scored because the API was unavailable.
    """

    __tablename__ = 'flagged_help_requests'
    __table_args__ = {'schema': 'proposed_saayam'}

    flagged_request_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    request_id = db.Column(db.String(255), nullable=True)
    user_id = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    severity_score = db.Column(db.Integer, nullable=True)
    severity_category = db.Column(db.String(50), nullable=True)
    route = db.Column(db.String(50), nullable=False)
    flagged_datetime = db.Column(db.DateTime, nullable=False, default=datetime.now)
