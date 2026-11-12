"""Profanity API integration and severity-based routing."""

import json
import os
from typing import Any

import requests


SEVERITY_REASONS = {
    0: "Good Request",
    1: "Foul Language",
    2: "Depressive or Suicidal Content",
    3: "Threatening Content",
}


class ProfanityAPIError(RuntimeError):
    """Raised when the Profanity API cannot return a valid classification."""


def _unwrap_response(payload: Any) -> dict:
    """Unwrap an API Gateway/Lambda response and return its JSON body."""
    for _ in range(2):
        if not isinstance(payload, dict):
            raise ProfanityAPIError(
                "The Profanity API response must be a JSON object."
            )

        status_code = payload.get("statusCode", payload.get("status_code"))
        if status_code is not None:
            if (
                type(status_code) is not int
                or not 200 <= status_code < 300
            ):
                raise ProfanityAPIError(
                    "The Profanity API reported a failure."
                )

        if payload.get("error") or payload.get("Error"):
            raise ProfanityAPIError(
                "The Profanity API reported a failure."
            )

        if "body" not in payload:
            return payload

        body = payload["body"]

        if isinstance(body, str):
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise ProfanityAPIError(
                    "The Profanity API returned an invalid response body."
                ) from exc
        else:
            payload = body

    raise ProfanityAPIError(
        "The Profanity API returned an unexpectedly nested response."
    )


def _score_from_flags(payload: dict) -> int:
    """Calculate severity using the existing category flags."""
    fields = (
        "contains_profanity",
        "contains_depressive_content",
        "contains_suicidal_content",
        "contains_threatening_content",
    )

    if not any(field in payload for field in fields):
        raise ProfanityAPIError(
            "The Profanity API response contains no severity score."
        )

    if any(type(payload.get(field)) is not bool for field in fields):
        raise ProfanityAPIError(
            "The Profanity API returned missing or invalid category flags."
        )

    if payload["contains_threatening_content"]:
        return 3

    if (
        payload["contains_depressive_content"]
        or payload["contains_suicidal_content"]
    ):
        return 2

    if payload["contains_profanity"]:
        return 1

    return 0


def _score_from_entries(entries: Any) -> int:
    """Return the highest flagged score from a severity_scores list."""
    if not isinstance(entries, list) or not entries:
        raise ProfanityAPIError(
            "severity_scores must be a non-empty list."
        )

    flagged_scores = []

    for entry in entries:
        if not isinstance(entry, dict):
            raise ProfanityAPIError(
                "Each severity entry must be a JSON object."
            )

        score = entry.get("score")
        flagged = entry.get("flagged")

        if type(score) is not int or score not in SEVERITY_REASONS:
            raise ProfanityAPIError(
                "The Profanity API returned an invalid severity score."
            )

        if type(flagged) is not bool:
            raise ProfanityAPIError(
                "The Profanity API returned an invalid flagged value."
            )

        if flagged:
            flagged_scores.append(score)

    return max(flagged_scores, default=0)


def parse_profanity_response(payload: Any) -> int:
    """Extract and validate a severity score from the API response."""
    result = _unwrap_response(payload)

    if "severity_scores" in result:
        return _score_from_entries(result["severity_scores"])

    explicit_score = None

    for field in (
        "severity_score",
        "severityScore",
        "classification_score",
        "classificationScore",
        "score",
    ):
        if field in result:
            explicit_score = result[field]
            break

    if explicit_score is not None:
        if (
            type(explicit_score) is not int
            or explicit_score not in SEVERITY_REASONS
        ):
            raise ProfanityAPIError(
                "Severity score must be an integer from 0 to 3."
            )

        flag_fields = (
            "contains_profanity",
            "contains_depressive_content",
            "contains_suicidal_content",
            "contains_threatening_content",
        )

        if any(field in result for field in flag_fields):
            flag_score = _score_from_flags(result)

            if explicit_score != flag_score:
                raise ProfanityAPIError(
                    "Severity score conflicts with category flags."
                )

        return explicit_score

    return _score_from_flags(result)


def call_profanity_api(subject: str, description: str) -> int:
    """Send a Help Request to the configured Profanity API."""
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("subject must be a non-empty string.")

    if not isinstance(description, str) or not description.strip():
        raise ValueError("description must be a non-empty string.")

    endpoint = os.environ.get("PROFANITY_API_URL", "").strip()

    if not endpoint.startswith("https://"):
        raise ProfanityAPIError(
            "PROFANITY_API_URL must contain a valid HTTPS endpoint."
        )

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    api_key = os.environ.get("PROFANITY_API_KEY", "").strip()
    if api_key:
        headers["x-api-key"] = api_key

    try:
        response = requests.post(
            endpoint,
            json={
                "subject": subject.strip(),
                "description": description.strip(),
            },
            headers=headers,
            timeout=(3.05, 15),
        )

        response.raise_for_status()
        payload = response.json()

    except (requests.RequestException, ValueError) as exc:
        raise ProfanityAPIError(
            "Unable to evaluate the Help Request."
        ) from exc

    return parse_profanity_response(payload)


def get_routing_decision(score: int) -> dict:
    """Return the workflow destination for a severity score."""
    if type(score) is not int or score not in SEVERITY_REASONS:
        raise ValueError("Severity score must be an integer from 0 to 3.")

    return {
        "severity_score": score,
        "is_flagged": score > 0,
        "reason": SEVERITY_REASONS[score],
        "destination": (
            "active_matching" if score == 0 else "fraud_requests"
        ),
    }
