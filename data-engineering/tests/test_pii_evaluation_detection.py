"""Tests for PII span handling, the detection approaches and redaction."""

import pytest

from scripts.build_pii_evaluation_dataset import DATASET_PATH, USERS_PATH
from src.pii_evaluation import comprehend as comprehend_module
from src.pii_evaluation.comprehend import ComprehendPiiDetector, comprehend_availability
from src.pii_evaluation.dataset import load_dataset
from src.pii_evaluation.detectors import approach_a, approach_b, approach_c, approach_d
from src.pii_evaluation.name_cues import find_cue_name_spans
from src.pii_evaluation.name_lookup import NameIndex, normalize_token, tokenize
from src.pii_evaluation.patterns import (
    BASELINE_PATTERNS,
    baseline_scrub_text,
    find_baseline_spans,
    find_enhanced_spans,
)
from src.pii_evaluation.spans import Span, merge_spans, redact


@pytest.fixture(scope="module")
def index():
    """Name index built from the synthetic users fixture."""
    return NameIndex.from_csv(USERS_PATH)


class FakeComprehend:
    """Stand-in for the boto3 client that records calls."""

    def __init__(self, entities=None, response=None):
        self.entities = entities or []
        self.response = response
        self.calls = []

    def detect_pii_entities(self, *, Text, LanguageCode):
        self.calls.append((Text, LanguageCode))
        return self.response if self.response is not None else {"Entities": self.entities}


# ------------------------------------------------------------------ spans

@pytest.mark.parametrize("start, end", [(-1, 3), (3, 3), (5, 2)])
def test_span_rejects_invalid_offsets(start, end):
    with pytest.raises(ValueError):
        Span(start, end, "PHONE")


def test_merge_combines_overlaps_and_keeps_touching_spans_apart():
    merged = merge_spans([Span(0, 5, "PERSON"), Span(3, 12, "ADDRESS"), Span(12, 15, "PHONE")])

    assert [(s.start, s.end, s.label) for s in merged] == [(0, 12, "ADDRESS"), (12, 15, "PHONE")]


def test_merge_keeps_longest_label_and_breaks_ties_by_priority():
    nested = merge_spans([Span(0, 20, "PHONE"), Span(4, 8, "PERSON")])
    tie = merge_spans([Span(0, 11, "PHONE", "a"), Span(0, 11, "NATIONAL_ID", "b")])

    assert nested == [Span(0, 20, "PHONE", "")]
    assert tie[0].label == "NATIONAL_ID" and tie[0].source == "a+b"


def test_redact_replaces_merged_spans_and_validates_offsets():
    text = "Call Ana at 202-555-0147."

    assert redact(text, [Span(5, 8, "PERSON"), Span(12, 24, "PHONE")]) == "Call [PERSON] at [PHONE]."
    assert redact(text, []) == text
    with pytest.raises(ValueError, match="exceeds"):
        redact(text, [Span(20, 40, "PHONE")])


# ------------------------------------------------------------------ approach A

def test_baseline_patterns_are_the_existing_pipeline_patterns():
    assert [(tag, pattern.pattern) for tag, pattern in BASELINE_PATTERNS] == [
        ("EMAIL", r"[\w.+-]+@[\w-]+\.[\w.]+"),
        ("SSN", r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),
        ("CARD", r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)"),
        ("PHONE", r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?!\d)"),
        ("URL", r"https?://\S+"),
    ]


def test_span_based_baseline_redacts_like_the_existing_scrubber():
    approach = approach_a()
    for request in load_dataset(DATASET_PATH):
        expected = baseline_scrub_text(request.text, {}).replace("[SSN]", "[NATIONAL_ID]")
        assert approach.redact(request.text) == expected, request.id


def test_baseline_scrubber_passes_through_empty_values():
    counts = {}
    assert baseline_scrub_text(None, counts) is None
    assert baseline_scrub_text("   ", counts) == "   "
    assert baseline_scrub_text("mail a@example.org", counts) == "mail [EMAIL]" and counts == {"EMAIL": 1}


