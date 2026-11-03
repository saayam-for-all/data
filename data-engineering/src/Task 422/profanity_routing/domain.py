"""Validated inputs, severity results, and public errors."""

from dataclasses import asdict, dataclass
import hashlib
import json


LABELS = ("normal", "profanity", "depressive_or_suicidal", "threatening")


class WorkflowError(Exception):
    """An expected failure that can be returned without exposing internals."""

    def __init__(self, code: str, message: str, status: int = 503):
        """Keep a fixed public message separate from any underlying exception."""
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class HelpRequest:
    """The request fields needed before entering the matching workflow."""

    request_id: str
    user_id: str
    subject: str
    description: str
    category_id: str | None = None
    location: str | None = None

    @classmethod
    def from_payload(cls, payload: object) -> "HelpRequest":
        """Check required text and limits from the repository's request schema."""
        if not isinstance(payload, dict):
            raise WorkflowError("invalid_input", "Expected a JSON object.", 400)
        limits = {
            "request_id": 255,
            "user_id": 255,
            "subject": 125,
            "description": 255,
            "category_id": 50,
            "location": 125,
        }
        if set(payload) - set(limits):
            raise WorkflowError("invalid_input", "Unknown request fields.", 400)
        values = {}
        for name, limit in limits.items():
            value = payload.get(name)
            if value is None and name in ("category_id", "location"):
                values[name] = None
                continue
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > limit
                or "\x00" in value
            ):
                raise WorkflowError(
                    "invalid_input",
                    f"{name} must be nonempty text of at most {limit} characters.",
                    400,
                )
            values[name] = value.strip()
        return cls(**values)

    @property
    def fingerprint(self) -> str:
        """Bind an idempotency key to the entire normalized submission."""
        encoded = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Classification:
    """A complete, validated API result; a missing score is never zero."""

    score: int
    categories: tuple[str, ...]

    def __post_init__(self):
        """Reject invalid scores even when a caller bypasses the HTTP adapter."""
        if type(self.score) is not int or self.score not in range(4):
            raise ValueError("Severity must be an integer from 0 through 3.")

    @property
    def destination(self) -> str:
        """Use the local task's documented routing policy."""
        return "active_matching" if self.score == 0 else "fraud_requests"

    def to_dict(self) -> dict:
        """Expose the highest score and every flagged category."""
        return {
            "severity_score": self.score,
            "severity_label": LABELS[self.score],
            "flagged_categories": list(self.categories),
            "classification_status": "complete",
        }
