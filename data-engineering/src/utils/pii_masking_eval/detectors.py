"""Lightweight PII detectors for req_subj / req_desc (issue #585).

Stdlib only (re, csv, unicodedata) so it is safe to import inside a Lambda
without layers.  Every detector returns a list of (start, end, label) spans;
`redact()` turns spans into masked text.

  approach 1  detect_patterns          - regex only (email, phone, card, SSN, Aadhaar, passport, DOB)
  approach 2  detect_patterns_lookup   - 1 + whole-word match against names from the users table
  approach 4  detect_layered           - 1 + spoken-number/obfuscated-email normalisation,
                                           address rules, name cue phrases (EN/ES/HI/MR/KO/ZH),
                                           + the users lookup
(approach 3 = approach 1 + Amazon Comprehend, see run_comprehend.py)
"""
import csv
import re

# ------------------------------------------------------------------ helpers
def _luhn(digits: str) -> bool:
    s, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        s += d
        alt = not alt
    return s % 10 == 0


def merge(spans):
    """Merge overlapping / touching spans; keep first label."""
    out = []
    for s, e, l in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(e, out[-1][1]), out[-1][2])
        else:
            out.append((s, e, l))
    return out


def redact(text, spans):
    res, last = [], 0
    for s, e, l in merge(spans):
        res.append(text[last:s])
        res.append(f"[{l}]")
        last = e
    res.append(text[last:])
    return "".join(res)


# ------------------------------------------------------- approach 1: patterns
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# 10 digits with optional +cc and common separators, or +cc with 8-12 digits
PHONE = re.compile(
    r"(?<![\w$.,])(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.\-]?)\d{3}[\s.\-]?\d{4}(?!\d)"
    r"|(?<!\w)\+\d{1,3}[\s.\-]?\d{5}[\s.\-]?\d{5}(?!\d)"
)
SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
AADHAAR = re.compile(r"(?<!\d)[2-9]\d{3}[\s\-]?\d{4}[\s\-]?\d{4}(?!\d)")
CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")
PASSPORT = re.compile(r"(?i)\bpassport(?:\s+(?:no\.?|number|#))?\s*[:#]?\s*([A-Z]\d{7,8}|\d{9})\b")
DOB = re.compile(r"(?i)\b(?:dob|d\.o\.b\.?|date of birth|born(?: on)?)\s*[:\-]?\s*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|[A-Z][a-z]+ \d{1,2},? \d{4})")


def detect_patterns(text):
    spans = []
    for m in EMAIL.finditer(text):
        spans.append((m.start(), m.end(), "EMAIL"))
    for m in SSN.finditer(text):
        spans.append((m.start(), m.end(), "ID"))
    for m in CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            spans.append((m.start(), m.end(), "CARD"))
    for m in AADHAAR.finditer(text):
        spans.append((m.start(), m.end(), "ID"))
    for m in PASSPORT.finditer(text):
        spans.append((m.start(1), m.end(1), "ID"))
    for m in DOB.finditer(text):
        spans.append((m.start(1), m.end(1), "DOB"))
    for m in PHONE.finditer(text):
        spans.append((m.start(), m.end(), "PHONE"))
    return merge(spans)


# ------------------------------------------------- approach 2: users lookup
# Junk / test / very common tokens found in the mock users table that would
# otherwise cause false positives.
_NAME_STOP = {
    "null", "none", "test", "demo", "demofirst", "demolast", "user", "name", "first", "last",
    "asdf", "abcd", "rbac", "admin", "the", "and", "kumar_", "bowo",
}


