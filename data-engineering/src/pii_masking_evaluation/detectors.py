"""The PII detection approaches compared in issue #585.

Every approach takes one request (subject, description) and returns, for each
field, a list of spans (start, end, label) to redact. redact() turns spans into
the cleaned text. Only the standard library is used (plus boto3 for Comprehend,
which the Lambda runtime already ships), so any of these can run inside the
archive Lambda without new packages.

  1  patterns           the regexes the archive pipeline already uses
  2  patterns+users     1 + names looked up from the users table
  3  patterns+comprehend 1 + Amazon Comprehend DetectPiiEntities
  4  improved           wider regexes (spelled-out numbers, obfuscated emails,
                        addresses, international phones) + users-table names
                        with a common-word filter + context cues ("my name is",
                        "Mr.", "my neighbor ...") for names that are not users
"""

import json
import os
import re
import time
import unicodedata

try:  # same folder whether run as a script or imported as a package
    from .pipeline_patterns import SCRUB_PATTERNS
except ImportError:  # pragma: no cover
    from pipeline_patterns import SCRUB_PATTERNS

FIELDS = ("subject", "description")


# --------------------------------------------------------------------- spans
def merge_spans(spans):
    """Sort and merge overlapping or touching spans; the first label wins."""
    out = []
    for start, end, label in sorted(spans):
        if out and start <= out[-1][1]:
            prev = out[-1]
            out[-1] = (prev[0], max(prev[1], end), prev[2])
        else:
            out.append((start, end, label))
    return out


def redact(text, spans):
    """Replace each span with [LABEL]."""
    if not text:
        return text
    pieces, pos = [], 0
    for start, end, label in merge_spans(spans):
        pieces.append(text[pos:start])
        pieces.append(f"[{label}]")
        pos = end
    pieces.append(text[pos:])
    return "".join(pieces)


def regex_spans(text, patterns):
    spans = []
    for label, pattern in patterns:
        spans.extend((m.start(), m.end(), label) for m in pattern.finditer(text))
    return spans


def pipeline_spans(text):
    """Spans the pipeline's scrub_text() replaces.

    scrub_text() applies the patterns one after another on the already-replaced
    text. Applying them in the same order and only keeping matches that don't
    overlap an earlier pattern's match gives the same result on the original
    text (checked in the tests).
    """
    spans = []
    for label, pattern in SCRUB_PATTERNS:
        for m in pattern.finditer(text):
            if not any(m.start() < e and s < m.end() for s, e, _ in spans):
                spans.append((m.start(), m.end(), label))
    return spans


# ---------------------------------------------------------------- name index
WORD = re.compile(r"[^\W\d_](?:[\w'’-]*[^\W_])?")
NAME_PARTICLES = {"al", "bin", "binti", "da", "das", "de", "del", "della", "der", "di",
                  "dos", "du", "el", "ibn", "la", "le", "ní", "ni", "nic", "ó", "o",
                  "van", "von", "y"}


def fold(word):
    """Lower-case and strip accents, so 'Ramírez' matches 'ramirez'."""
    word = unicodedata.normalize("NFKD", word.casefold())
    return "".join(c for c in word if not unicodedata.combining(c)).replace("’", "'")


# Common English words that are also first or last names. A users-table lookup
# that redacts these redacts ordinary sentences ("Grace period", "Hope someone
# can help", "May I ..."). Approach 4 only redacts them when they are next to
# another name part or after a name cue.
COMMON_WORDS = set("""
a about after all also am an and any april are art as at august autumn baker
bank bay be bell berry best bill bishop black blessing bloom bond brook brooks
brown bush but by can carter case cash chance chase church city clay cliff
coat cole cook cooper court cross dale dawn day dean december doctor dove
down drew dusty east english faith fall field fisher ford forest fox frank
free friday gay gift glad glen gold grace grant gray green guy hall happy
hardy harmony help her hill him his holly honey hope house hunter i if in
iris ivy jack january jay jewel job joy july june just justice kind king
lake lane law lee light lily long love lucky major march mark marsh mason
matt may me mercy miles mill miller monday moon more morning ms my new nick
north not now of on or page park pat patience pearl penny pierce pine
porter power price prince ray reed rich rice river rob rock rose ruby sage
saturday scott sea september shepherd short sky smith so son spring star
stone storm street summer sunday sunny taylor tea test the then thursday to
tuesday turner unity us victory wade walker ward warren water way wednesday
well wells west white will win winter wolf wood woods worth young
""".split())

