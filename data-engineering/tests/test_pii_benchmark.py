"""Tests for the issue #585 PII evaluation harness."""

import json

import pytest

from scripts.benchmark_request_pii import (
    load_samples,
    load_user_names,
    run,
)
from src.utils.pii_benchmark import (
    LabeledText,
    detect_with_comprehend,
    detect_with_patterns,
    detect_with_patterns_and_users,
    estimate_monthly_comprehend_cost,
    evaluate,
    make_user_name_detector,
)


def test_test_set_meets_issue_minimum_and_has_clean_examples():
    samples = load_samples()

    assert len(samples) >= 50
    assert sum(not sample.contains_pii for sample in samples) >= 15
    assert sum(sample.contains_pii for sample in samples) > 0


def test_pattern_detector_catches_requested_pattern_types():
    assert detect_with_patterns("Email me at person@example.invalid")
    assert detect_with_patterns("Call +1 (202) 555-0188")
    assert detect_with_patterns("Card 4111 1111 1111 1111")
    assert detect_with_patterns("ID 078-05-1120")


def test_pattern_detector_avoids_common_clean_numbers():
    assert not detect_with_patterns("The event is on 2026-02-14.")
    assert not detect_with_patterns("The bus fare is $2.75 each way.")


def test_name_lookup_finds_multilingual_users_and_not_unknown_names():
    detector = make_user_name_detector(load_user_names())

    assert detector("Please contact José Alvarez.")
    assert detector("Amina Hassan needs help.")
    assert not detector("Samira El-Amin needs help.")


def test_combined_approach_includes_patterns_and_user_names():
    detector = make_user_name_detector(load_user_names())

    assert detect_with_patterns_and_users(
        "Call +1 (202) 555-0188",
        detector,
    )
    assert detect_with_patterns_and_users(
        "Please ask Wei Chen",
        detector,
    )


def test_comprehend_adapter_uses_response_entities():
    class FakeComprehend:
        def detect_pii_entities(self, **kwargs):
            assert kwargs == {
                "Text": "Reach me at someone@example.invalid",
                "LanguageCode": "en",
            }
            return {"Entities": [{"Type": "EMAIL", "BeginOffset": 13}]}

    assert detect_with_comprehend(
        "Reach me at someone@example.invalid",
        FakeComprehend(),
    )


def test_comprehend_adapter_rejects_malformed_response():
    class FakeComprehend:
        def detect_pii_entities(self, **kwargs):
            return {}

    with pytest.raises(ValueError, match="Entities"):
        detect_with_comprehend("sample", FakeComprehend())


def test_evaluate_counts_catches_misses_and_false_positives():
    samples = [
        LabeledText("1", "one", True),
        LabeledText("2", "two", True),
        LabeledText("3", "three", False),
        LabeledText("4", "four", False),
    ]
    predictions = iter([True, False, True, False])

    metrics = evaluate(samples, lambda text: next(predictions))

    assert (metrics.caught, metrics.missed) == (1, 1)
    assert (metrics.false_positives, metrics.true_negative) == (1, 1)
    assert metrics.elapsed_seconds >= 0


def test_estimated_cost_rounds_up_by_request():
    assert estimate_monthly_comprehend_cost([101, 200], 10_000) == pytest.approx(
        2.0
    )


def test_benchmark_generates_report_without_faking_comprehend(tmp_path, monkeypatch):
    import scripts.benchmark_request_pii as benchmark

    monkeypatch.setattr(benchmark, "REPORT_PATH", tmp_path / "report.md")
    report = run()

    assert "Not measured" in report
    assert "No AWS credentials/IAM permission" in report
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == report


def test_all_approaches_receive_the_same_labeled_test_set(tmp_path, monkeypatch):
    import scripts.benchmark_request_pii as benchmark

    calls = []

    def fake_comprehend(text):
        calls.append(text)
        return "example.invalid" in text

    monkeypatch.setattr(benchmark, "REPORT_PATH", tmp_path / "report.md")
    report = run(include_comprehend=True, comprehend_detector=fake_comprehend)

    assert len(calls) == len(load_samples())
    assert "Comprehend was called live" in report
