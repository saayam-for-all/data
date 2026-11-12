"""Loading and validation of the labelled synthetic request-text dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ENTITY_TYPES = frozenset({"EMAIL", "PHONE", "PERSON", "ADDRESS", "NATIONAL_ID", "CARD", "URL"})


@dataclass(frozen=True)
class GoldEntity:
    """A labelled PII entity with its exact character span."""

    type: str
    start: int
    end: int
    text: str
    in_users_table: bool | None = None


@dataclass(frozen=True)
class LabeledRequest:
    """One synthetic request description and its labels."""

    id: str
    text: str
    contains_pii: bool
    language: str
    entities: tuple[GoldEntity, ...] = ()
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def entity_types(self) -> tuple[str, ...]:
        """Sorted distinct entity types present in the text."""
        return tuple(sorted({entity.type for entity in self.entities}))


def parse_record(record: dict) -> LabeledRequest:
    """Validate one JSON record and convert it to a :class:`LabeledRequest`."""
    required = {"id", "text", "contains_pii", "language", "entity_types", "entities", "tags"}
    missing = required - record.keys()
    if missing:
        raise ValueError(f"Record {record.get('id')!r} is missing {sorted(missing)}")

    text = record["text"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Record {record['id']!r} has empty text")

    entities = []
    for item in record["entities"]:
        entity = GoldEntity(item["type"], item["start"], item["end"], item["text"],
                            item.get("in_users_table"))
        if entity.type not in ENTITY_TYPES:
            raise ValueError(f"Record {record['id']!r} has unknown entity type {entity.type!r}")
        if not 0 <= entity.start < entity.end <= len(text):
            raise ValueError(f"Record {record['id']!r} has an out-of-range span")
        if text[entity.start:entity.end] != entity.text:
            raise ValueError(f"Record {record['id']!r} span text does not match {entity.text!r}")
        entities.append(entity)

    ordered = sorted(entities, key=lambda entity: entity.start)
    for previous, current in zip(ordered, ordered[1:]):
        if current.start < previous.end:
            raise ValueError(f"Record {record['id']!r} has overlapping entities")

    request = LabeledRequest(
        id=record["id"],
        text=text,
        contains_pii=record["contains_pii"],
        language=record["language"],
        entities=tuple(ordered),
        tags=tuple(record["tags"]),
    )
    if request.contains_pii != bool(request.entities):
        raise ValueError(f"Record {request.id!r}: contains_pii disagrees with its entities")
    if list(request.entity_types) != sorted(record["entity_types"]):
        raise ValueError(f"Record {request.id!r}: entity_types disagrees with its entities")
    return request


def load_binary_dataset(path: str | Path) -> list[LabeledRequest]:
    """Load an external JSONL set labelled only with ``id``, ``text``, ``contains_pii``.

    Used for held-out, document-level checks (for example the PR #659 fixture).
    Records carry no entity spans, so only document metrics apply to them.
    """
    requests = []
    with Path(path).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item.get("text"), str) or not isinstance(item.get("contains_pii"), bool):
                raise ValueError(f"Line {line_number} needs a string text and a boolean contains_pii")
            requests.append(LabeledRequest(id=str(item.get("id", line_number)), text=item["text"],
                                           contains_pii=item["contains_pii"], language="unknown",
                                           tags=("external",)))
    if not requests:
        raise ValueError("Dataset is empty")
    return requests


def load_dataset(path: str | Path) -> list[LabeledRequest]:
    """Load a JSONL dataset, validating every record and that ids are unique."""
    requests = []
    seen: set[str] = set()
    with Path(path).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                request = parse_record(json.loads(line))
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError(f"Invalid record on line {line_number}: {exc}") from exc
            if request.id in seen:
                raise ValueError(f"Duplicate id {request.id!r}")
            seen.add(request.id)
            requests.append(request)
    if not requests:
        raise ValueError("Dataset is empty")
    return requests
