"""Name detection by lookup against names from the ``users`` table.

Text is split into Unicode word tokens and compared against an in-memory index,
so lookup cost per text depends on the number of tokens, not the number of
users. Matching is case-insensitive and accent-insensitive.

Two modes are supported:

* ``full``: a run of two or more tokens equal to a user's full name
  (``first last`` or ``first middle last``, or ``full_name``).
* ``token``: additionally, any single capitalised token equal to a user's first
  or last name. Higher recall, but common words that are also names (``May``,
  ``Grace``, ``Mark``) become false positives.

Scripts written without spaces (Chinese, Japanese, Thai) are not segmented, so
names in them are only found when surrounded by spaces or punctuation.
"""

from __future__ import annotations

import csv
import unicodedata
from pathlib import Path
from typing import Iterable, Mapping

from src.pii_evaluation.spans import Span

NAME_FIELDS = ("first_name", "middle_name", "last_name", "full_name")
_JOINERS = "'’-"
_MAX_NAME_TOKENS = 5


def _is_word_char(char: str) -> bool:
    return unicodedata.category(char)[0] in "LMN"


def tokenize(text: str) -> list[tuple[int, int, str]]:
    """Split ``text`` into ``(start, end, token)`` word tokens.

    Letters, combining marks and digits form words. An apostrophe or hyphen
    between two word characters stays inside the token (``Al-Sayed``).
    """
    tokens = []
    index = 0
    length = len(text)
    while index < length:
        if not _is_word_char(text[index]):
            index += 1
            continue
        start = index
        while index < length and (
            _is_word_char(text[index])
            or (text[index] in _JOINERS and index + 1 < length
                and _is_word_char(text[index + 1]) and index > start)
        ):
            index += 1
        tokens.append((start, index, text[start:index]))
    return tokens


def normalize_token(token: str) -> str:
    """Case-fold and remove combining marks so ``Chloé`` equals ``chloe``."""
    decomposed = unicodedata.normalize("NFKD", token)
    stripped = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return unicodedata.normalize("NFKC", stripped).casefold()


def _is_capitalized(token: str) -> bool:
    """True for a token starting with an uppercase letter or an uncased letter."""
    first = token[0]
    if first.upper() == first.lower():
        return first.isalpha()
    return first.isupper()


def _name_key(value: str) -> tuple[str, ...]:
    return tuple(normalize_token(token) for _, _, token in tokenize(value))


class NameIndex:
    """In-memory index of user names for full-name and single-token lookup."""

    def __init__(self, full_names: Iterable[tuple[str, ...]], single_names: Iterable[str]):
        self.full_names = {key for key in full_names if 2 <= len(key) <= _MAX_NAME_TOKENS}
        self.single_names = {name for name in single_names if len(name) >= 2}
        self.max_tokens = max((len(key) for key in self.full_names), default=0)

    @classmethod
    def from_user_rows(cls, rows: Iterable[Mapping[str, str | None]]) -> "NameIndex":
        """Build the index from rows with ``users`` name columns."""
        full_names: set[tuple[str, ...]] = set()
        single_names: set[str] = set()
        for row in rows:
            first = (row.get("first_name") or "").strip()
            middle = (row.get("middle_name") or "").strip()
            last = (row.get("last_name") or "").strip()
            full = (row.get("full_name") or "").strip()
            for candidate in (full, f"{first} {last}", f"{first} {middle} {last}"):
                key = _name_key(candidate)
                if key:
                    full_names.add(key)
            for part in (first, last):
                single_names.update(_name_key(part))
        return cls(full_names, single_names)

    @classmethod
    def from_csv(cls, path: str | Path) -> "NameIndex":
        """Build the index from a CSV export of the ``users`` name columns."""
        with Path(path).open(encoding="utf-8", newline="") as source:
            return cls.from_user_rows(csv.DictReader(source))

    def __len__(self) -> int:
        return len(self.full_names)

    def find_spans(self, text: str, mode: str = "full") -> list[Span]:
        """Return PERSON spans for user names found in ``text``."""
        if mode not in ("full", "token"):
            raise ValueError("mode must be 'full' or 'token'")
        tokens = tokenize(text)
        keys = [normalize_token(token) for _, _, token in tokens]
        spans = []
        index = 0
        while index < len(tokens):
            matched = 0
            for size in range(min(self.max_tokens, len(tokens) - index), 1, -1):
                if tuple(keys[index:index + size]) in self.full_names:
                    matched = size
                    break
            if matched:
                spans.append(Span(tokens[index][0], tokens[index + matched - 1][1],
                                  "PERSON", f"users_{mode}"))
                index += matched
                continue
            if (mode == "token" and keys[index] in self.single_names
                    and _is_capitalized(tokens[index][2])):
                spans.append(Span(tokens[index][0], tokens[index][1], "PERSON", "users_token"))
            index += 1
        return spans