def test_baseline_cannot_see_names_or_international_numbers():
    assert find_baseline_spans("Wei Zhang needs a ride") == []
    assert find_baseline_spans("Call +44 20 7946 0958") == []
    assert find_baseline_spans("Call 202-555-0147")[0].label == "PHONE"


# ------------------------------------------------------------------ approach B

def test_tokenize_keeps_joined_names_and_indic_marks_together():
    assert [t for _, _, t in tokenize("Fatima Al-Sayed, O’Neil")] == ["Fatima", "Al-Sayed", "O’Neil"]
    assert [t for _, _, t in tokenize("मेरा नाम अनीता शर्मा है")][2:4] == ["अनीता", "शर्मा"]
    assert tokenize("") == []


def test_normalize_token_ignores_case_and_accents():
    assert normalize_token("Chloé") == normalize_token("CHLOE") == "chloe"


def test_full_name_lookup_matches_accented_and_multi_part_names(index):
    assert [s.label for s in index.find_spans("Chloé Lefèvre needs help")] == ["PERSON"]
    span = index.find_spans("Please ask Nguyen Thi Lan which")[0]
    assert (span.start, span.end) == (11, 25)
    assert index.find_spans("मेरा नाम अनीता शर्मा है")


def test_full_name_mode_ignores_common_words_but_token_mode_does_not(index):
    text = "Grace period for the bill ends Friday"

    assert index.find_spans(text, mode="full") == []
    assert [s.start for s in index.find_spans(text, mode="token")] == [0]
    assert index.find_spans("grace period", mode="token") == []


def test_lookup_cannot_segment_unspaced_scripts(index):
    assert index.find_spans("我叫王伟，需要帮助搬家。", mode="token") == []


def test_name_index_rejects_unknown_mode_and_handles_empty_input(index):
    with pytest.raises(ValueError, match="mode"):
        index.find_spans("text", mode="fuzzy")
    assert NameIndex.from_user_rows([]).find_spans("Wei Zhang") == []
    assert index.find_spans("") == []


def test_approach_b_adds_names_to_baseline(index):
    redacted = approach_b(index).redact("Wei Zhang: call 202-555-0147")
    assert redacted == "[PERSON]: call [PHONE]"


# ------------------------------------------------------------------ approach D

@pytest.mark.parametrize("text, expected", [
    ("Contact me on +44 20 7946 0958 today", "+44 20 7946 0958"),
    ("Contact Ahmed (+92 300 1234567) now", "+92 300 1234567"),
    ("Call ٠٢٠ ٥٥٥ ٠١٤٧ please", "٠٢٠ ٥٥٥ ٠١٤٧"),
    ("It is five five five, two one four, eight eight nine zero.", "five five five, two one four, eight eight nine zero"),
    ("Send it to rosa dot delgado at example dot com please", "rosa dot delgado at example dot com"),
    ("My passport number is X1234567 and", "X1234567"),
    ("I am staying at 9 Hope Street.", "9 Hope Street"),
    ("See https://facebook.com/some.person today", "https://facebook.com/some.person"),
])
def test_enhanced_patterns_find_expected_text(text, expected):
    found = [text[s.start:s.end] for s in merge_spans(find_enhanced_spans(text))]
    assert expected in found


@pytest.mark.parametrize("text", [
    "The appointment is on 2026-03-14 at 10:30.",
    "Order number 4521-7789-3310 has not arrived.",
    "The total was 1,250,000 rupees.",
    "Card 4111 1111 1111 1112 fails the checksum.",
    "More at https://www.example.org/relief today.",
    "Between 18:00 and 20:00 on Saturdays.",
])
def test_enhanced_patterns_skip_common_false_positives(text):
    assert find_enhanced_spans(text) == []