CUE_WORDS = [
    r"my name is", r"name is", r"i am", r"i'm", r"im", r"this is", r"call me",
    r"ask for", r"contact", r"call", r"text", r"speak to", r"talk to", r"help",
    r"thanks,", r"thank you,", r"regards,", r"from", r"for", r"visit", r"with",
]
RELATIONS = [
    "mother", "mom", "mum", "father", "dad", "son", "daughter", "husband", "wife",
    "brother", "sister", "neighbor", "neighbour", "friend", "grandmother", "grandma",
    "grandfather", "grandpa", "uncle", "aunt", "cousin", "caseworker", "case worker",
    "landlord", "landlady", "roommate", "partner", "child", "nephew", "niece",
    "teacher", "boss", "coworker", "doctor",
]
TITLES = r"(?:mr|mrs|ms|miss|mx|dr|prof)\.?"
CUE_RE = re.compile(
    r"\b(?:" + "|".join(CUE_WORDS) + r"|" + TITLES
    + r"|(?:my|our|his|her|their)\s+(?:" + "|".join(RELATIONS) + r")(?:'s name is|,| is| named)?"
    + r"|(?:landlord|caseworker|case worker|neighbor|neighbour)(?: is)?"
    + r")\s+",
    re.IGNORECASE)


class NameIndex:
    """First, middle and last name parts from the users table."""

    def __init__(self, rows, min_len=3):
        self.parts = set()
        for row in rows:
            for key in ("first_name", "middle_name", "last_name"):
                value = (row.get(key) or "").strip()
                if not value or value.upper() == "NULL":
                    continue
                for part in re.split(r"[\s]+", value):
                    part = part.strip(".,")
                    if len(part) >= min_len and not part.isdigit():
                        self.parts.add(fold(part))

    def __contains__(self, word):
        return fold(word) in self.parts

    def __len__(self):
        return len(self.parts)

    @classmethod
    def from_csv(cls, *paths):
        import csv
        rows = []
        for path in paths:
            if path and os.path.exists(path):
                with open(path, newline="", encoding="utf-8") as f:
                    rows.extend(csv.DictReader(f))
        return cls(rows)


def users_lookup_spans(text, names):
    """Approach 2: any capitalised word that is a user's name part."""
    spans = []
    for m in WORD.finditer(text):
        word = m.group()
        if word[0].isupper() and word in names:
            spans.append((m.start(), m.end(), "NAME"))
    return spans


def _is_cap(word):
    return word[0].isupper()


def improved_name_spans(text, names):
    """Approach 4 names: users-table parts with a common-word filter, joined into
    full names, plus names that follow a cue even if they are not users."""
    words = list(WORD.finditer(text))
    spans = []

    # a) user name parts, extended to neighbouring capitalised words/particles
    i = 0
    while i < len(words):
        w = words[i].group()
        strong = w in names and fold(w) not in COMMON_WORDS
        weak = w in names and _is_cap(w)
        if strong or (weak and _neighbour_is_name(words, i, names, text)):
            j = i
            while j + 1 < len(words) and _joins(text, words[j], words[j + 1], names):
                j += 1
            k = i
            while k - 1 >= 0 and _joins(text, words[k - 1], words[k], names, backwards=True):
                k -= 1
            spans.append((words[k].start(), words[j].end(), "NAME"))
            i = j + 1
            continue
        i += 1

    # b) context cues: "my name is X Y", "Mr. X", "my neighbor X", "Thanks, X"
    for cue in CUE_RE.finditer(text):
        idx = next((n for n, w in enumerate(words) if w.start() == cue.end()), None)
        if idx is None:
            continue
        first = words[idx].group()
        cue_text = cue.group().strip().lower()
        strong_cue = cue_text.startswith(("my name", "name is", "i am", "i'm", "this is",
                                          "call me")) or re.match(TITLES, cue_text) or \
            any(r in cue_text for r in RELATIONS) or cue_text.endswith(",")
        lower_ok = cue_text.startswith(("my name", "name is"))
        if not (_is_cap(first) or lower_ok):
            continue
        if fold(first) in COMMON_WORDS and first not in names:
            continue
        if not strong_cue and first not in names:
            # weak cue ("call", "for", "help"): only with two capitalised words
            if not (idx + 1 < len(words) and _is_cap(words[idx + 1].group())
                    and _adjacent(text, words[idx], words[idx + 1])):
                continue
        j = idx
        while j + 1 < len(words) and j - idx < 3 and _adjacent(text, words[j], words[j + 1]):
            nxt = words[j + 1].group()
            if _is_cap(nxt) or fold(nxt) in NAME_PARTICLES or (lower_ok and fold(nxt) not in COMMON_WORDS):
                j += 1
            else:
                break
        spans.append((words[idx].start(), words[j].end(), "NAME"))
    return spans


