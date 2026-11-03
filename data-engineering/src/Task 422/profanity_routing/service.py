"""The shared HTTP and Lambda submission workflow."""

from .client import ProfanityClient
from .domain import HelpRequest, WorkflowError
from .storage import RoutingStore


class RoutingService:
    """Validate, screen, then save before acknowledging any routing decision."""

    def __init__(self, client: ProfanityClient, store: RoutingStore):
        """Keep transport and persistence replaceable for local verification."""
        self.client = client
        self.store = store

    def submit(self, payload: object) -> dict:
        """Replay known requests or screen and route a new submission."""
        submission = HelpRequest.from_payload(payload)
        existing = self.store.lookup(submission)
        if existing is not None:
            return existing
        classification = self.client.classify(submission)
        return self.store.record(submission, classification)


def handle_submission(service: RoutingService, payload: object) -> tuple[dict, int]:
    """Give both entry points the same status and error contract."""
    try:
        return service.submit(payload), 200
    except WorkflowError as exc:
        return {
            "error_code": exc.code,
            "message": str(exc),
            "severity_score": None,
            "destination": None,
            "recorded": False,
            "matching_invoked": False,
        }, exc.status
