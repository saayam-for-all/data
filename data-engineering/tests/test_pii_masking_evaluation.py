"""Checks for the #585 PII masking evaluation (no AWS, no database needed)."""

import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1] / "src" / "pii_masking_evaluation"
sys.path.insert(0, str(EVAL_DIR))

import detectors  # noqa: E402
import evaluate  # noqa: E402
from pipeline_patterns import scrub_text  # noqa: E402

MAIN = evaluate.load_items(evaluate.SETS["main"])
HOLDOUT = evaluate.load_items(evaluate.SETS["holdout"])


# ---------------------------------------------------------------- test set
def test_test_set_meets_the_acceptance_criteria():
    clean = [i for i in MAIN if not i["has_pii"]]
    assert len(MAIN) >= 50
    assert len(clean) >= 15
    names = [e["text"] for i in MAIN for e in i["pii"] if e["type"] == "NAME"]
    assert any(any(ord(c) > 127 for c in n) for n in names)        # accented / non-Latin
    assert len({e["type"] for i in MAIN for e in i["pii"]}) >= 5    # several kinds of details


def test_every_label_is_in_its_text_and_clean_items_have_none():
    for item in MAIN + HOLDOUT:
        assert item["has_pii"] == bool(item["pii"])
        if item["has_pii"]:
            assert evaluate.gold_occurrences(item), item["id"]


def test_nested_label_counts_once():
    item = {"id": "x", "subject": "Ride for Grace", "description": "Grace Thompson needs a ride",
            "has_pii": True, "pii": [{"type": "NAME", "text": "Grace"},
                                     {"type": "NAME", "text": "Grace Thompson"}]}
    occ = [(f, item[f][s:e]) for f, s, e, _ in evaluate.gold_occurrences(item)]
    assert occ == [("subject", "Grace"), ("description", "Grace Thompson")]


# ------------------------------------------------------- approach 1 fidelity
def test_approach_1_redacts_exactly_like_the_pipeline():
    for item in MAIN + HOLDOUT:
        for field in detectors.FIELDS:
            text = item[field]
            expected = scrub_text(text, {})
            got = detectors.redact(text, detectors.pipeline_spans(text))
            assert got == expected, (item["id"], field)


# ------------------------------------------------------------------ scoring
def test_coverage_caught_partial_missed():
    text = "call 408 555 0101 now"
    assert evaluate.coverage(text, 5, 17, [(5, 17, "PHONE")]) == "caught"
    assert evaluate.coverage(text, 5, 17, [(5, 8, "PHONE")]) == "partial"
    assert evaluate.coverage(text, 5, 17, []) == "missed"


def test_merge_and_redact():
    assert detectors.merge_spans([(5, 9, "A"), (0, 3, "B"), (8, 12, "C")]) == [(0, 3, "B"), (5, 12, "A")]
    assert detectors.redact("Hi Maria Lopez!", [(3, 8, "NAME"), (9, 14, "NAME")]) == "Hi [NAME] [NAME]!"


# --------------------------------------------------------------- detectors
NAMES = detectors.NameIndex([{"first_name": "Grace", "last_name": "Thompson"},
                             {"first_name": "José", "last_name": "Hernández"},
                             {"first_name": "A", "last_name": "B"}])


def test_name_index_folds_accents_and_skips_short_parts():
    assert "jose" in NAMES and "HERNANDEZ" in NAMES
    assert "A" not in NAMES


def test_approach_2_redacts_common_words_that_are_names():
    text = "Grace period ended"
    assert detectors.users_lookup_spans(text, NAMES) == [(0, 5, "NAME")]


def test_approach_4_keeps_common_words_but_catches_full_names():
    assert detectors.improved_name_spans("Grace period ended", NAMES) == []
    text = "Grace Thompson needs a ride"
    assert detectors.redact(text, detectors.improved_name_spans(text, NAMES)) == "[NAME] needs a ride"


def test_approach_4_cues_catch_names_of_non_users():
    text = "My neighbor Haruto Sato fell"
    assert detectors.redact(text, detectors.improved_name_spans(text, NAMES)) == "My neighbor [NAME] fell"


def test_spelled_out_and_obfuscated_contacts():
    spans = detectors.improved_pattern_spans("call four zero eight five five five 0192 today")
    assert [s[2] for s in spans] == ["PHONE"]
    text = "write to raghu dot priya at gmail dot com"
    assert detectors.redact(text, detectors.improved_pattern_spans(text)) == "write to [EMAIL]"
    assert detectors.improved_pattern_spans("meet at the park at 5") == []


def test_comprehend_offsets_are_mapped_back_to_each_field(tmp_path):
    item = {"id": "T", "subject": "Help Maria", "description": "Call Bob at home"}
    joined = item["subject"] + "\n" + item["description"]
    cache = tmp_path / "c.json"
    ents = [{"Type": "NAME", "Score": 0.99, "BeginOffset": 5, "EndOffset": 10},
            {"Type": "NAME", "Score": 0.99, "BeginOffset": 16, "EndOffset": 19},
            {"Type": "DATE_TIME", "Score": 0.99, "BeginOffset": 0, "EndOffset": 4}]
    cache.write_text('{"T": {"text": %s, "entities": %s}}' % (
        evaluate.json.dumps(joined), evaluate.json.dumps(ents)))
    approach = detectors.PatternsComprehend(detectors.ComprehendDetector("cache", str(cache)))
    spans = approach.detect(item)
    assert detectors.redact(item["subject"], spans["subject"]) == "Help [NAME]"
    assert detectors.redact(item["description"], spans["description"]) == "Call [NAME] at home"


def test_evaluation_runs_without_aws():
    names = detectors.NameIndex.from_csv(evaluate.MOCK_USERS)
    for approach in (detectors.Patterns(), detectors.PatternsUsers(names), detectors.Improved(names)):
        result = evaluate.score(MAIN, approach)
        total = sum(result["totals"].values())
        assert total == sum(len(evaluate.gold_occurrences(i)) for i in MAIN)


def test_no_heavy_imports():
    for name in ("detectors.py", "pipeline_patterns.py", "evaluate.py"):
        src = (EVAL_DIR / name).read_text(encoding="utf-8")
        for heavy in ("presidio", "spacy", "pandas", "numpy", "torch", "transformers"):
            assert f"import {heavy}" not in src and f"from {heavy}" not in src
