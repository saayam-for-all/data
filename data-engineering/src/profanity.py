"""Client and response validation for the profanity classification API."""

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
    """Raised when the classification API fails or returns invalid data."""


def call_profanity_api(subject, description):
    """Call the configured classifier with help-request text."""
    endpoint = os.environ.get("PROFANITY_API_URL", "").strip()
    if not endpoint.startswith("https://"):
        raise ProfanityAPIError("PROFANITY_API_URL must be an HTTPS URL")

    text = " ".join((subject.strip(), description.strip()))
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    api_key = os.environ.get("PROFANITY_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    api_request = urllib.request.Request(
        endpoint,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(api_request, timeout=10) as response:
            if not 200 <= response.status < 300:
                raise ProfanityAPIError(
                    "The classification API returned an unsuccessful status"
                )
            try:
                payload = json.loads(response.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProfanityAPIError(
                    "The classification API returned invalid JSON"
                ) from exc
    except urllib.error.HTTPError as exc:
        raise ProfanityAPIError(
            "The classification API returned an unsuccessful status"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProfanityAPIError(
            "The classification API could not be reached"
        ) from exc

    return payload


def parse_profanity_response(payload):
    """Validate classifier output and return its highest flagged score."""
    if not isinstance(payload, dict):
        raise ProfanityAPIError("Classifier response must be a JSON object")

    scores = payload.get("severity_scores")
    if scores is not None:
        if not isinstance(scores, list) or not scores:
            raise ProfanityAPIError(
                "Classifier severity_scores must be a non-empty list"
            )

        flagged = []
        for item in scores:
            if not isinstance(item, dict):
                raise ProfanityAPIError(
                    "Each classifier severity entry must be an object"
                )
            score = item.get("score")
            category = item.get("category")
            is_flagged = item.get("flagged")
            if type(score) is not int or score not in SEVERITY_REASONS:
                raise ProfanityAPIError("Classifier returned an invalid score")
            if not isinstance(category, str) or not category.strip():
                raise ProfanityAPIError(
                    "Classifier returned an invalid category"
                )
            if type(is_flagged) is not bool:
                raise ProfanityAPIError(
                    "Classifier returned an invalid flagged value"
                )
            if is_flagged and score > 0:
                flagged.append({
                    "score": score,
                    "category": category.strip(),
                })

        return {
            "severity_score": max(
                (item["score"] for item in flagged),
                default=0,
            ),
            "is_flagged": bool(flagged),
            "flagged_categories": flagged,
        }

    result = payload.get("result")
    response_data = {**payload, **result} if isinstance(result, dict) else payload
    score = next(
        (
            response_data[field]
            for field in (
                "severity_score",
                "severityScore",
                "classification_score",
                "classificationScore",
                "score",
            )
            if field in response_data
        ),
        None,
    )
    if type(score) is not int or score not in SEVERITY_REASONS:
        raise ProfanityAPIError(
            "Classifier response contains no valid severity score"
        )

    flagged_categories = []
    category = response_data.get("category")
    if score > 0 and isinstance(category, str) and category.strip():
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
    """Return the destination and reason for a valid severity score."""
    if type(score) is not int or score not in SEVERITY_REASONS:
        raise ValueError("Severity score must be an integer from 0 to 3")

    return {
        "severity_score": score,
        "destination": "active_matching" if score == 0 else "fraud_requests",
        "reason": SEVERITY_REASONS[score],
    }
