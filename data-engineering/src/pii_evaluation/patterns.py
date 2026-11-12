"""Regex-based PII detection: the existing baseline and an enhanced variant.

``BASELINE_PATTERNS`` is copied verbatim from ``SCRUB_PATTERNS`` in
``data-engineering/src/requests_archive/lambda_function.py`` on branch
``hpant5_416_archive_datapipeline_rdbms_s3`` (commit ``97f1dff``, Issue #416).
That module is not merged, so the patterns are reproduced here rather than
imported. Keep them identical so Approach A measures the existing behaviour.

The enhanced patterns are a supplementary experiment for the "better approach"
invited by Issue #585. They were written by the same author as the synthetic
test set, so their measured accuracy is optimistic.
"""

from __future__ import annotations

import re
from typing import Iterable, Pattern

from src.pii_evaluation.spans import Span

BASELINE_PATTERNS: list[tuple[str, Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("SSN",   re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("CARD",  re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?!\d)")),
    ("URL",   re.compile(r"https?://\S+")),
]

BASELINE_LABELS = {"EMAIL": "EMAIL", "SSN": "NATIONAL_ID", "CARD": "CARD",
                   "PHONE": "PHONE", "URL": "URL"}


def baseline_scrub_text(value: str | None, counts: dict[str, int]) -> str | None:
    """Reproduce the existing pipeline's sequential ``scrub_text`` behaviour."""
    if value is None:
        return None
    text = str(value)
    if not text.strip():
        return value
    for tag, pattern in BASELINE_PATTERNS:
        text, replaced = pattern.subn(f"[{tag}]", text)
        if replaced:
            counts[tag] = counts.get(tag, 0) + replaced
    return text


def find_pattern_spans(
    text: str,
    patterns: Iterable[tuple[str, Pattern[str]]],
    labels: dict[str, str] | None = None,
    source: str = "patterns",
) -> list[Span]:
    """Return a span for every match of every pattern in ``text``."""
    spans = []
    for tag, pattern in patterns:
        label = labels.get(tag, tag) if labels else tag
        for match in pattern.finditer(text):
            if match.end() > match.start():
                spans.append(Span(match.start(), match.end(), label, source))
    return spans


def find_baseline_spans(text: str) -> list[Span]:
    """Approach A: spans found by the existing pipeline patterns."""
    return find_pattern_spans(text, BASELINE_PATTERNS, BASELINE_LABELS, "baseline")


# ------------------------------------------------------------------ enhanced

_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DOT = r"(?:\(dot\)|\[dot\]|\bdot\b)"
_AT = r"(?:\(at\)|\[at\]|\bat\b)"
_OBFUSCATED_EMAIL_RE = re.compile(
    rf"\b[\w+-]+(?:\s*{_DOT}\s*[\w+-]+)*\s*{_AT}\s*[\w-]+(?:\s*{_DOT}\s*[a-z]{{2,}})+\b",
    re.IGNORECASE,
)
_PHONE_CANDIDATE_RE = re.compile(r"(?<![\w+])(?:\+|00)?\(?\d[\d\s().-]{5,20}\d(?!\w)")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}")
_NON_PHONE_CONTEXT_RE = re.compile(
    r"\b(?:order|invoice|receipt|reference|ref|tracking|route|case|ticket)\b"
    r"(?:\s+(?:number|no\.?|#))?\s*[:#]?\s*$",
    re.IGNORECASE,
)
_SSN_RE = re.compile(r"(?<!\d)\d{3}[- ]\d{2}[- ]\d{4}(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_ID_KEYWORD_RE = re.compile(
    r"(?i:\b(?:passport|aadhaar|aadhar|ssn|social security|national id|id card|"
    r"identity card|driver'?s licen[cs]e)\b(?:\s+(?:number|no\.?|num|#))?\s*(?:is|:)?\s*)"
    r"(?P<value>[A-Z]{1,3}\d{5,10}|\d[\d -]{3,18}\d)"
)
_SOCIAL_URL_RE = re.compile(
    r"\b(?:https?://)?(?:www\.|m\.)?(?:facebook\.com|fb\.com|instagram\.com|"
    r"twitter\.com|x\.com|linkedin\.com|tiktok\.com|t\.me|wa\.me)/[^\s,;]+",
    re.IGNORECASE,
)
_DIGIT_WORDS = (
    "zero|oh|one|two|three|four|five|six|seven|eight|nine|"
    "cero|uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve"
)
_SPELLED_NUMBER_RE = re.compile(
    rf"\b(?:{_DIGIT_WORDS})(?:[\s,.-]+(?:{_DIGIT_WORDS})){{6,}}\b",
    re.IGNORECASE,
)
_STREET_SUFFIX = (
    r"(?:(?:Street|Avenue|Road|Lane|Boulevard|Drive|Court|Way|Place|Terrace|Close|Crescent)\b"
    r"|(?:St|Ave|Rd|Ln|Blvd|Dr|Ct|Pl)\b\.?)"
)
_UNIT_TAIL = r"(?:,?\s*(?i:apt|apartment|unit|suite|ste|building|bldg|flat|floor)\.?\s*#?\s*\w+)*"
_CITY_TAIL = r"(?:,\s*[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)?)?"
_ADDRESS_RES = [
    re.compile(
        rf"\b\d{{1,5}}[A-Za-z]?\s+(?:[A-Z][\w'’.-]*\s+){{0,3}}{_STREET_SUFFIX}"
        rf"{_UNIT_TAIL}{_CITY_TAIL}"
    ),
    re.compile(
        r"\b(?:\d{1,5}\s+)?(?:Rue|Calle|Avenida|Rua|Via|Viale|Strasse|Straße|Camino|Carrera|Jalan)"
        rf"(?:\s+[\w'’º-]+){{1,4}}{_CITY_TAIL}"
    ),
    re.compile(
        r"\b(?:House|Flat|Plot|Door)\s*(?:No\.?\s*)?\d+[A-Za-z]?"
        r"(?:,\s*(?:Lane|Street|Road|Sector|Block|Phase|Ward)\s*\d+[A-Za-z]?)*"
        r"(?:,\s*[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)?)*(?:\s+\d{6})?"
    ),
]


def _is_luhn_valid(candidate: str) -> bool:
    """Return whether the digits in ``candidate`` pass the payment-card checksum."""
    digits = [int(char) for char in candidate if char.isdigit()]
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


def _phone_spans(text: str) -> list[Span]:
    """Phone numbers with 7-15 digits, excluding dates and labelled reference numbers."""
    spans = []
    for match in _PHONE_CANDIDATE_RE.finditer(text):
        candidate = match.group()
        digit_count = sum(char.isdigit() for char in candidate)
        if not 7 <= digit_count <= 15:
            continue
        if _DATE_RE.fullmatch(candidate.strip()):
            continue
        if _NON_PHONE_CONTEXT_RE.search(text[max(0, match.start() - 30):match.start()]):
            continue
        spans.append(Span(match.start(), match.end(), "PHONE", "enhanced"))
    return spans


def find_enhanced_spans(text: str) -> list[Span]:
    """Supplementary approach: broader, still dependency-free pattern rules."""
    spans = [Span(m.start(), m.end(), "EMAIL", "enhanced") for m in _EMAIL_RE.finditer(text)]
    spans += [Span(m.start(), m.end(), "EMAIL", "enhanced")
              for m in _OBFUSCATED_EMAIL_RE.finditer(text)]
    spans += _phone_spans(text)
    spans += [Span(m.start(), m.end(), "PHONE", "enhanced")
              for m in _SPELLED_NUMBER_RE.finditer(text)]
    spans += [Span(m.start(), m.end(), "NATIONAL_ID", "enhanced")
              for m in _SSN_RE.finditer(text)]
    spans += [Span(m.start("value"), m.end("value"), "NATIONAL_ID", "enhanced")
              for m in _ID_KEYWORD_RE.finditer(text)]
    spans += [Span(m.start(), m.end(), "CARD", "enhanced")
              for m in _CARD_RE.finditer(text) if _is_luhn_valid(m.group())]
    spans += [Span(m.start(), m.end(), "URL", "enhanced")
              for m in _SOCIAL_URL_RE.finditer(text)]
    for address_re in _ADDRESS_RES:
        spans += [Span(m.start(), m.end(), "ADDRESS", "enhanced")
                  for m in address_re.finditer(text)]
    return spans
