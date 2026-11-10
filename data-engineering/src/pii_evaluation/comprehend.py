"""Amazon Comprehend ``DetectPiiEntities`` adapter for the evaluation.

The client is injected so tests and local runs never reach AWS. ``boto3`` is
imported only inside :func:`create_comprehend_client`; the Lambda Python runtime
already ships it, so this adds no deployment package size.

Every call is billable (see ``costs.py``). The benchmark refuses to create a live
client unless billable calls are explicitly approved on the command line.
"""

from __future__ import annotations

from typing import Any, Protocol

from src.pii_evaluation.spans import Span

SUPPORTED_LANGUAGES = frozenset({"en", "es"})
MAX_TEXT_BYTES = 100_000
DEFAULT_MIN_SCORE = 0.5
# Dates and ages are returned as PII by Comprehend but are not labelled as PII in
# the #585 test set, so they are excluded to keep the comparison like for like.
DEFAULT_EXCLUDED_TYPES = frozenset({"DATE_TIME", "AGE"})

TYPE_LABELS = {
    "NAME": "PERSON",
    "ADDRESS": "ADDRESS",
    "PHONE": "PHONE",
    "EMAIL": "EMAIL",
    "URL": "URL",
    "SSN": "NATIONAL_ID",
    "PASSPORT_NUMBER": "NATIONAL_ID",
    "DRIVER_ID": "NATIONAL_ID",
    "IN_AADHAAR": "NATIONAL_ID",
    "IN_PERMANENT_ACCOUNT_NUMBER": "NATIONAL_ID",
    "IN_VOTER_NUMBER": "NATIONAL_ID",
    "UK_NATIONAL_INSURANCE_NUMBER": "NATIONAL_ID",
    "CA_SOCIAL_INSURANCE_NUMBER": "NATIONAL_ID",
    "CREDIT_DEBIT_NUMBER": "CARD",
}


class ComprehendClient(Protocol):
    """The subset of the boto3 Comprehend client used here."""

    def detect_pii_entities(self, *, Text: str, LanguageCode: str) -> dict[str, Any]:
        """Detect PII entities in one document."""


class ComprehendPiiDetector:
    """Turn ``DetectPiiEntities`` responses into :class:`Span` objects."""

    def __init__(
        self,
        client: ComprehendClient,
        language_code: str = "en",
        min_score: float = DEFAULT_MIN_SCORE,
        excluded_types: frozenset[str] = DEFAULT_EXCLUDED_TYPES,
    ):
        if language_code not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"DetectPiiEntities supports {sorted(SUPPORTED_LANGUAGES)}, got {language_code!r}"
            )
        if not 0.0 <= min_score <= 1.0:
            raise ValueError("min_score must be between 0 and 1")
        self.client = client
        self.language_code = language_code
        self.min_score = min_score
        self.excluded_types = excluded_types
        self.calls = 0

    def find_spans(self, text: str) -> list[Span]:
        """Call Comprehend once and return the accepted entities as spans."""
        if not text.strip():
            return []
        if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("Text exceeds the 100 KB DetectPiiEntities limit")
        response = self.client.detect_pii_entities(Text=text, LanguageCode=self.language_code)
        self.calls += 1
        entities = response.get("Entities") if isinstance(response, dict) else None
        if not isinstance(entities, list):
            raise ValueError("Comprehend response is missing its Entities list")

        spans = []
        for entity in entities:
            entity_type = entity.get("Type")
            score = entity.get("Score", 0.0)
            start, end = entity.get("BeginOffset"), entity.get("EndOffset")
            if not isinstance(start, int) or not isinstance(end, int):
                raise ValueError(f"Comprehend entity has invalid offsets: {entity!r}")
            if not 0 <= start < end <= len(text):
                raise ValueError(f"Comprehend offsets out of range for text: {entity!r}")
            if entity_type in self.excluded_types or score < self.min_score:
                continue
            spans.append(Span(start, end, TYPE_LABELS.get(entity_type, "OTHER"), "comprehend"))
        return spans


def create_comprehend_client(region: str) -> ComprehendClient:
    """Create a real boto3 Comprehend client. Only used for an approved live run."""
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for a live Comprehend run") from exc
    return boto3.client("comprehend", region_name=region)


def comprehend_availability() -> dict[str, Any]:
    """Report, without calling AWS, whether a live Comprehend run is possible."""
    try:
        import boto3
    except ImportError:
        return {"boto3_installed": False, "credentials_found": False,
                "reason": "boto3 is not installed in this environment"}
    credentials = boto3.Session().get_credentials()
    found = credentials is not None
    return {
        "boto3_installed": True,
        "credentials_found": found,
        "reason": "credentials found; IAM permission comprehend:DetectPiiEntities is "
                  "only confirmed by a live call" if found else "no AWS credentials found",
    }
