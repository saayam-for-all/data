"""Manual smoke run for the Profanity API routing contract (issue #422).

Mirrors the placement and style of `test_categorizer.py`: a script, not a pytest
module, so CI's `pytest tests/` does not pick it up.

Unlike `test_categorizer.py`, this runs with no OPENAI_API_KEY and without the
`openai` package: it exercises the routing contract directly with injected
scores, which is the part of issue #422 that is actually verifiable here. The
live gpt-3.5-turbo path is only attempted if a key is present.

    python test_profanity.py
"""
import json
import sys

sys.path.insert(0, '.')

from src.profanity.classifier import OPENAI_AVAILABLE, classify_content
from src.profanity.handler import lambda_handler
from src.profanity.severity import SEVERITY_SCALE, route

SEPARATOR = "-" * 72


def show_scale():
    print("SEVERITY SCALE AND ROUTING CONTRACT")
    print(SEPARATOR)
    print(f"{'score':<7}{'label':<10}{'action':<10}{'allowed':<10}{'review':<8}")
    print(SEPARATOR)
    for score in sorted(SEVERITY_SCALE):
        decision = route(score)
        print(
            f"{score:<7}{decision['severity_label']:<10}{decision['action']:<10}"
            f"{str(decision['allowed']):<10}{str(decision['requires_review']):<8}"
        )
    undetermined = route(None)
    print(
        f"{'None':<7}{undetermined['severity_label']:<10}{undetermined['action']:<10}"
        f"{str(undetermined['allowed']):<10}{str(undetermined['requires_review']):<8}"
    )
    print()


def show_routing_decisions():
    """Every score the contract accepts, plus the values it must reject."""
    print("ROUTING DECISIONS (score injected directly, no model call)")
    print(SEPARATOR)
    cases = [
        ("clean request", 0, "no profanity in subject or description"),
        ("mild profanity", 1, "one mild expletive used in frustration"),
        ("severe profanity", 2, "repeated abusive language aimed at volunteers"),
        ("extreme content", 3, "slur and explicit threat"),
    ]
    for label, score, reasoning in cases:
        print(f"\n[{label}]")
        print(json.dumps(route(score, reasoning=reasoning), indent=2))

    print("\n[rejected scores -> fail open but flagged]")
    for bad in (None, 7, -1, 2.5, "high", True):
        decision = route(bad, reasoning="classifier returned an unusable value")
        print(
            f"  {str(bad):<8} -> score={str(decision['severity_score']):<5} "
            f"label={decision['severity_label']:<8} action={decision['action']:<8} "
            f"allowed={decision['allowed']}"
        )
    print()


def show_handler_without_key():
    """What the deployed handler does when the model is unreachable."""
    print("HANDLER WITH NO OPENAI KEY (degraded path)")
    print(SEPARATOR)
    events = [
        ("empty content", {}),
        ("categorizer field names", {"subject": "Need food", "description": "We have not eaten"}),
        ("request table column names", {"req_subj": "Need a ride", "req_desc": "To a clinic"}),
        ("JSON string body", {"body": json.dumps({"subject": "Help", "description": "please"})}),
    ]
    for label, event in events:
        response = lambda_handler(event, None)
        print(f"\n[{label}] event: {json.dumps(event)}")
        print(json.dumps({"statusCode": response["statusCode"], "body": response["body"]}, indent=2))
    print()


def show_live_classification():
    print("LIVE CLASSIFICATION")
    print(SEPARATOR)
    if not OPENAI_AVAILABLE:
        print("SKIPPED: the 'openai' package is not installed.")
        print("Install it with: pip install -r src/profanity/requirements.txt")
        print()
        return

    samples = [
        ("clean hardship request", "Need food", "My family has not eaten in two days."),
        ("distress, not profanity", "Feeling unsafe", "My partner has been violent and I need shelter."),
        ("mild profanity", "This is a mess", "I am so damn tired of being ignored by everyone."),
    ]
    for label, subject, description in samples:
        result = classify_content(subject, description)
        print(f"\n[{label}]")
        print(json.dumps(route(result["severity_score"], result["reasoning"], result["error"]), indent=2))
    print()


if __name__ == "__main__":
    show_scale()
    show_routing_decisions()
    show_handler_without_key()
    show_live_classification()
