"""Tests for the Issue #585 synthetic PII dataset and users fixture."""

import json

import pytest

from scripts.build_pii_evaluation_dataset import (
    DATASET_PATH,
    USERS_PATH,
    render_dataset,
    render_users,
)
from src.pii_evaluation.dataset import ENTITY_TYPES, load_binary_dataset, load_dataset, parse_record
from src.pii_evaluation.patterns import _is_luhn_valid


@pytest.fixture(scope="module")
def dataset():
    """Load the committed dataset once for this module."""
    return load_dataset(DATASET_PATH)


def _valid_record(**overrides):
    record = {
        "id": "X1", "text": "Call 202-555-0147 now.", "contains_pii": True, "language": "en",
        "entity_types": ["PHONE"], "tags": [],
        "entities": [{"type": "PHONE", "start": 5, "end": 17, "text": "202-555-0147"}],
    }
    record.update(overrides)
    return record


def test_committed_fixtures_match_the_builder():
    assert DATASET_PATH.read_text(encoding="utf-8") == render_dataset()
    assert USERS_PATH.read_text(encoding="utf-8") == render_users()


def test_dataset_meets_size_and_clean_minimums(dataset):
    assert len(dataset) >= 60
    assert sum(not request.contains_pii for request in dataset) >= 20
    assert sum(request.contains_pii for request in dataset) >= 40


def test_every_entity_span_matches_its_text(dataset):
    for request in dataset:
        for entity in request.entities:
            assert request.text[entity.start:entity.end] == entity.text
        assert request.contains_pii == bool(request.entities)


def test_dataset_covers_required_categories(dataset):
    types = {entity.type for request in dataset for entity in request.entities}
    tags = [tag for request in dataset for tag in request.tags]

    assert {"EMAIL", "PHONE", "PERSON", "ADDRESS"} <= types <= ENTITY_TYPES
    assert tags.count("international_phone") >= 5
    assert tags.count("spelled_out") >= 3
    assert sum(1 for r in dataset if "mixed_language" in r.tags and r.contains_pii) >= 3
    assert sum(1 for r in dataset if len(r.entities) >= 2) >= 5
    assert sum(1 for r in dataset if not r.contains_pii and any(t.startswith("fp_trap") for t in r.tags)) >= 10
    assert {r.language for r in dataset} >= {"en", "es", "fr", "hi", "zh", "mixed"}


def test_dataset_includes_non_english_and_non_latin_names(dataset):
    names = [e.text for r in dataset for e in r.entities if e.type == "PERSON"]
    non_ascii = [name for name in names if not name.isascii()]

    assert len(non_ascii) >= 4
    assert any("\u0900" <= char <= "\u097f" for name in names for char in name)
    assert any("\u4e00" <= char <= "\u9fff" for name in names for char in name)


def test_person_entities_record_users_table_membership(dataset):
    people = [e for r in dataset for e in r.entities if e.type == "PERSON"]

    assert all(person.in_users_table is not None for person in people)
    assert any(person.in_users_table for person in people)
    assert any(not person.in_users_table for person in people)


def test_contact_details_are_synthetic(dataset):
    for request in dataset:
        for entity in request.entities:
            if entity.type == "EMAIL" and "@" in entity.text:
                assert entity.text.rsplit("@", 1)[1] in {"example.com", "example.org", "example.net"}
            if entity.type == "CARD":
                assert entity.text.replace(" ", "").replace("-", "") in {
                    "4111111111111111", "5555555555554444"}
                assert _is_luhn_valid(entity.text)


def test_parse_record_rejects_mismatched_span():
    entity = {"type": "PHONE", "start": 5, "end": 17, "text": "999-555-0147"}
    with pytest.raises(ValueError, match="span text"):
        parse_record(_valid_record(entities=[entity]))


def test_parse_record_rejects_overlapping_entities():
    entities = [{"type": "PHONE", "start": 5, "end": 17, "text": "202-555-0147"},
                {"type": "PHONE", "start": 9, "end": 17, "text": "555-0147"}]
    with pytest.raises(ValueError, match="overlapping"):
        parse_record(_valid_record(entities=entities))


@pytest.mark.parametrize("overrides, message", [
    ({"contains_pii": False}, "contains_pii"),
    ({"entity_types": ["EMAIL"]}, "entity_types"),
    ({"text": "   "}, "empty text"),
    ({"entities": [{"type": "SECRET", "start": 5, "end": 17, "text": "202-555-0147"}],
      "entity_types": ["SECRET"]}, "unknown entity type"),
    ({"entities": [{"type": "PHONE", "start": 5, "end": 99, "text": "202-555-0147"}]}, "out-of-range"),
])
def test_parse_record_rejects_invalid_labels(overrides, message):
    with pytest.raises(ValueError, match=message):
        parse_record(_valid_record(**overrides))


def test_parse_record_requires_all_fields():
    record = _valid_record()
    del record["language"]
    with pytest.raises(ValueError, match="missing"):
        parse_record(record)


def test_load_dataset_rejects_duplicate_ids_and_empty_files(tmp_path):
    duplicate = tmp_path / "duplicate.jsonl"
    line = json.dumps(_valid_record())
    duplicate.write_text(f"{line}\n{line}\n", encoding="utf-8")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{not json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate"):
        load_dataset(duplicate)
    with pytest.raises(ValueError, match="empty"):
        load_dataset(empty)
    with pytest.raises(ValueError, match="line 1"):
        load_dataset(malformed)


def test_load_binary_dataset_accepts_document_labels_only(tmp_path):
    path = tmp_path / "external.jsonl"
    path.write_text('{"id": "E1", "text": "hello", "contains_pii": false}\n', encoding="utf-8")
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": "E1", "text": "hello", "contains_pii": "no"}\n', encoding="utf-8")

    assert load_binary_dataset(path)[0].contains_pii is False
    with pytest.raises(ValueError, match="boolean"):
        load_binary_dataset(bad)