def _adjacent(text, a, b):
    return re.fullmatch(r"[ \t]+", text[a.end():b.start()]) is not None


def _joins(text, a, b, names, backwards=False):
    if not _adjacent(text, a, b):
        return False
    other = a if backwards else b
    word = other.group()
    return (_is_cap(word) and (word in names or fold(word) not in COMMON_WORDS)) or \
        fold(word) in NAME_PARTICLES


def _neighbour_is_name(words, i, names, text):
    for j in (i - 1, i + 1):
        if 0 <= j < len(words):
            a, b = (words[j], words[i]) if j < i else (words[i], words[j])
            w = words[j].group()
            if _adjacent(text, a, b) and _is_cap(w) and w in names and fold(w) not in COMMON_WORDS:
                return True
    return False


# ------------------------------------------------------- improved patterns (4)
DIGIT_WORDS = {"zero": 1, "oh": 1, "o": 1, "one": 1, "two": 1, "three": 1, "four": 1,
               "five": 1, "six": 1, "seven": 1, "eight": 1, "nine": 1, "double": 0}
NUMBER_WORDS = DIGIT_WORDS.keys() | {"ten", "eleven", "twelve", "thirteen", "fourteen",
                                     "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
                                     "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
                                     "eighty", "ninety", "hundred"}
STREET = (r"(?:street|st|avenue|ave|boulevard|blvd|road|rd|drive|dr|lane|ln|way|court|ct|"
          r"place|pl|parkway|pkwy|highway|hwy|circle|cir|terrace|ter|trail|trl|loop|square|sq)")
UNIT = r"(?:,?\s*(?:apt|apartment|unit|suite|ste|#)\.?\s*[\w-]+)?"
HOUSE_NUMBER = r"(?:\d{1,6}[a-z]?|(?:" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")(?:[ -](?:" + \
    "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")){0,3})"
DOMAINS = r"(?:com|org|net|edu|gov|in|co|us|io|uk|ca|info)"

