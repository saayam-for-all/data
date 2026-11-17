"""Detectors for the approaches compared in issue #585.

Every detector takes one text (``req_subj`` or ``req_desc``) and returns a list
of ``(start, end, tag)`` spans to redact. ``redact`` turns spans into the
masked text.

  1  pipeline_only          the archive pipeline's current patterns
  2  pipeline_plus_lookup   1 + any word that matches a users-table name part
  3  pipeline_plus_comprehend  1 + Amazon Comprehend DetectPiiEntities
                               (see comprehend_adapter.py)
  4  improved_rules         wider patterns + users-table names + name cues
                            (standard library only, intended for Lambda)
  5  improved_plus_spacy    4's patterns + spaCy en_core_web_sm PERSON entities
                            (reference only: spaCy does not fit a zip Lambda)
"""

import re

from pipeline_patterns import pipeline_spans


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def merge_spans(spans):
    """Merge overlapping spans; the earliest span's tag wins."""
    merged = []
    for start, end, tag in sorted(spans, key=lambda s: (s[0], -s[1])):
        if merged and start < merged[-1][1]:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end), prev[2])
        else:
            merged.append((start, end, tag))
    return merged


def join_adjacent_names(text, spans):
    """Treat "[NAME] [NAME]" (two name words split by one space) as one name."""
    out = []
    for span in merge_spans(spans):
        if (out and span[2] == "NAME" and out[-1][2] == "NAME"
                and text[out[-1][1]:span[0]] == " "):
            out[-1] = (out[-1][0], span[1], "NAME")
        else:
            out.append(span)
    return out


def redact(text, spans):
    """Replace each span with ``[TAG]``."""
    out, pos = [], 0
    for start, end, tag in merge_spans(spans):
        out.append(text[pos:start])
        out.append(f"[{tag}]")
        pos = end
    out.append(text[pos:])
    return "".join(out)


_WORD = re.compile(r"[^\W\d_][\w'’-]*")


def _trim(text, start, end, chars=" \t,.;:!?)-"):
    while end > start and text[end - 1] in chars:
        end -= 1
    return start, end


# --------------------------------------------------------------------------
# Approach 2: pipeline + naive users-table lookup
# --------------------------------------------------------------------------

def lookup_spans_naive(text, name_parts):
    """Any word whose lower-case form is a users-table name part (2+ letters)."""
    spans = []
    for m in _WORD.finditer(text):
        word = m.group().strip("'’-")
        if len(word) >= 2 and word.lower() in name_parts:
            spans.append((m.start(), m.start() + len(word), "NAME"))
    return spans


def pipeline_plus_lookup(text, name_parts):
    return merge_spans(pipeline_spans(text) + lookup_spans_naive(text, name_parts))


# --------------------------------------------------------------------------
# Approach 4: improved rules (standard library only)
# --------------------------------------------------------------------------

_DIGIT_WORD = r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|double|triple)"
_TLD = r"(?:com|org|net|edu|gov|in|co|uk|io|us|info)"
_STREET = (r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Court|Ct|Boulevard|Blvd|"
           r"Way|Place|Pl|Highway|Hwy|Terrace|Ter|Circle|Cir|Parkway|Pkwy)")
_UNIT = r"(?:Apt|Apartment|Unit|Suite|Ste|Flat|#)"

IMPROVED_PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}")),
    # "name dot surname at gmail dot com", "name [at] example [dot] com"
    ("EMAIL", re.compile(
        rf"\b[\w+-]+(?:(?:\.|\s+dot\s+)[\w+-]+)*"
        rf"\s*(?:\[at\]|\(at\)|\s+at\s+)\s*"
        rf"[\w-]+(?:\s*(?:\[dot\]|\(dot\)|\.|\s+dot\s+)\s*[\w-]+)*?"
        rf"\s*(?:\[dot\]|\(dot\)|\.|\s+dot\s+)\s*{_TLD}\b", re.IGNORECASE)),
    ("URL", re.compile(r"(?:https?://|www\.)\S+|\b(?:facebook|instagram|linkedin|twitter|x|tiktok)"
                       r"\.com/\S+", re.IGNORECASE)),
    ("SSN", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("ID", re.compile(r"\b(?:passport|licen[cs]e|aadhaar|aadhar|social security|ssn|id)"
                      r"(?:\s+(?:number|no\.?|num|#))?\s*(?:is|:)?\s*"
                      r"(?P<value>(?=[A-Za-z0-9-]*\d)[A-Za-z0-9][A-Za-z0-9-]{5,})", re.IGNORECASE)),
    ("DOB", re.compile(r"\b(?:dob|d\.o\.b\.?|date of birth|born on|birthday)\s*[:\-]?\s*"
                       r"(?P<value>\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|[A-Z][a-z]+ \d{1,2},? \d{4})",
                       re.IGNORECASE)),
    ("PHONE", re.compile(rf"\b{_DIGIT_WORD}(?:[\s,.-]+{_DIGIT_WORD}\b){{6,}}", re.IGNORECASE)),
    ("ADDRESS", re.compile(
        rf"(?:\b{_UNIT}\.?\s*\w+,\s*)?"
        rf"\b\d{{1,6}}[A-Za-z]?\s+(?:[A-Z][\w'.-]*\s+){{1,4}}{_STREET}\b\.?"
        rf"(?:,?\s*{_UNIT}\.?\s*[\w-]+)?")),
    ("ADDRESS", re.compile(
        r"\b\d{1,5},?\s+(?:Rue|Calle|Avenida|Via|Strasse|Straße|Rua)\s+"
        r"(?:(?:de|del|la|le|les|des|du|di|da|do)\s+)*[A-ZÀ-Ý][\w'-]*(?:\s+[A-ZÀ-Ý][\w'-]*){0,2}")),
]

