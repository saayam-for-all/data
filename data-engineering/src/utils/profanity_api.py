import json
import os

import requests


class ProfanityAPIError(RuntimeError):
    pass


def severity_score(payload: dict) -> int:
    for _ in range(2):
        if not isinstance(payload, dict):
            raise ProfanityAPIError("Invalid moderation response")
        for field in ("statusCode", "status_code"):
            if field in payload:
                status = payload[field]
                if type(status) is not int or not 200 <= status < 300:
                    raise ProfanityAPIError("Moderation service reported a failure")
        if payload.get("Error") or payload.get("error"):
            raise ProfanityAPIError("Moderation service reported a failure")
        if "body" not in payload:
            break
        body = payload["body"]
        try:
            payload = json.loads(body) if isinstance(body, str) else body
        except (ValueError, TypeError, RecursionError) as exc:
            raise ProfanityAPIError("Invalid moderation response body") from exc
    else:
        raise ProfanityAPIError("Unexpected nested moderation response")

    score = None
    if "severity_score" in payload:
        score = payload["severity_score"]
        if type(score) is not int or score not in range(4):
            raise ProfanityAPIError("Severity score must be an integer from 0 to 3")
    fields = (
        "contains_profanity",
        "contains_depressive_content",
        "contains_suicidal_content",
        "contains_threatening_content",
    )
    if score is not None and not any(field in payload for field in fields):
        return score
    if any(type(payload.get(field)) is not bool for field in fields):
        raise ProfanityAPIError("Missing or invalid moderation flags")
    if payload["contains_threatening_content"]:
        category = 3
    elif payload["contains_depressive_content"] or payload["contains_suicidal_content"]:
        category = 2
    else:
        category = int(payload["contains_profanity"])
    if score is not None and score != category:
        raise ProfanityAPIError("Severity score conflicts with moderation flags")
    return category


def evaluate_help_request(subject: str, description: str) -> int:
    if any(not isinstance(value, str) or not value.strip()
           for value in (subject, description)):
        raise ValueError("subject and description must be non-empty strings")
    url = os.getenv("PROFANITY_API_URL", "").strip()
    if not url.startswith("https://"):
        raise ProfanityAPIError("PROFANITY_API_URL must be configured with HTTPS")
    headers = {"Accept": "application/json"}
    api_key = os.getenv("PROFANITY_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    try:
        response = requests.post(
            url,
            json={"subject": subject, "description": description},
            headers=headers,
            timeout=(3.05, 15),
            allow_redirects=False,
        )
        if not 200 <= response.status_code < 300:
            raise ProfanityAPIError("Moderation service returned an unsuccessful status")
        payload = response.json()
    except (requests.RequestException, ValueError, RecursionError) as exc:
        raise ProfanityAPIError("Unable to evaluate help request") from exc
    return severity_score(payload)
