"""The PII detection approaches compared in the Issue #585 evaluation.

Every approach returns merged :class:`Span` objects and redacts with the same
:func:`~src.pii_evaluation.spans.redact`, so only detection differs between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.pii_evaluation.comprehend import ComprehendPiiDetector
from src.pii_evaluation.name_cues import find_cue_name_spans
from src.pii_evaluation.name_lookup import NameIndex
from src.pii_evaluation.patterns import find_baseline_spans, find_enhanced_spans
from src.pii_evaluation.spans import Span, merge_spans, redact

SpanFinder = Callable[[str], list[Span]]


@dataclass
class Approach:
    """A named combination of span finders."""

    key: str
    name: str
    finders: list[SpanFinder]

    def find_spans(self, text: str | None) -> list[Span]:
        """Run every finder on ``text`` and return the merged spans."""
        if text is None:
            return []
        if not isinstance(text, str):
            raise TypeError(f"text must be a string or None, got {type(text).__name__}")
        if not text.strip():
            return []
        spans: list[Span] = []
        for finder in self.finders:
            spans.extend(finder(text))
        return merge_spans(spans)

    def contains_pii(self, text: str | None) -> bool:
        """Document-level decision: whether any PII span was found."""
        return bool(self.find_spans(text))

    def redact(self, text: str | None) -> str | None:
        """Return ``text`` with every detected span replaced by a ``[LABEL]`` tag."""
        if text is None:
            return None
        return redact(text, self.find_spans(text))


def approach_a() -> Approach:
    """A: the existing pipeline's pattern matching only."""
    return Approach("A", "A. Existing patterns only", [find_baseline_spans])


def approach_b(index: NameIndex, mode: str = "full") -> Approach:
    """B: existing patterns plus a lookup against ``users`` table names."""
    label = "full names" if mode == "full" else "full names + single name tokens"
    return Approach(
        f"B_{mode}",
        f"B. Existing patterns + users lookup ({label})",
        [find_baseline_spans, lambda text: index.find_spans(text, mode=mode)],
    )


def approach_c(detector: ComprehendPiiDetector) -> Approach:
    """C: existing patterns plus Amazon Comprehend ``DetectPiiEntities``."""
    return Approach("C", "C. Existing patterns + Amazon Comprehend",
                    [find_baseline_spans, detector.find_spans])


def approach_d(index: NameIndex) -> Approach:
    """D (supplementary): enhanced patterns + full-name lookup + context cues."""
    return Approach(
        "D",
        "D. Enhanced patterns + users full-name lookup + name cues (supplementary)",
        [find_enhanced_spans, lambda text: index.find_spans(text, mode="full"),
         find_cue_name_spans],
    )