def load_name_lookup(users_csv_path, min_len=3):
    """Return a set of lowercase name tokens (first/middle/last) from users.csv."""
    toks = set()
    with open(users_csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            for col in ("first_name", "middle_name", "last_name", "full_name"):
                for t in re.split(r"\s+", (row.get(col) or "").strip()):
                    t = t.strip(".,").lower()
                    if (len(t) >= min_len and t.isalpha() and t not in _NAME_STOP):
                        toks.add(t)
    return toks


def build_lookup_regex(tokens):
    if not tokens:
        return None
    alt = "|".join(sorted((re.escape(t) for t in tokens), key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alt})(?!\w)", re.IGNORECASE)


def detect_lookup(text, rx):
    if rx is None:
        return []
    return [(m.start(), m.end(), "NAME") for m in rx.finditer(text)]


def detect_patterns_lookup(text, rx):
    return merge(detect_patterns(text) + detect_lookup(text, rx))


# ---------------------------------------------- approach 4: layered, no deps
_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_DW = "|".join(_DIGIT_WORDS)
# a run of >=7 "digit tokens" (words or single digits or digit groups) separated by space , - .
_SPOKEN_TOKEN = rf"(?:(?i:{_DW})|\d+)"
SPOKEN_RUN = re.compile(rf"(?<![\w$])(?:{_SPOKEN_TOKEN}(?:[\s,.\-]+|$)){{2,}}{_SPOKEN_TOKEN}(?!\w)")


def detect_spoken_numbers(text):
    spans = []
    for m in SPOKEN_RUN.finditer(text):
        run = m.group()
        toks = re.findall(rf"(?i:{_DW})|\d+", run)
        n = sum(1 if t.isalpha() else len(t) for t in toks)
        has_word = any(t.isalpha() for t in toks)
        if has_word and n >= 7:            # pure-digit runs are handled by PHONE etc.
            spans.append((m.start(), m.end(), "PHONE"))
    return spans


_SEP_AT = r"\s*[\(\[\{]?\s*\bat\b\s*[\)\]\}]?\s*"
_SEP_DOT = r"(?:\s*[\(\[\{]?\s*\bdot\b\s*[\)\]\}]?\s*|\.)"
OBF_EMAIL = re.compile(
    rf"(?i)\b[\w\-]+(?:{_SEP_DOT}[\w\-]+)*{_SEP_AT}[\w\-]+(?:{_SEP_DOT}[\w\-]+)*?"
    rf"{_SEP_DOT}(?:com|org|net|edu|gov|io|co|in|us|uk)\b"
)


def detect_obfuscated_email(text):
    """'john dot miller at gmail dot com', 'a.b [at] gmail [dot] com' (needs a real TLD)."""
    return [(m.start(), m.end(), "EMAIL") for m in OBF_EMAIL.finditer(text)]


_SUFFIX = (r"(?:St|Street|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|Ln|Lane|Way|Ct|Court|Terrace|Ter|"
           r"Pl|Place|Pkwy|Parkway|Cir|Circle|Hwy|Highway)\b\.?")
_NUMW = r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|hundred|thousand|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
_UNIT = r"(?:(?i:Apt|Apartment|Unit|Suite|Ste|#)\.?\s*[A-Za-z0-9\-]+)"
_STREET_BODY = r"(?:[NSEW]\.?\s+)?(?:[A-Z][\w'\-]*\s+){0,3}?"
ADDRESS = re.compile(
    rf"(?:\b\d{{1,6}}|\b(?i:{_NUMW})(?:\s+(?i:{_NUMW}))*)\s+{_STREET_BODY}{_SUFFIX}"
    rf"(?:,?\s+{_UNIT})?(?:,?\s+[A-Z][a-z]+(?:\s[A-Z][a-z]+)?(?:,?\s+[A-Z]{{2}})?(?:\s+\d{{5}}(?:-\d{{4}})?)?)?"
)
# trailing city/state/zip is only kept when it follows a comma or is a zip/state
POBOX = re.compile(r"(?i)\bP\.?\s?O\.?\s*Box\s+\d+(?:,?\s+[A-Z][a-z]+,?\s+[A-Z]{2}\s+\d{5})?")
UNIT_ADDR = re.compile(r"(?i)\bUnit\s+\d+,\s*\d{1,6}\s+[A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*){0,2}")


def _trim_address(text, m):
    """Drop a trailing capitalised word that is just the start of the next sentence."""
    s, e = m.start(), m.end()
    seg = text[s:e]
    # keep trailing city only when preceded by comma, or ends in state/zip
    mt = re.search(rf"({_SUFFIX}(?:,?\s+{_UNIT})?)(.*)$", seg)
    if mt and mt.group(2):
        tail = mt.group(2)
        if not (tail.lstrip().startswith(",") or re.search(r"\d{5}|\b[A-Z]{2}\b", tail)):
            e = s + mt.end(1)
    return s, e


def detect_addresses(text):
    spans = []
    for m in ADDRESS.finditer(text):
        s, e = _trim_address(text, m)
        spans.append((s, e, "ADDRESS"))
    for m in POBOX.finditer(text):
        spans.append((m.start(), m.end(), "ADDRESS"))
    for m in UNIT_ADDR.finditer(text):
        spans.append((m.start(), m.end(), "ADDRESS"))
    return spans


# ---- names via cue phrases -------------------------------------------------
_PARTICLE = r"(?:de|del|la|las|los|van|von|der|bin|bint|ibn|al|el|da|dos|di|le|ben)"
_CAP = r"[^\W\d_]"                           # any letter (unicode)
_CAPWORD = rf"(?:(?!(?:{{stop}})\b)[A-ZÀ-ÖØ-Þ]{_CAP}*(?:['\-][A-Za-zÀ-ÿ]+)*)"
_NON_NAME = {
    "I", "A", "An", "The", "My", "Mi", "We", "He", "She", "It", "Our", "Your", "Please", "Help",
    "Needed", "Need", "Needs", "Thanks", "Thank", "Hello", "Hi", "Dear", "Urgent", "Medicaid",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "Tempe", "Phoenix", "Mesa", "Arizona", "Walmart", "Amazon",
    "English", "Spanish", "Hindi", "Chinese", "Vietnamese", "Mandarin", "Marathi", "Arabic",
    "Social", "Security", "Rent", "Unemployed", "Blind", "Sick", "Homeless", "New", "Not", "In", "At",
    "On", "For", "To", "And", "But", "Or", "If", "Is", "Am", "Are", "Was", "Looking", "Seeking",
    "Request", "Requesting", "Family", "Elderly", "Senior", "Single", "Student", "Veteran",
    "Muslim", "Hindu", "Christian", "Jewish", "Black", "White", "Asian",
}
_STOPRE = "|".join(sorted(_NON_NAME, key=len, reverse=True))
_NAME_TOK = rf"(?:(?!(?:{_STOPRE})\b)[A-ZÀ-ÖØ-Þ][^\W\d_]*(?:['\-][^\W\d_]+)*|{_PARTICLE}(?=\s+[A-ZÀ-ÖØ-Þ]))"
_NAME = rf"{_NAME_TOK}(?:\s+{_NAME_TOK}){{0,3}}"
# lowercase-tolerant name after a very strong cue ("my name is jose hernandez")
_LOWSTOP = r"(?:and|but|y|e|i|need|needs|necesito|no|am|is|from|who|with|to|for|in|at|on|my|mi|because|so|so\s+i|can|could|please|looking|live|lives|have|has|tengo|vivo|and\s+i)"
_LOWNAME = rf"(?:(?!{_LOWSTOP}\b)[^\W\d_]+(?:\s+(?!{_LOWSTOP}\b)[^\W\d_]+){{0,2}})"

# strong cues - accept lower-case names
_STRONG = re.compile(
    rf"(?i:\b(?:my name is|my name's|me llamo|mi nombre es|name\s*:|nombre\s*:|soy|call me|i am called))\s+(?P<n>{_LOWNAME})"
)
# capitalised-name cues.  STRONG cues introduce a person ("this is X", "my son X", honorifics, sign-offs) so one
# token is enough; WEAK cues ("help X", "call X", "for X") are also ordinary verbs/prepositions, so they need a
# full name (>=2 capitalised tokens) to fire - this was added after a false-positive probe ("Contact Lenses").
_REL = (r"my (?:son|daughter|mother|father|mom|dad|wife|husband|neighbou?r|friend|brother|sister|aunt|uncle|"
        r"grandmother|grandfather|grandson|granddaughter|cousin|nephew|niece|partner|roommate|landlord|caregiver)")
_CUE_STRONG = re.compile(
    rf"(?:(?i:\b(?:this is|i am|i'm|im|thanks,|thank you,|regards,|sincerely,|best,|{_REL}(?:,? named)?|named)(?:\s|(?<=,)))|"
    rf"\bMr\.?\s|\bMrs\.?\s|\bMs\.?\s|\bMiss\s|\bDr\.?\s|\bShri\s|\bSmt\.?\s|\bSr\.?\s|\bSra\.?\s)\s*"
    rf"(?P<n>{_NAME})"
)
_CUE_WEAK = re.compile(
    r"(?i:\b(?:it's|its|here is|ask for|contact|call|text|email|reach|please help|help|from|attn:?|for)\s+)"
    rf"(?P<n>{_NAME_TOK}(?:\s+{_NAME_TOK}){{1,3}})"
)
_TITLE = re.compile(rf"\b(?P<t>(?:Mr|Mrs|Ms|Dr|Shri|Smt|Sr|Sra)\.?|Miss)\s+(?P<n>{_NAME})")
# non-Latin-script cues (Hindi / Marathi / Korean / Chinese / Arabic): "my name is" patterns
_SCRIPT_CUES = [
    re.compile(r"(?:माझे नाव|मेरा नाम|मेरा नाम है|माझं नाव)\s+(?P<n>[\u0900-\u097F]+(?:\s[\u0900-\u097F]+){0,2}?)(?=\s*(?:आहे|है|\.|,|$))"),
    re.compile(r"(?:제 이름은|저는)\s*(?P<n>[\uAC00-\uD7AF]{2,4})(?=입니다|이에요|예요|\s|\.|,|$)"),
    re.compile(r"(?:我叫|我的名字是|我是)\s*(?P<n>[\u4E00-\u9FFF]{2,4})"),
    re.compile(r"(?:اسمي|أنا)\s+(?P<n>[\u0600-\u06FF]+(?:\s[\u0600-\u06FF]+){0,2})"),
]


def detect_name_cues(text):
    spans = []
    for m in _STRONG.finditer(text):
        spans.append((m.start("n"), m.end("n"), "NAME"))
    for rx in (_CUE_STRONG, _CUE_WEAK):
        for m in rx.finditer(text):
            spans.append((m.start("n"), m.end("n"), "NAME"))
    for m in _TITLE.finditer(text):          # include the honorific in the span
        spans.append((m.start("t"), m.end("n"), "NAME"))
    for rx in _SCRIPT_CUES:
        for m in rx.finditer(text):
            spans.append((m.start("n"), m.end("n"), "NAME"))
    return spans


def detect_layered(text, rx_lookup=None):
    spans = detect_patterns(text)
    spans += detect_spoken_numbers(text)
    spans += detect_obfuscated_email(text)
    spans += detect_addresses(text)
    spans += detect_name_cues(text)
    spans += detect_lookup(text, rx_lookup)
    return merge(spans)
