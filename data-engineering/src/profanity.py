
"""Severity validation and routing decisions for Help Requests."""

import json
import os
import urllib.error
import urllib.request

SEVERITY_REASONS = {
    0: "Good Request",
    1: "Foul Language",
    2: "Depressive or Suicidal Content",
    3: "Threatening Content",
}


class ProfanityAPIError(RuntimeError):
    """Raised when the classifier cannot provide a usable response."""


def call_profanity_api(subject, description, *, opener=None):
    """Submit a Help Request to the configured profanity classifier."""
    endpoint = os.environ.get("PROFANITY_API_URL", "").strip()

    if not endpoint:
        raise ProfanityAPIError(
            "PROFANITY_API_URL must contain the full classifier endpoint"
        )

    if not endpoint.startswith("https://"):
        raise ProfanityAPIError("The classifier endpoint must use HTTPS")

    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("A non-empty subject is required")

    if not isinstance(description, str) or not description.strip():
        raise ValueError("A non-empty description is required")

    text = " ".join((subject.strip(), description.strip()))
    body = json.dumps({"text": text}).encode("utf-8")

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    api_key = os.environ.get("PROFANITY_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        endpoint,
        data=body,
        headers=headers,
        method="POST",
    )

    send = opener or urllib.request.urlopen

    try:
        response = send(request, timeout=10)
        try:
            status = getattr(response, "status", 200)

            if type(status) is not int or not 200 <= status < 300:
                raise ProfanityAPIError(
                    "The classifier returned an unsuccessful HTTP status"
                )

            try:
                return json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ProfanityAPIError(
                    "The classifier returned invalid JSON"
                ) from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    except urllib.error.URLError as exc:
        raise ProfanityAPIError(
            "The classifier could not be reached"
        ) from exc
    except TimeoutError as exc:
        raise ProfanityAPIError(
            "The classifier request timed out"
        ) from exc
    except OSError as exc:
        raise ProfanityAPIError(
            "The classifier request failed"
        ) from exc

def parse_profanity_response(payload):
    """Validate classifier output and extract its severity score."""
    if not isinstance(payload, dict):
        raise ProfanityAPIError(
            "Classifier response must be a JSON object"
        )

    # Preserve support for the existing multi-category response format.
    scores = payload.get("severity_scores")

    if scores is not None:
        if not isinstance(scores, list) or not scores:
            raise ProfanityAPIError(
                "Classifier severity_scores must be a non-empty list"
            )

        flagged_scores = []

        for item in scores:
            if not isinstance(item, dict):
                raise ProfanityAPIError(
                    "Each severity entry must be a JSON object"
                )

            score = item.get("score")
            category = item.get("category")
            flagged = item.get("flagged")

            if type(score) is not int or score not in SEVERITY_REASONS:
                raise ProfanityAPIError(
                    "Classifier returned an invalid score"
                )

            if not isinstance(category, str) or not category.strip():
                raise ProfanityAPIError(
                    "Classifier returned a missing category"
                )

            if type(flagged) is not bool:
                raise ProfanityAPIError(
                    "Classifier returned an invalid flagged value"
                )

            if flagged and score > 0:
                flagged_scores.append({
                    "score": score,
                    "category": category.strip(),
                })

        highest_score = max(
            (item["score"] for item in flagged_scores),
            default=0,
        )

        return {
            "severity_score": highest_score,
            "is_flagged": bool(flagged_scores),
            "flagged_categories": flagged_scores,
        }

    # Support single-score response formats.
    result = payload.get("result")
    if isinstance(result, dict):
        response_data = {**payload, **result}
    else:
        response_data = payload

    score = None
    score_fields = (
        "severity_score",
        "severityScore",
        "classification_score",
        "classificationScore",
        "score",
    )

    for field in score_fields:
        if field in response_data:
            score = response_data[field]
            break

    if type(score) is not int or score not in SEVERITY_REASONS:
        raise ProfanityAPIError(
            "Classifier response contains no valid severity score"
        )

    is_flagged = score > 0
    categories = []

    if is_flagged:
        category = response_data.get("category")
        if isinstance(category, str) and category.strip():
            categories.append({
                "score": score,
                "category": category.strip(),
            })

    return {
        "severity_score": score,
        "is_flagged": is_flagged,
        "flagged_categories": categories,
    }

def get_routing_decision(score):
    """Return the destination and reason for a severity score."""
    if type(score) is not int or score not in SEVERITY_REASONS:
        raise ValueError("Severity score must be an integer from 0 to 3")

    reason = SEVERITY_REASONS[score]

    if score == 0:
        destination = "active_matching"
    else:
        destination = "fraud_requests"

    return {
        "severity_score": score,
        "destination": destination,
        "reason": reason,
    }