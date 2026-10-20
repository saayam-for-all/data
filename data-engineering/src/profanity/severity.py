"""Severity scale and routing contract for the Profanity API (issue #422).

This module is the contract the rest of the Help Request workflow codes against.
It is deliberately pure: no network, no database, no configuration. Given a
severity score it returns the routing decision, and nothing else in the request
pipeline needs to know how that score was produced.

Issue #422 states the Profanity API returns a classification score of 0, 1, 2 or
3 but does not define what those values mean or where each one routes. The scale
below mirrors `database/lookup_tables/request_priority.csv`, which already uses
an identical 0-3 ordinal (LOW/MEDIUM/HIGH/CRITICAL), so the two read
consistently to anyone working in this codebase.

Routing is advisory. This module returns a decision; it never writes to a table
and never mutates a request. The caller owning the Help Request workflow applies
the action.
"""

SEVERITY_CLEAN = 0
SEVERITY_MILD = 1
SEVERITY_SEVERE = 2
SEVERITY_EXTREME = 3

ACTION_PROCEED = "proceed"
ACTION_FLAG = "flag"
ACTION_HOLD = "hold"
ACTION_BLOCK = "block"

UNKNOWN_LABEL = "UNKNOWN"

# allowed          - may the request enter the active volunteer-matching workflow
# requires_review  - does a human need to look at it
SEVERITY_SCALE = {
    SEVERITY_CLEAN: {
        "severity_label": "CLEAN",
        "action": ACTION_PROCEED,
        "allowed": True,
        "requires_review": False,
        "description": "No profanity detected. Request proceeds to volunteer matching.",
    },
    SEVERITY_MILD: {
        "severity_label": "MILD",
        "action": ACTION_FLAG,
        "allowed": True,
        "requires_review": True,
        "description": "Mild or incidental profanity. Request proceeds but is flagged for review.",
    },
    SEVERITY_SEVERE: {
        "severity_label": "SEVERE",
        "action": ACTION_HOLD,
        "allowed": False,
        "requires_review": True,
        "description": "Severe profanity or abuse. Request is withheld pending human review.",
    },
    SEVERITY_EXTREME: {
        "severity_label": "EXTREME",
        "action": ACTION_BLOCK,
        "allowed": False,
        "requires_review": False,
        "description": "Hate speech, threats or sexual content. Request is blocked outright.",
    },
}

VALID_SCORES = frozenset(SEVERITY_SCALE)

# What an unusable score routes to. See fail-open rationale in route().
UNKNOWN_ROUTE = {
    "severity_label": UNKNOWN_LABEL,
    "action": ACTION_FLAG,
    "allowed": True,
    "requires_review": True,
    "description": "Severity could not be determined. Request proceeds but is flagged for review.",
}


def normalize_score(score):
    """Coerce a raw score onto the 0-3 scale, or None if it cannot be trusted.

    Accepts ints and whole-valued floats/strings, since an LLM may return 2, 2.0
    or "2" for the same answer. Anything else - None, out of range, fractional,
    non-numeric - is rejected rather than clamped: a score this module cannot
    place is a classification failure, not a 0.
    """
    if isinstance(score, bool):
        return None
    if isinstance(score, int):
        return score if score in VALID_SCORES else None
    if isinstance(score, float):
        return int(score) if score.is_integer() and int(score) in VALID_SCORES else None
    if isinstance(score, str):
        text = score.strip()
        try:
            value = float(text)
        except ValueError:
            return None
        return int(value) if value.is_integer() and int(value) in VALID_SCORES else None
    return None


def route(score, reasoning="", error=None):
    """Map a severity score onto a routing decision.

    An unusable score (None, out of range, non-numeric) routes to `flag`:
    allowed through, but marked for human review.

    That is a deliberate fail-open. Saayam help requests can be time-sensitive,
    so treating an upstream classifier outage as SEVERE would stall every
    incoming request until the outage cleared - worse than letting a request
    through with a review marker on it. The returned `severity_score` is None in
    that case, so a caller can always tell a real CLEAN verdict from an
    undetermined one rather than reading a fabricated 0.
    """
    normalized = normalize_score(score)

    if normalized is None:
        decision = dict(UNKNOWN_ROUTE)
        decision["severity_score"] = None
    else:
        decision = dict(SEVERITY_SCALE[normalized])
        decision["severity_score"] = normalized

    decision["reasoning"] = reasoning or ""
    decision["error"] = error

    return decision
