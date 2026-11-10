"""Character spans for detected PII, overlap merging and redaction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# When two overlapping spans are equally long, the more specific label wins.
LABEL_PRIORITY = ("EMAIL", "URL", "CARD", "NATIONAL_ID", "PHONE", "ADDRESS", "PERSON")


@dataclass(frozen=True)
class Span:
    """A detected PII entity as a half-open character range ``[start, end)``."""

    start: int
    end: int
    label: str
    source: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.start, int) or not isinstance(self.end, int):
            raise TypeError("Span offsets must be integers")
        if self.start < 0 or self.end <= self.start:
            raise ValueError(f"Invalid span offsets: start={self.start}, end={self.end}")

    @property
    def length(self) -> int:
        """Return the number of characters covered by the span."""
        return self.end - self.start


def validate_spans(spans: Iterable[Span], text_length: int) -> list[Span]:
    """Return the spans as a list, raising ``ValueError`` if any exceed the text."""
    checked = list(spans)
    for span in checked:
        if span.end > text_length:
            raise ValueError(
                f"Span [{span.start}, {span.end}) exceeds text length {text_length}"
            )
    return checked


def _priority(label: str) -> int:
    return LABEL_PRIORITY.index(label) if label in LABEL_PRIORITY else len(LABEL_PRIORITY)


def _preferred(candidate: Span, current: Span) -> bool:
    if candidate.length != current.length:
        return candidate.length > current.length
    return _priority(candidate.label) < _priority(current.label)


def merge_spans(spans: Iterable[Span]) -> list[Span]:
    """Merge overlapping spans into non-overlapping spans sorted by start.

    Spans that only touch (one ends where the next starts) stay separate. A
    merged span keeps the label of its longest constituent; between equally
    long constituents the label earlier in ``LABEL_PRIORITY`` wins. Sources are
    combined with ``+``.
    """
    ordered = sorted(spans, key=lambda span: (span.start, -span.end, _priority(span.label)))
    merged: list[Span] = []
    longest: Span | None = None
    sources: set[str] = set()

    for span in ordered:
        if merged and span.start < merged[-1].end:
            current = merged[-1]
            if longest is None or _preferred(span, longest):
                longest = span
            if span.source:
                sources.add(span.source)
            merged[-1] = Span(
                start=current.start,
                end=max(current.end, span.end),
                label=longest.label,
                source="+".join(sorted(sources)),
            )
        else:
            longest = span
            sources = {span.source} if span.source else set()
            merged.append(span)
    return merged


def redact(text: str, spans: Iterable[Span]) -> str:
    """Replace each merged span in ``text`` with a ``[LABEL]`` tag."""
    merged = merge_spans(validate_spans(spans, len(text)))
    parts: list[str] = []
    cursor = 0
    for span in merged:
        parts.append(text[cursor:span.start])
        parts.append(f"[{span.label}]")
        cursor = span.end
    parts.append(text[cursor:])
    return "".join(parts)
