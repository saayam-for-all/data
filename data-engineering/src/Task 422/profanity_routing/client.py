"""Adapter for the existing subject/description Profanity API."""

import json
import math
from urllib.parse import urlsplit

import requests

from .domain import Classification, HelpRequest, LABELS, WorkflowError


FLAG_SCORES = {
    "contains_profanity": 1,
    "contains_depressive_content": 2,
    "contains_suicidal_content": 2,
    "contains_threatening_content": 3,
}


def invalid_response() -> WorkflowError:
    """Return a stable error without upstream content or credentials."""
    return WorkflowError(
        "classification_unavailable", "The Profanity API did not return a complete score."
    )


def _check_status(payload: dict) -> None:
    """Catch upstream model failures even when the outer HTTP status is 200."""
    for name in ("statusCode", "status_code"):
        if name in payload:
            status = payload[name]
            if type(status) is not int or not 200 <= status < 300:
                raise invalid_response()
    for name in ("error", "Error", "error_code", "llm_error"):
        if payload.get(name):
            raise invalid_response()
    if payload.get("classification_status", "complete") != "complete":
        raise invalid_response()
    if payload.get("severity_partial", False) is not False:
        raise invalid_response()


def parse_classification(payload: object) -> Classification:
    """Read explicit severity or all four legacy booleans, including Lambda bodies.

    All supplied representations must agree. Multiple flags use the highest
    score while preserving all categories. Partial or failed results are rejected.
    """
    for depth in range(3):
        if not isinstance(payload, dict):
            raise invalid_response()
        _check_status(payload)
        if "body" not in payload:
            break
        if depth == 2 or not ({"statusCode", "status_code"} & payload.keys()):
            raise invalid_response()
        # A wrapper must not hide contradictory classification information.
        if {"severity_score", "severity_scores", *FLAG_SCORES} & payload.keys():
            raise invalid_response()
        payload = payload["body"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError as exc:
                raise invalid_response() from exc

    representations = []
    category_scores = None
    if "severity_score" in payload:
        score = payload["severity_score"]
        if type(score) is not int or score not in range(4):
            raise invalid_response()
        representations.append(score)
    if set(FLAG_SCORES) & payload.keys():
        if any(type(payload.get(flag)) is not bool for flag in FLAG_SCORES):
            raise invalid_response()
        category_scores = {score for flag, score in FLAG_SCORES.items() if payload[flag]}
        representations.append(max(category_scores, default=0))
    if "severity_scores" in payload:
        entries = payload["severity_scores"]
        if not isinstance(entries, list) or len(entries) != 4:
            raise invalid_response()
        flags = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise invalid_response()
            score, flagged = entry.get("score"), entry.get("flagged")
            if (
                type(score) is not int
                or score not in range(4)
                or score in flags
                or type(flagged) is not bool
            ):
                raise invalid_response()
            flags[score] = flagged
        from_entries = {score for score in (1, 2, 3) if flags[score]}
        if flags[0] != (not from_entries):
            raise invalid_response()
        if category_scores is not None and category_scores != from_entries:
            raise invalid_response()
        category_scores = from_entries
        representations.append(max(from_entries, default=0))
    if not representations or len(set(representations)) != 1:
        raise invalid_response()
    score = representations[0]
    if category_scores is None:
        category_scores = {score} if score else set()
    return Classification(score, tuple(LABELS[n] for n in sorted(category_scores)))


class ProfanityClient:
    """Call a configured service with a bounded timeout and no redirects."""

    def __init__(
        self,
        url: str,
        api_key: str = "",
        timeout: float = 10,
        allow_local_http: bool = False,
    ):
        """Validate transport settings before making any network request."""
        try:
            parsed = urlsplit(url)
            local_http = (
                allow_local_http
                and parsed.scheme == "http"
                and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            )
            valid_url = (
                bool(parsed.hostname)
                and (parsed.scheme == "https" or local_http)
                and not parsed.username
                and not parsed.password
                and not parsed.fragment
            )
            parsed.port  # Validate malformed port numbers as well.
            valid_timeout = math.isfinite(timeout) and 0 < timeout <= 60
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid Profanity API configuration.") from exc
        if not valid_url or not valid_timeout:
            raise ValueError("An HTTPS API URL and a timeout in (0, 60] are required.")
        if "\r" in api_key or "\n" in api_key:
            raise ValueError("Invalid API key header.")
        self.url = url
        self.api_key = api_key
        self.timeout = timeout

    def classify(self, submission: HelpRequest) -> Classification:
        """Send only subject and description, matching the existing Lambda."""
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        try:
            with requests.post(
                self.url,
                json={"subject": submission.subject, "description": submission.description},
                headers=headers,
                timeout=self.timeout,
                allow_redirects=False,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise invalid_response()
                payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise invalid_response() from exc
        return parse_classification(payload)
