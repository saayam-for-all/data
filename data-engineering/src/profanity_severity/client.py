"""HTTP client for the deployed Profanity API."""
import os
from typing import Any

import requests

from src.profanity_severity.scoring import ScoringError

DEFAULT_TIMEOUT_SECONDS = 10


def call_profanity_api(subject: str, description: str) -> Any:
    """POST the request text to the Profanity API and return its JSON.

    Configuration (environment variables):
        PROFANITY_API_URL      Required. Full HTTPS URL of the endpoint.
        PROFANITY_API_KEY      Optional. Sent as the x-api-key header.
        PROFANITY_API_TIMEOUT  Optional. Seconds, default 10.

    Raises:
        ScoringError: configuration is missing or the call failed in any way.
    """
    url = os.environ.get("PROFANITY_API_URL", "").strip()
    if not url.lower().startswith("https://"):
        raise ScoringError("not_configured", "PROFANITY_API_URL must be an https URL")

    try:
        timeout = float(os.environ.get("PROFANITY_API_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECONDS

    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get("PROFANITY_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key

    try:
        response = requests.post(
            url,
            json={"subject": subject, "description": description},
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.Timeout as exc:
        raise ScoringError("upstream_timeout", "Profanity API timed out") from exc
    except requests.RequestException as exc:
        raise ScoringError("upstream_unreachable", type(exc).__name__) from exc

    if not 200 <= response.status_code < 300:
        raise ScoringError("upstream_error", f"HTTP {response.status_code}")

    try:
        return response.json()
    except ValueError as exc:
        raise ScoringError("invalid_response", "response is not valid JSON") from exc