# Phone numbers in any common format; the digit count decides (see _is_phone).
_PHONE_CANDIDATE = re.compile(
    r"(?<![\w$#/.])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{1,4}\)[\s.-]?)?\d{1,12}(?:[\s.-]\d{1,12}){0,9}(?![\w/])")
_CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def _luhn_ok(digits):
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _is_phone(candidate):
    digits = re.sub(r"\D", "", candidate)
    if candidate.startswith("+"):
        return 8 <= len(digits) <= 15
    return 10 <= len(digits) <= 12


def improved_pattern_spans(text):
    spans = []
    for tag, pattern in IMPROVED_PATTERNS:
        for m in pattern.finditer(text):
            if "value" in pattern.groupindex:
                start, end = m.span("value")
            else:
                start, end = _trim(text, *m.span())
            if end > start:
                spans.append((start, end, tag))
    for m in _CARD_CANDIDATE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            spans.append((m.start(), m.end(), "CARD"))
    for m in _PHONE_CANDIDATE.finditer(text):
        if _is_phone(m.group()):
            spans.append((*_trim(text, *m.span()), "PHONE"))
    return spans


# Capitalised words that are also common English words. A users-table match on
# one of these only counts when it sits next to another name.
COMMON_WORDS = {
    "hope", "will", "may", "grace", "mark", "rose", "faith", "joy", "june", "april",
    "august", "art", "bill", "sunny", "summer", "dawn", "rich", "ray", "max", "guy",
    "frank", "chase", "page", "love", "star", "sky", "day", "main", "red", "cross",
    "help", "need", "test", "son", "the", "and", "for", "with", "white", "brown",
    "green", "black", "gray", "grey", "young", "long", "hill", "park", "street",
    "please", "thanks", "hello", "hi", "can", "pat", "sue", "don", "van", "bay",
    "lee", "king", "rue", "flat", "unit", "apt", "school", "office", "food", "bank",
}

# Words that end a name when capturing after a cue.
STOP_WORDS = {
    "and", "or", "i", "i'm", "im", "is", "am", "are", "was", "at", "on", "in", "to",
    "for", "from", "with", "my", "me", "we", "he", "she", "they", "it", "need",
    "needs", "here", "please", "who", "that", "the", "a", "an", "but", "if", "so",
    "y", "e", "mi", "es", "con", "de", "et", "und", "your", "his", "her", "our",
}

_TITLE = r"(?:Mr|Mrs|Ms|Miss|Mx|Dr|Sr|Sra|Srta|Shri|Smt)\.?"
_RELATION = (r"(?:son|daughter|husband|wife|mother|mom|mum|father|dad|neighbou?r|cousin|"
             r"caseworker|case worker|brother|sister|grandmother|grandma|grandfather|"
             r"grandpa|friend|uncle|aunt|nephew|niece|landlord|partner|child|kid|baby)")

