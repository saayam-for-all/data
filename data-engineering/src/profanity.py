"""Profanity API integration and severity-based routing for Help Requests."""

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
    """Raised when the profanity classifier returns an unusable response."""


def call_profanity_api(subject, description, *, opener=None):
    """Send Help Request content to the configured Profanity API."""

    endpoint = os.environ.get("PROFANITY_API_URL", "").strip()

    if not endpoint:
        raise ProfanityAPIError(
            "PROFANITY_API_URL must contain the classifier endpoint"
        )

    if not endpoint.startswith("https://"):
        raise ProfanityAPIError("Profanity API endpoint must use HTTPS")

    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("A non-empty subject is required")

    if not isinstance(description, str) or not description.strip():
        raise ValueError("A non-empty description is required")

    text = f"{subject.strip()} {description.strip()}"

    body = json.dumps({
        "text": text
    }).encode("utf-8")

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    api_key = os.environ.get("PROFANITY_API_KEY", "").strip()

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request_object = urllib.request.Request(
        endpoint,
        data=body,
        headers=headers,
        method="POST",
    )

    send = opener or urllib.request.urlopen

    try:
        response = send(request_object, timeout=10)

        try:
            status = getattr(response, "status", 200)

            if type(status) is not int or not 200 <= status < 300:
                raise ProfanityAPIError(
                    "Profanity API returned an unsuccessful HTTP status"
                )

            try:
                return json.loads(
                    response.read().decode("utf-8")
                )
            except (UnicodeDecodeError, ValueError) as exc:
                raise ProfanityAPIError(
                    "Profanity API returned invalid JSON"
                ) from exc

        finally:
            close = getattr(response, "close", None)

            if callable(close):
                close()

    except urllib.error.URLError as exc:
        raise ProfanityAPIError(
            "Profanity API could not be reached"
        ) from exc

    except TimeoutError as exc:
        raise ProfanityAPIError(
            "Profanity API request timed out"
        ) from exc

    except OSError as exc:
        raise ProfanityAPIError(
            "Profanity API request failed"
        ) from exc


def parse_profanity_response(payload):
    """Validate the Profanity API response and return its severity."""

    if not isinstance(payload, dict):
        raise ProfanityAPIError(
            "Profanity API response must be a JSON object"
        )

    # Existing API may return multiple category scores.
    severity_scores = payload.get("severity_scores")

    if severity_scores is not None:

        if not isinstance(severity_scores, list) or not severity_scores:
            raise ProfanityAPIError(
                "severity_scores must be a non-empty list"
            )

        flagged_categories = []

        for item in severity_scores:

            if not isinstance(item, dict):
                raise ProfanityAPIError(
                    "Each severity entry must be a JSON object"
                )

            score = item.get("score")
            category = item.get("category")
            flagged = item.get("flagged")

            if type(score) is not int or score not in SEVERITY_REASONS:
                raise ProfanityAPIError(
                    "Profanity API returned an invalid severity score"
                )

            if not isinstance(category, str) or not category.strip():
                raise ProfanityAPIError(
                    "Profanity API returned a missing category"
                )

            if type(flagged) is not bool:
                raise ProfanityAPIError(
                    "Profanity API returned an invalid flagged value"
                )

            if flagged and score > 0:
                flagged_categories.append({
                    "score": score,
                    "category": category.strip(),
                })

        severity_score = max(
            (item["score"] for item in flagged_categories),
            default=0,
        )

        return {
            "severity_score": severity_score,
            "is_flagged": bool(flagged_categories),
            "flagged_categories": flagged_categories,
        }

    # Also support APIs returning one score.
    result = payload.get("result")

    if isinstance(result, dict):
        response_data = {**payload, **result}
    else:
        response_data = payload

    score = None

    possible_fields = (
        "severity_score",
        "severityScore",
        "classification_score",
        "classificationScore",
        "score",
    )

    for field in possible_fields:
        if field in response_data:
            score = response_data[field]
            break

    if type(score) is not int or score not in SEVERITY_REASONS:
        raise ProfanityAPIError(
            "Profanity API response contains no valid severity score"
        )

    flagged_categories = []

    if score > 0:
        category = response_data.get("category")

        if isinstance(category, str) and category.strip():
            flagged_categories.append({
                "score": score,
                "category": category.strip(),
            })

    return {
        "severity_score": score,
        "is_flagged": score > 0,
        "flagged_categories": flagged_categories,
    }


def get_routing_decision(score):
    """Return the Help Request destination for severity score 0-3."""

    if type(score) is not int or score not in SEVERITY_REASONS:
        raise ValueError(
            "Severity score must be an integer from 0 to 3"
        )

    return {
        "severity_score": score,
        "destination": (
            "active_matching"
            if score == 0
            else "fraud_requests"
        ),
        "reason": SEVERITY_REASONS[score],
    }