IMPROVED_PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("EMAIL", re.compile(
        r"\b[\w+-]+(?:\s*(?:\(dot\)|\[dot\]|\{dot\}|\s+dot\s+|\.)\s*[\w+-]+)*"
        r"\s*(?:\(at\)|\[at\]|\{at\}|\s+at\s+)\s*[\w-]+"
        r"(?:\s*(?:\(dot\)|\[dot\]|\{dot\}|\s+dot\s+|\.)\s*[\w-]+)*?"
        r"\s*(?:\(dot\)|\[dot\]|\{dot\}|\s+dot\s+|\.)\s*" + DOMAINS + r"\b", re.IGNORECASE)),
    ("ID", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("CARD", re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")),
    ("PHONE", re.compile(r"(?<![\d\w])\+\d{1,3}(?:[ .-]?\(?\d{1,5}\)?){2,5}(?!\d)")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?!\d)")),
    ("PHONE", re.compile(r"(?<![\d-])\d{3}[-.]\d{4}(?![\d-])")),
    ("URL", re.compile(r"https?://\S+")),
    ("ADDRESS", re.compile(r"\b" + HOUSE_NUMBER + r"\s+(?:[A-Z0-9][\w'.-]*\s+){1,4}" + STREET
                           + r"\b\.?" + UNIT, re.IGNORECASE)),
    ("ADDRESS", re.compile(r"\bP\.?\s?O\.?\s+Box\s+\d+\b", re.IGNORECASE)),
]
# House numbers written as words must start with a capital or follow "on"/"at".
_ADDRESS_WORD_START = re.compile(r"[a-z]")


def spelled_number_spans(text, min_digits=7):
    """Runs of digit words and digits ('four zero eight 555 0192') with >= 7 digits."""
    tokens = list(re.finditer(r"[A-Za-z]+|\d+", text))
    spans, i = [], 0
    while i < len(tokens):
        j, digits, words_used = i, 0, 0
        while j < len(tokens):
            tok = tokens[j].group().lower()
            if j > i and re.search(r"[^\s,.-]", text[tokens[j - 1].end():tokens[j].start()]):
                break
            if tok.isdigit():
                digits += len(tok)
            elif tok in DIGIT_WORDS:
                digits += DIGIT_WORDS[tok]
                words_used += 1
            else:
                break
            j += 1
        if digits >= min_digits and words_used >= 2:
            spans.append((tokens[i].start(), tokens[j - 1].end(), "PHONE"))
            i = j
        else:
            i += 1
    return spans


def improved_pattern_spans(text):
    spans = []
    for label, pattern in IMPROVED_PATTERNS:
        for m in pattern.finditer(text):
            if label == "ADDRESS" and _ADDRESS_WORD_START.match(m.group()) and not \
                    re.search(r"\b(?:on|at|is|to|from)\s+$", text[:m.start()], re.IGNORECASE):
                continue
            spans.append((m.start(), m.end(), label))
    spans.extend(spelled_number_spans(text))
    return spans


# --------------------------------------------------------------- comprehend
# Comprehend types that are personal details here. DATE_TIME and AGE are left
# out: "rent due 11/15" or "kids aged 4 and 7" don't identify anyone.
COMPREHEND_TYPES_SKIPPED = {"DATE_TIME", "AGE"}
COMPREHEND_MIN_SCORE = 0.5


class ComprehendDetector:
    """DetectPiiEntities on subject + description in ONE call (one minimum
    charge per request). Responses are cached in a JSON file so the evaluation
    can be re-run, and checked by reviewers, without AWS access."""

    def __init__(self, mode="cache", cache_path=None, region=None):
        self.mode = mode                     # "live" (call AWS) or "cache"
        self.cache_path = cache_path
        self.cache = {}
        if cache_path and os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                self.cache = json.load(f)
        self.client = None
        if mode == "live":
            import boto3  # in the Lambda runtime already
            self.client = boto3.client("comprehend", region_name=region or "us-east-1")
        self.call_seconds = []

    @property
    def available(self):
        return self.mode == "live" or bool(self.cache)

    def entities(self, key, text):
        if self.mode == "live":
            t0 = time.perf_counter()
            resp = self.client.detect_pii_entities(Text=text, LanguageCode="en")
            self.call_seconds.append(time.perf_counter() - t0)
            self.cache[key] = {"text": text, "entities": resp["Entities"]}
        entry = self.cache.get(key)
        if entry is None or entry["text"] != text:
            raise KeyError(f"no cached Comprehend response for {key}; run with --comprehend live")
        return entry["entities"]

    def save(self):
        if self.cache_path and self.mode == "live":
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=1, ensure_ascii=False)


# ------------------------------------------------------------- approaches
class Approach:
    key = ""
    title = ""

    def detect(self, item):
        """{'subject': [spans], 'description': [spans]} for one request."""
        raise NotImplementedError


class Patterns(Approach):
    key, title = "1", "Pattern matching only (current pipeline)"

    def detect(self, item):
        return {f: pipeline_spans(item[f] or "") for f in FIELDS}


class PatternsUsers(Approach):
    key, title = "2", "Patterns + users-table name lookup"

    def __init__(self, names):
        self.names = names

    def detect(self, item):
        return {f: pipeline_spans(item[f] or "") + users_lookup_spans(item[f] or "", self.names)
                for f in FIELDS}


class PatternsComprehend(Approach):
    key, title = "3", "Patterns + Amazon Comprehend"

    def __init__(self, comprehend):
        self.comprehend = comprehend

    def detect(self, item):
        subject, description = item["subject"] or "", item["description"] or ""
        joined = subject + "\n" + description
        out = {f: pipeline_spans(item[f] or "") for f in FIELDS}
        for ent in self.comprehend.entities(item["id"], joined):
            if ent["Type"] in COMPREHEND_TYPES_SKIPPED or ent["Score"] < COMPREHEND_MIN_SCORE:
                continue
            start, end = ent["BeginOffset"], ent["EndOffset"]
            label = ent["Type"]
            if end <= len(subject):
                out["subject"].append((start, end, label))
            elif start > len(subject):
                off = len(subject) + 1
                out["description"].append((start - off, end - off, label))
            else:  # crosses the joint: split it
                out["subject"].append((start, len(subject), label))
                out["description"].append((0, end - len(subject) - 1, label))
        return out


class Improved(Approach):
    key, title = "4", "Improved patterns + users names + name cues"

    def __init__(self, names):
        self.names = names

    def detect(self, item):
        return {f: improved_pattern_spans(item[f] or "") + improved_name_spans(item[f] or "", self.names)
                for f in FIELDS}