@pytest.mark.parametrize("text, expected", [
    ("My name is Priya Raghunathan and", ["Priya Raghunathan"]),
    ("Contact my neighbor Dmitri Volkov because", ["Dmitri Volkov"]),
    ("Hola, soy Maria da Silva y", ["Maria da Silva"]),
    ("I am 72 years old", []),
    ("This is urgent", []),
])
def test_name_cues(text, expected):
    assert [text[s.start:s.end] for s in find_cue_name_spans(text)] == expected


# ------------------------------------------------------------------ approach C

def test_comprehend_detector_maps_filters_and_validates_entities():
    text = "Ana Silva, born 1990, lives at 1 Main St"
    client = FakeComprehend([
        {"Type": "NAME", "Score": 0.99, "BeginOffset": 0, "EndOffset": 9},
        {"Type": "DATE_TIME", "Score": 0.99, "BeginOffset": 16, "EndOffset": 20},
        {"Type": "ADDRESS", "Score": 0.30, "BeginOffset": 31, "EndOffset": 40},
    ])
    spans = ComprehendPiiDetector(client).find_spans(text)

    assert [(s.label, s.start, s.end) for s in spans] == [("PERSON", 0, 9)]
    assert client.calls == [(text, "en")]


def test_comprehend_detector_skips_blank_text_without_calling():
    client = FakeComprehend()
    assert ComprehendPiiDetector(client).find_spans("  ") == []
    assert client.calls == []


@pytest.mark.parametrize("response, message", [
    ({}, "Entities"),
    ({"Entities": [{"Type": "NAME", "Score": 1, "BeginOffset": 0, "EndOffset": 99}]}, "out of range"),
    ({"Entities": [{"Type": "NAME", "Score": 1, "BeginOffset": "0", "EndOffset": 2}]}, "invalid offsets"),
])
def test_comprehend_detector_rejects_malformed_responses(response, message):
    with pytest.raises(ValueError, match=message):
        ComprehendPiiDetector(FakeComprehend(response=response)).find_spans("Ana Silva")


def test_comprehend_detector_rejects_unsupported_input():
    with pytest.raises(ValueError, match="supports"):
        ComprehendPiiDetector(FakeComprehend(), language_code="hi")
    with pytest.raises(ValueError, match="min_score"):
        ComprehendPiiDetector(FakeComprehend(), min_score=2)
    with pytest.raises(ValueError, match="100 KB"):
        ComprehendPiiDetector(FakeComprehend()).find_spans("a" * 100_001)


def test_approach_c_merges_comprehend_with_baseline():
    client = FakeComprehend([{"Type": "NAME", "Score": 0.9, "BeginOffset": 0, "EndOffset": 9}])
    approach = approach_c(ComprehendPiiDetector(client))

    assert approach.redact("Wei Zhang: 202-555-0147") == "[PERSON]: [PHONE]"


def test_comprehend_availability_reports_missing_boto3(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "boto3":
            raise ImportError("no boto3")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    status = comprehend_availability()
    assert status["boto3_installed"] is False and status["credentials_found"] is False
    with pytest.raises(RuntimeError, match="boto3"):
        comprehend_module.create_comprehend_client("us-east-1")


# ------------------------------------------------------------------ all approaches

@pytest.mark.parametrize("build", ["a", "b", "d"])
def test_approaches_handle_empty_and_invalid_input(build, index):
    approach = {"a": approach_a, "b": lambda: approach_b(index), "d": lambda: approach_d(index)}[build]()

    assert approach.find_spans(None) == [] and approach.redact(None) is None
    assert approach.find_spans("") == [] and approach.redact("") == ""
    assert approach.contains_pii("   \n") is False
    with pytest.raises(TypeError):
        approach.find_spans(12345)


def test_redaction_never_leaves_a_detected_entity_partially_visible(index):
    approach = approach_d(index)
    for request in load_dataset(DATASET_PATH):
        spans = approach.find_spans(request.text)
        assert spans == merge_spans(spans)
        redacted = approach.redact(request.text)
        for span in spans:
            assert request.text[span.start:span.end] not in redacted
