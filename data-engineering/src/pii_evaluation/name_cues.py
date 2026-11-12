"""Context-cue name detection for the supplementary enhanced approach.

Finds capitalised words that follow an introducing phrase such as "my name is",
"my grandmother", "contact" or "soy". This catches names that are not in the
``users`` table (relatives, neighbours) without a language model. It only works
for scripts with letter case and for the English, Spanish and French cues
listed here.
"""

from __future__ import annotations

import re

from src.pii_evaluation.name_lookup import tokenize
from src.pii_evaluation.spans import Span

_RELATIONS = (
    "grandmother|grandfather|grandma|grandpa|mother|father|mom|mum|dad|son|daughter|"
    "wife|husband|brother|sister|aunt|uncle|cousin|neighbou?r|friend|landlord|"
    "caretaker|child|niece|nephew"
)
_RELACIONES = (
    "abuela|abuelo|madre|padre|mamá|papá|hijo|hija|esposa|esposo|hermano|hermana|"
    "vecino|vecina|amigo|amiga|tía|tío"
)
_CUE_RE = re.compile(
    r"\b(?:"
    r"my name is|name is|i am|i'm|i’m|this is|"
    rf"(?:my|his|her|their|our) (?:{_RELATIONS})|"
    r"ask for|ask|contact|speak (?:to|with)|talk to|staying with|living with|lives with|"
    r"soy|me llamo|mi nombre es|"
    rf"(?:mi|su|nuestra|nuestro) (?:{_RELACIONES})|"
    r"je m'appelle|je m’appelle|je suis"
    r")\b[ \t]*[,:]?[ \t]*",
    re.IGNORECASE,
)
_PARTICLES = {"de", "del", "da", "dos", "van", "von", "der", "al", "el", "bin", "ibn", "la", "le"}
_MAX_NAME_TOKENS = 3


def _is_cased_capitalized(token: str) -> bool:
    first = token[0]
    return first.upper() != first.lower() and first.isupper()


def find_cue_name_spans(text: str) -> list[Span]:
    """Return PERSON spans for capitalised words introduced by a cue phrase."""
    tokens = tokenize(text)
    spans = []
    for cue in _CUE_RE.finditer(text):
        following = [token for token in tokens if token[0] >= cue.end()]
        if not following or following[0][0] != cue.end():
            continue
        picked: list[tuple[int, int, str]] = []
        for position, token in enumerate(following):
            if picked and text[picked[-1][1]:token[0]] != " ":
                break
            if _is_cased_capitalized(token[2]):
                picked.append(token)
            elif (picked and token[2].lower() in _PARTICLES
                  and position + 1 < len(following)
                  and _is_cased_capitalized(following[position + 1][2])):
                picked.append(token)
            else:
                break
            if len(picked) == _MAX_NAME_TOKENS:
                break
        if picked:
            spans.append(Span(picked[0][0], picked[-1][1], "PERSON", "name_cues"))
    return spans
