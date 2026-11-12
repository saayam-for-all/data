"""Document-level, entity-level and latency metrics for the evaluation."""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from src.pii_evaluation.dataset import LabeledRequest
from src.pii_evaluation.spans import Span


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


@dataclass(frozen=True)
class DocumentMetrics:
    """Confusion counts for the "does this text contain PII?" decision."""

    true_positive: int
    false_negative: int
    false_positive: int
    true_negative: int

    @property
    def precision(self) -> float | None:
        return _ratio(self.true_positive, self.true_positive + self.false_positive)

    @property
    def recall(self) -> float | None:
        return _ratio(self.true_positive, self.true_positive + self.false_negative)

    @property
    def f1(self) -> float | None:
        precision, recall = self.precision, self.recall
        if precision is None or recall is None or precision + recall == 0:
            return None
        return 2 * precision * recall / (precision + recall)

    @property
    def specificity(self) -> float | None:
        return _ratio(self.true_negative, self.true_negative + self.false_positive)

    def as_dict(self) -> dict:
        """Counts and derived rates, using the Issue #585 vocabulary as well."""
        return {
            "true_positive": self.true_positive,
            "false_negative": self.false_negative,
            "false_positive": self.false_positive,
            "true_negative": self.true_negative,
            "pii_texts_caught": self.true_positive,
            "pii_texts_missed": self.false_negative,
            "clean_texts_wrongly_redacted": self.false_positive,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "specificity": self.specificity,
        }


def document_metrics(gold: Sequence[bool], predicted: Sequence[bool]) -> DocumentMetrics:
    """Count TP/FN/FP/TN for paired gold and predicted document labels."""
    if len(gold) != len(predicted):
        raise ValueError("gold and predicted must have the same length")
    counts = {"tp": 0, "fn": 0, "fp": 0, "tn": 0}
    for actual, guess in zip(gold, predicted):
        key = ("tp" if guess else "fn") if actual else ("fp" if guess else "tn")
        counts[key] += 1
    return DocumentMetrics(counts["tp"], counts["fn"], counts["fp"], counts["tn"])


def _overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def _covered_characters(start: int, end: int, spans: Iterable[Span]) -> int:
    covered = [False] * (end - start)
    for span in spans:
        for position in range(max(start, span.start), min(end, span.end)):
            covered[position - start] = True
    return sum(covered)


def entity_metrics(
    dataset: Sequence[LabeledRequest],
    predictions: Mapping[str, Sequence[Span]],
) -> dict:
    """Entity-level results.

    A gold entity is *detected* if any predicted span overlaps it, and *fully
    redacted* if predicted spans cover every one of its characters (a partially
    redacted phone number can still leak). Predicted spans that overlap no gold
    entity are counted as spurious. Entity types are not required to agree:
    for redaction, covering the text is what matters.
    """
    per_type: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "detected": 0, "fully_redacted": 0})
    users_split: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "detected": 0})
    predicted_total = spurious = 0

    for request in dataset:
        spans = list(predictions.get(request.id, ()))
        predicted_total += len(spans)
        spurious += sum(
            1 for span in spans
            if not any(_overlap(span.start, span.end, gold.start, gold.end) for gold in request.entities)
        )
        for gold in request.entities:
            stats = per_type[gold.type]
            stats["total"] += 1
            detected = any(_overlap(gold.start, gold.end, span.start, span.end) for span in spans)
            stats["detected"] += detected
            stats["fully_redacted"] += (
                _covered_characters(gold.start, gold.end, spans) == gold.end - gold.start)
            if gold.type == "PERSON" and gold.in_users_table is not None:
                bucket = users_split["in_users_table" if gold.in_users_table else "not_in_users_table"]
                bucket["total"] += 1
                bucket["detected"] += detected

    total = sum(stats["total"] for stats in per_type.values())
    detected_total = sum(stats["detected"] for stats in per_type.values())
    fully_total = sum(stats["fully_redacted"] for stats in per_type.values())
    for stats in per_type.values():
        stats["recall"] = _ratio(stats["detected"], stats["total"])
        stats["full_redaction_rate"] = _ratio(stats["fully_redacted"], stats["total"])
    for bucket in users_split.values():
        bucket["recall"] = _ratio(bucket["detected"], bucket["total"])
    return {
        "gold_entities": total,
        "detected": detected_total,
        "fully_redacted": fully_total,
        "recall": _ratio(detected_total, total),
        "full_redaction_rate": _ratio(fully_total, total),
        "predicted_spans": predicted_total,
        "spurious_spans": spurious,
        "span_precision": _ratio(predicted_total - spurious, predicted_total),
        "per_type": dict(sorted(per_type.items())),
        "person_by_users_table_membership": dict(sorted(users_split.items())),
    }


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile of ``values`` (``fraction`` between 0 and 1)."""
    if not values:
        raise ValueError("percentile of an empty sequence")
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def latency_summary(samples_ns: Sequence[int]) -> dict:
    """Mean, median, p95 and range of per-text latencies, in microseconds."""
    if not samples_ns:
        raise ValueError("no latency samples")
    micros = [sample / 1_000 for sample in samples_ns]
    return {
        "samples": len(micros),
        "mean_us": statistics.fmean(micros),
        "median_us": statistics.median(micros),
        "p95_us": percentile(micros, 0.95),
        "min_us": min(micros),
        "max_us": max(micros),
    }
