"""Severity classification for Help Request text (issue #422).

Maps request text onto the `sentiment_codes` taxonomy that is already seeded
in the Virginia database:

    0  Good Request             clean, no harmful or negative content
    1  Foul Language            offensive or foul language
    2  Depressive or Suicidal   depressive or suicidal language
    3  Threatening              threatening language or weapon references

Those four codes and their meanings come from the `sentiment_codes` seed data,
not from a profanity-intensity ladder invented here. That distinction drives
the whole design: code 2 is a *distress* signal, not "moderate profanity", so
it must never be handled as a language-cleanliness problem. See routing.py.

Limits worth knowing before anyone leans on this:

- Lexicon matching only. It does not understand negation, quotation, irony or
  context ("my landlord threatened to kill my dog" scores as Threatening).
- No obfuscation handling beyond case, punctuation and stretched letters
  ("fuuuck"). Deliberate evasion ("f.u.c.k", "phuck") will pass as clean.
- The distress lexicon will miss distress expressed in words nobody put on a
  list. It is a routing aid, not a safety net, and must not be the only thing
  standing between a person in crisis and a human being.

The upgrade path is the DB-backed `profane_words` lexicon or a trained
classifier; the public function signature here does not change when that lands.
"""

import re

# --- sentiment_codes.code values -----------------------------------------

SAFE = 0
FOUL_LANGUAGE = 1
DEPRESSIVE_OR_SUICIDAL = 2
THREATENING = 3

# Fallback labels only. The authoritative label/description live in the
# sentiment_codes table and are read from there by routing.resolve_code_label;
# these exist so classify() is useful without a database connection.
CODE_LABELS = {
    SAFE: "Good Request",
    FOUL_LANGUAGE: "Foul Language",
    DEPRESSIVE_OR_SUICIDAL: "Depressive or Suicidal",
    THREATENING: "Threatening",
}

# --- Lexicons -------------------------------------------------------------
# Multi-word entries are matched as phrases. Distress is scanned first and its
# matches are removed from the text before the threat scan, so "kill myself"
# is read as distress rather than as a threat against someone else.

DISTRESS_TERMS = [
    "kill myself", "killing myself", "kill me", "end my life",
    "ending my life", "end it all", "take my own life", "want to die",
    "wanna die", "wish i was dead", "wish i were dead", "better off dead",
    "no reason to live", "nothing to live for", "cant go on", "can t go on",
    "cannot go on", "give up on life", "suicide", "suicidal",
    "self harm", "self harming", "harm myself", "hurt myself",
    "cutting myself", "overdose", "hopeless", "worthless",
    "no way out", "tired of living", "dont want to live",
    "do not want to live", "don t want to live",
]

THREAT_TERMS = [
    "kill you", "kill him", "kill her", "kill them", "kill your",
    "murder you", "shoot you", "shoot up", "stab you", "beat you up",
    "burn your house", "burn down", "blow up", "bomb", "gun", "guns",
    "rifle", "shotgun", "pistol", "firearm", "knife", "machete",
    "explosive", "grenade", "hunt you down", "find you and",
    "make you pay", "you will regret", "youll regret", "watch your back",
    "i will hurt", "going to hurt you", "gonna hurt you", "break your legs",
    "slit your", "rape", "lynch", "massacre", "terrorist", "behead",
    "death threat", "wipe out your", "destroy you",
]

FOUL_TERMS = [
    "ass", "asses", "asshole", "assholes", "bastard", "bastards", "bitch",
    "bitches", "bollocks", "bullshit", "crap", "cunt", "damn", "dick",
    "dickhead", "dumbass", "dyke", "fag", "faggot", "fuck", "fucked",
    "fucker", "fuckers", "fucking", "goddamn", "hell", "jackass",
    "motherfucker", "motherfucking", "nigga", "nigger", "piss", "pissed",
    "prick", "pussy", "retard", "retarded", "shit", "shite", "shitty",
    "slut", "twat", "wanker", "whore",
]

# Precedence when more than one category matches. Threatening wins because it
# must block regardless of what else is present; distress outranks foul
# language so that a distressed request is never routed as a profanity
# problem. Every match is still reported in `matched_codes`.
PRECEDENCE = [THREATENING, DEPRESSIVE_OR_SUICIDAL, FOUL_LANGUAGE]

_LEXICONS = {
    DEPRESSIVE_OR_SUICIDAL: DISTRESS_TERMS,
    THREATENING: THREAT_TERMS,
    FOUL_LANGUAGE: FOUL_TERMS,
}

_REPEATED_CHAR = re.compile(r"(.)\1{2,}")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalize(text):
    """Lowercase, flatten punctuation to spaces, and unstretch letters.

    "F.U.C.K!!"   -> "f u c k"   (not matched - see module docstring)
    "Fuuuuucking" -> "fucking"
    """
    if not text:
        return ""
    lowered = text.lower()
    collapsed = _REPEATED_CHAR.sub(r"\1", lowered)
    return _NON_WORD.sub(" ", collapsed).strip()


def _compile(terms):
    """One alternation per lexicon, longest terms first so phrases win."""
    ordered = sorted(terms, key=len, reverse=True)
    pattern = "|".join(re.escape(term) for term in ordered)
    return re.compile(r"\b(?:" + pattern + r")\b")


_PATTERNS = {code: _compile(terms) for code, terms in _LEXICONS.items()}


def _take_matches(pattern, text):
    """Return (matched terms, text with those spans blanked out)."""
    matches = []
    spans = []
    for match in pattern.finditer(text):
        matches.append(match.group(0))
        spans.append(match.span())

    if not spans:
        return [], text

    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            chars[i] = " "
    return matches, "".join(chars)


def classify(text):
    """Classify request text into a sentiment_codes value.

    Returns a dict:
        severity_score   int    the sentiment_codes.code to record (0-3)
        severity_label   str    fallback label for that code
        matched_codes    list   every category that matched, highest first
        matches          dict   {code: [matched terms]} for the audit trail
        contains_profanity bool kept for callers of the previous API shape
    """
    normalized = normalize(text)

    matches = {}
    remaining = normalized

    # Distress first, then its spans are withheld from the threat scan.
    for code in (DEPRESSIVE_OR_SUICIDAL, THREATENING, FOUL_LANGUAGE):
        found, remaining = _take_matches(_PATTERNS[code], remaining)
        if found:
            matches[code] = sorted(set(found))

    matched_codes = [code for code in PRECEDENCE if code in matches]
    score = matched_codes[0] if matched_codes else SAFE

    return {
        "severity_score": score,
        "severity_label": CODE_LABELS[score],
        "matched_codes": matched_codes,
        "matches": matches,
        "contains_profanity": FOUL_LANGUAGE in matches,
    }


def classify_request(subject, description):
    """Classify a help request from its subject and description together."""
    combined = " ".join(part for part in (subject, description) if part)
    result = classify(combined)
    result["evaluated_fields"] = [
        name for name, value in (("subject", subject),
                                 ("description", description)) if value
    ]
    return result
