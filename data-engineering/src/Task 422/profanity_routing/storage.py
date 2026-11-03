"""Atomic routing using repository request/fraud columns and a screening ledger."""

from dataclasses import asdict
from datetime import datetime, timezone
import re

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    select,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .domain import Classification, HelpRequest, LABELS, WorkflowError


def storage_error() -> WorkflowError:
    """Report that routing did not complete, without exposing database details."""
    return WorkflowError("storage_unavailable", "The request could not be recorded. Retry later.")


class RoutingStore:
    """Keep the routing receipt and the destination row in one transaction."""

    def __init__(self, database_url: str, schema: str | None = None, active_status_id: int = 1):
        """Define tables without connecting or changing the database."""
        if schema and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
            raise ValueError("Invalid database schema.")
        if type(active_status_id) is not int or active_status_id < 1:
            raise ValueError("An active request status ID must be a positive integer.")
        self.engine = create_engine(database_url, pool_pre_ping=True)
        if self.engine.dialect.name not in {"sqlite", "postgresql"}:
            raise ValueError("Only SQLite and PostgreSQL are supported.")
        if self.engine.dialect.name == "sqlite" and schema:
            raise ValueError("Do not set a PostgreSQL schema for SQLite.")
        self.active_status_id = active_status_id
        self.metadata = MetaData(schema=schema)
        self.requests = Table(
            "request",
            self.metadata,
            Column("req_id", String(255), primary_key=True),
            Column("req_user_id", String(255), nullable=False),
            Column("req_subj", String(125), nullable=False),
            Column("req_desc", String(255), nullable=False),
            Column("req_cat_id", String(50)),
            Column("req_loc", String(125)),
            Column("req_status_id", Integer, nullable=False),
            Column("submission_date", DateTime, nullable=False),
            Column("last_update_date", DateTime, nullable=False),
        )
        self.fraud_requests = Table(
            "fraud_requests",
            self.metadata,
            Column("fraud_request_id", Integer, primary_key=True, autoincrement=True),
            Column("user_id", String(255), nullable=False),
            Column("request_datetime", DateTime, nullable=False),
            Column("reason", String(255), nullable=False),
        )
        # The existing fraud table has no request ID, text, or severity column.
        # This ledger preserves those fields without changing that table's contract.
        self.screenings = Table(
            "profanity_screenings",
            self.metadata,
            Column("request_id", String(255), primary_key=True),
            Column("fingerprint", String(64), nullable=False),
            Column("severity_score", Integer, nullable=False),
            Column("destination", String(30), nullable=False),
            Column("payload", JSON, nullable=False),
            Column("receipt", JSON, nullable=False),
            Column("created_at", DateTime, nullable=False),
            CheckConstraint("severity_score BETWEEN 0 AND 3"),
        )

    def initialize_local(self) -> None:
        """Create only the standalone SQLite tables; never auto-migrate PostgreSQL."""
        if self.engine.dialect.name != "sqlite":
            raise ValueError("Local initialization is restricted to SQLite.")
        self.metadata.create_all(self.engine)

    def lookup(self, submission: HelpRequest) -> dict | None:
        """Return a previous receipt or reject reuse of an ID for different input."""
        try:
            with self.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(self.screenings).where(
                            self.screenings.c.request_id == submission.request_id
                        )
                    )
                    .mappings()
                    .first()
                )
        except SQLAlchemyError as exc:
            raise storage_error() from exc
        if row is None:
            return None
        if row["fingerprint"] != submission.fingerprint:
            raise WorkflowError(
                "request_id_conflict", "This request ID belongs to a different submission.", 409
            )
        return {**row["receipt"], "replayed": True}

    def record(self, submission: HelpRequest, classification: Classification) -> dict:
        """Persist exactly one destination, rolling back both writes on failure."""
        active = classification.score == 0
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        receipt = {
            "request_id": submission.request_id,
            **classification.to_dict(),
            "destination": classification.destination,
            "destination_table": "request" if active else "fraud_requests",
            "workflow_status": "ready_for_matching" if active else "held_for_review",
            "recorded": True,
            "matching_invoked": False,
        }
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(self.screenings).values(
                        request_id=submission.request_id,
                        fingerprint=submission.fingerprint,
                        severity_score=classification.score,
                        destination=classification.destination,
                        payload=asdict(submission),
                        receipt=receipt,
                        created_at=now,
                    )
                )
                if active:
                    connection.execute(
                        insert(self.requests).values(
                            req_id=submission.request_id,
                            req_user_id=submission.user_id,
                            req_subj=submission.subject,
                            req_desc=submission.description,
                            req_cat_id=submission.category_id,
                            req_loc=submission.location,
                            req_status_id=self.active_status_id,
                            submission_date=now,
                            last_update_date=now,
                        )
                    )
                else:
                    connection.execute(
                        insert(self.fraud_requests).values(
                            user_id=submission.user_id,
                            request_datetime=now,
                            reason=f"Profanity screening: score {classification.score} ({LABELS[classification.score]}); held for review",
                        )
                    )
        except IntegrityError as exc:
            # A concurrent identical submission may have committed first.
            existing = self.lookup(submission)
            if existing is not None:
                return existing
            raise storage_error() from exc
        except SQLAlchemyError as exc:
            raise storage_error() from exc
        return {**receipt, "replayed": False}
