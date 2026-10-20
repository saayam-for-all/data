"""Lambda entry point for the Profanity API (issue #422).

Classifies Help Request content and returns the routing decision for it. The
response is advisory: nothing is written to any table and no request is
mutated. The caller owning the Help Request workflow applies the action.

Accepts either the categorizer's field names (`subject`/`description`) or the
request table's own column names (`req_subj`/`req_desc`), since this sits
directly in front of a request row.
"""
import json

from src.profanity.classifier import classify_content
from src.profanity.severity import route


def parse_body(event):
    """Pull request fields out of an API Gateway event, a plain dict, or nothing."""
    if not isinstance(event, dict):
        return {}

    body = event.get("body", event)
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            return {}

    return body if isinstance(body, dict) else {}


def _field(body, *names):
    """First present, string-valued field among `names`."""
    for name in names:
        value = body.get(name)
        if isinstance(value, str):
            return value
    return ""


def lambda_handler(event, context):
    """Return the profanity severity score and routing decision for a request."""
    try:
        body = parse_body(event)

        subject = _field(body, "subject", "req_subj")
        description = _field(body, "description", "req_desc")

        classification = classify_content(subject, description)
        decision = route(
            classification["severity_score"],
            reasoning=classification["reasoning"],
            error=classification["error"],
        )

        return {"statusCode": 200, "body": decision}

    except Exception as exc:  # noqa: BLE001 - the workflow must always get a decision
        # Fail open but flagged, matching severity.route's handling of an
        # undetermined score: a bug here must not stall every help request.
        message = f"{type(exc).__name__}: {exc}"
        return {
            "statusCode": 500,
            "body": route(None, reasoning=f"Internal error: {message}", error=message),
        }