# Cue followed by a name. "strong" cues also accept lower-case names
# ("my name is grace kim"); "weak" cues require capitalised words.
NAME_CUES = [
    ("strong", re.compile(r"\b(?:my name is|name is|name\s*:|me llamo|mi nombre es|"
                          r"je m'appelle|ich hei(?:ß|ss)e)\s+", re.IGNORECASE)),
    ("weak", re.compile(r"\b(?:i am|i'm|this is|it's|it is)\s+", re.IGNORECASE)),
    ("weak", re.compile(rf"\b{_TITLE}\s*")),
    ("weak", re.compile(rf"\b(?:my|our|his|her)\s+{_RELATION}\s*,?\s+", re.IGNORECASE)),
    ("weak", re.compile(r"\b(?:call|text|contact|ask for|reach|email|message|whatsapp)\s+",
                        re.IGNORECASE)),
    ("weak", re.compile(r"\b(?:patient|account holder|attn|beneficiary|requester|"
                        r"recipient|resident|tenant)\s*:\s*", re.IGNORECASE)),
    ("weak", re.compile(r"\b(?:thanks|thank you|regards|best|cheers|sincerely)\s*[,!-]?\s+",
                        re.IGNORECASE)),
    ("weak", re.compile(r"\bme\s*\(\s*", re.IGNORECASE)),
]
_HINDI_NAME = re.compile(r"(?:मेरा नाम|मेरा नाम है)\s+(?P<value>.+?)\s+(?:है|हैं)")
_NAME_TOKEN = re.compile(r"(?:[^\W\d_]\.|[^\W\d_][\w'’-]*)")


def _capture_name(text, pos, strong, max_tokens=3):
    """Read up to ``max_tokens`` name words starting at ``pos``."""
    start = end = None
    count = 0
    while count < max_tokens:
        m = _NAME_TOKEN.match(text, pos)
        if not m:
            break
        word = m.group()
        bare = word.rstrip(".").lower()
        if bare in STOP_WORDS:
            break
        is_title = word[0].isupper()
        if not strong and not is_title:
            break
        if re.fullmatch(_TITLE, word):     # skip "Mr." inside "ask for Mr. Mehta"
            pos = m.end()
            while pos < len(text) and text[pos] == " ":
                pos += 1
            continue
        if start is None:
            start = m.start()
        end = m.end()
        count += 1
        pos = m.end()
        if pos < len(text) and text[pos] == " ":
            pos += 1
        else:
            break
    if start is None:
        return None
    start, end = _trim(text, start, end, " ,;:!?)-")
    if text[end - 1:end] == "." and not re.fullmatch(r"[^\W\d_]\.", text[start:end].split()[-1]):
        end -= 1
    return (start, end) if end > start else None


def name_cue_spans(text):
    spans = []
    for kind, cue in NAME_CUES:
        for m in cue.finditer(text):
            found = _capture_name(text, m.end(), strong=(kind == "strong"))
            if found:
                spans.append((*found, "NAME"))
    for m in _HINDI_NAME.finditer(text):
        spans.append((*m.span("value"), "NAME"))
    return spans


def lookup_spans_careful(text, name_parts):
    """Capitalised users-table names, ignoring common words unless next to a name."""
    words = [(m.start(), m.end(), m.group().strip("'’-")) for m in _WORD.finditer(text)]
    hits = []
    for i, (s, e, w) in enumerate(words):
        if len(w) < 3 or not w[0].isupper() or w.lower() not in name_parts:
            hits.append(False)
            continue
        hits.append(w.lower() not in COMMON_WORDS)
    # A common word that is also a name ("Hope Williams") counts when it is
    # directly next to a confirmed name.
    for i, (s, e, w) in enumerate(words):
        if hits[i] or not w[:1].isupper() or w.lower() not in name_parts:
            continue
        for j in (i - 1, i + 1):
            if 0 <= j < len(words) and hits[j]:
                a, b = sorted((i, j))
                if text[words[a][1]:words[b][0]] == " ":
                    hits[i] = True
    return [(s, s + len(w), "NAME") for (s, e, w), hit in zip(words, hits) if hit]


def improved_rules(text, name_parts):
    # The improved patterns replace the pipeline's list (they cover every
    # pipeline pattern, and the card pattern adds a checksum test).
    spans = improved_pattern_spans(text)
    spans += lookup_spans_careful(text, name_parts) + name_cue_spans(text)
    return join_adjacent_names(text, spans)


# --------------------------------------------------------------------------
# Approach 5 (reference only): improved patterns + spaCy small model
# --------------------------------------------------------------------------

_SPACY = None


def spacy_available():
    try:
        import spacy  # noqa: F401
        import en_core_web_sm  # noqa: F401
        return True
    except ImportError:
        return False


def _nlp():
    global _SPACY
    if _SPACY is None:
        import en_core_web_sm
        _SPACY = en_core_web_sm.load(disable=["parser", "lemmatizer"])
    return _SPACY


def improved_plus_spacy(text, name_parts=None):
    spans = improved_pattern_spans(text)
    for ent in _nlp()(text).ents:
        if ent.label_ == "PERSON":
            spans.append((ent.start_char, ent.end_char, "NAME"))
    return join_adjacent_names(text, spans)
