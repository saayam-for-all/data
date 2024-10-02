from datetime import datetime
from extensions import db

class FraudRequests(db.Model):
    __tablename__ = 'fraud_requests'
    __table_args__ = {'schema': 'proposed_saayam'}

    fraud_request_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.String(255), nullable=False)
    request_datetime = db.Column(db.DateTime, nullable=False, default=datetime.now)
    reason=db.Column(db.String(255), nullable=True)