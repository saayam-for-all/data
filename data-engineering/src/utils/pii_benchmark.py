"""Local benchmark for request-description PII detection approaches."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from math import ceil
from typing import Callable, Iterable, Protocol


@dataclass(frozen=True)
class LabeledText:
    """A synthetic text sample and its binary PII label."""

    sample_id: str
    text: str
    contains_pii: bool


@dataclass(frozen=True)
class Metrics:
    """Detection metrics and elapsed time for one method."""

    true_positive: int
    false_negative: int
    false_positive: int
    true_negative: int
    elapsed_seconds: float
    samples_per_second: float

    @property
    def caught(self) -> int:
        """Return the number of PII-containing samples detected."""
        return self.true_positive

    @property
    def missed(self) -> int:
        """Return the number of PII-containing samples not detected."""
        return self.false_negative

    @property
    def false_positives(self) -> int:
        """Return the number of clean samples incorrectly flagged."""
        return self.false_positive


class ComprehendClient(Protocol):
    """Subset of the Amazon Comprehend client used by the benchmark."""

    def detect_pii_entities(self, **kwargs: str) -> dict:
        """Detect PII entities in one text."""


EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w.-])",
    re.IGNORECASE,
)
SSN_RE = re.compile(r"(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[ .()-]*)?"
    r"(?:\(?\d{2,4}\)?[ .-]){1,3}\d{2,4}(?!\w)"
    r"|(?<!\w)\+\d{8,15}(?!\w)"
    r"|(?<!\w)\d{10,15}(?!\w)"
)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_luhn_valid(candidate: str) -> bool:
    """Return whether a digit string satisfies the payment-card checksum."""
    digits = [int(character) for character in candidate if character.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def detect_with_patterns(text: str) -> bool:
    """Detect email, phone, payment-card, or common US SSN patterns."""
    if EMAIL_RE.search(text) or SSN_RE.search(text):
        return True
    if any(_is_luhn_valid(match.group()) for match in CARD_RE.finditer(text)):
        return True

    for match in PHONE_RE.finditer(text):
        candidate = match.group().strip()
        if ISO_DATE_RE.fullmatch(candidate):
            continue
        if sum(character.isdigit() for character in candidate) >= 8:
            return True
    return False


def make_user_name_detector(names: Iterable[str]) -> Callable[[str], bool]:
    """Build a detector for whole names present in the mock users table."""
    alternatives = sorted(
        {name.strip() for name in names if name.strip()},
        key=len,
        reverse=True,
    )
    if not alternatives:
        return lambda text: False
    name_pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(name) for name in alternatives) +
        r")(?!\w)",
        re.IGNORECASE,
    )

    def detect(text: str) -> bool:
        return bool(name_pattern.search(text))

    return detect


def detect_with_patterns_and_users(
    text: str,
    user_name_detector: Callable[[str], bool],
) -> bool:
    """Detect baseline patterns or exact names from the users lookup."""
    return detect_with_patterns(text) or user_name_detector(text)


def detect_with_comprehend(
    text: str,
    client: ComprehendClient,
    language_code: str = "en",
) -> bool:
    """Call Amazon Comprehend and report whether it found any PII entity."""
    response = client.detect_pii_entities(
        Text=text,
        LanguageCode=language_code,
    )
    entities = response.get("Entities")
    if not isinstance(entities, list):
        raise ValueError("Comprehend response is missing its Entities list")
    return bool(entities)


def evaluate(
    samples: Iterable[LabeledText],
    detector: Callable[[str], bool],
) -> Metrics:
    """Measure sample-level catch, miss, false-positive, and runtime counts."""
    sample_list = list(samples)
    if not sample_list:
        raise ValueError("At least one labeled sample is required")

    true_positive = false_negative = false_positive = true_negative = 0
    started = time.perf_counter()
    for sample in sample_list:
        predicted = detector(sample.text)
        if not isinstance(predicted, bool):
            raise TypeError("PII detectors must return a bool")
        if sample.contains_pii and predicted:
            true_positive += 1
        elif sample.contains_pii:
            false_negative += 1
        elif predicted:
            false_positive += 1
        else:
            true_negative += 1
    elapsed = time.perf_counter() - started

    return Metrics(
        true_positive=true_positive,
        false_negative=false_negative,
        false_positive=false_positive,
        true_negative=true_negative,
        elapsed_seconds=elapsed,
        samples_per_second=len(sample_list) / elapsed if elapsed else float("inf"),
    )


def estimate_monthly_comprehend_cost(
    sample_lengths: Iterable[int],
    requests_per_month: int,
    rate_per_100_characters: float = 0.0001,
) -> float:
    """Estimate Comprehend on-demand cost, rounding each request to 100 chars."""
    if requests_per_month < 0:
        raise ValueError("requests_per_month cannot be negative")
    lengths = list(sample_lengths)
    if not lengths or any(length < 0 for length in lengths):
        raise ValueError("At least one non-negative sample length is required")
    average_units = sum(max(1, ceil(length / 100)) for length in lengths) / len(lengths)
    return average_units * requests_per_month * rate_per_100_characters
