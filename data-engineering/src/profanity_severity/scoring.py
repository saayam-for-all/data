"""Turn a Profanity API response into a severity score (0-3).

Score 0: normal request
Score 1: profanity
Score 2: depressive or suicidal content
Score 3: threatening content

When more than one category is flagged, the highest score wins and every
flagged category is reported.

Scoring is fail-closed: anything that is not a complete, well-formed
response raises ScoringError. A failure must never be reported as score 0,
because score 0 lets a request into active matching.
"""
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

# (score, category, response flags that trigger it). Mirrors the flags
# returned by the inappropriate content filter.
SEVERITY_CATEGORIES: Tuple[Tuple[int, str, Tuple[str, ...]], ...] = (
    (1, "profanity", ("contains_profanity",)),
    (
        2,
        "depressive_suicidal",
        ("contains_depressive_content", "contains_suicidal_content"),
    ),
    (3, "threatening", ("contains_threatening_content",)),
)

REQUIRED_FLAGS: Tuple[str, ...] = tuple(
    flag for _, _, flags in SEVERITY_CATEGORIES for flag in flags
)


class ScoringError(Exception):
    """The API response could not be turned into a trustworthy score."""

    def __init__(self, error_code: str, detail: str = ""):
        super().__init__(f"{error_code}: {detail}" if detail else error_code)
        self.error_code = error_code
        self.detail = detail


@dataclass(frozen=True)
class SeverityResult:
    """A validated severity score and the categories behind it."""

    score: int
    categories: Tuple[str, ...]


def _unwrap(payload: Any) -> Dict[str, Any]:
    """Return the response dict, unwrapping a Lambda proxy envelope.

    The filter is a Lambda that returns {"statusCode": 200, "body": "<json>"}.
    Depending on how it is invoked, the caller sees either that envelope or
    just the inner JSON body, so both are accepted.
    """
    if not isinstance(payload, dict):
        raise ScoringError("invalid_response", "response is not a JSON object")

    if "body" in payload and "statusCode" in payload:
        status = payload["statusCode"]
        if not isinstance(status, int) or isinstance(status, bool) or not 200 <= status < 300:
            raise ScoringError("upstream_error", f"statusCode={status!r}")
        body = payload["body"]
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except ValueError as exc:
                raise ScoringError("invalid_response", "body is not valid JSON") from exc
        if not isinstance(body, dict):
            raise ScoringError("invalid_response", "body is not a JSON object")
        return body

    return payload


def extract_severity(payload: Any) -> SeverityResult:
    """Validate a Profanity API response and derive its severity score.

    Raises:
        ScoringError: the response reports an error, or any of the four
            flags is missing or not a boolean.
    """
    data = _unwrap(payload)

    # The filter reports its own failures with HTTP 200 and an "Error" field
    # (and zeroed flags), so they have to be rejected here.
    if "Error" in data or "error" in data:
        raise ScoringError("upstream_error", "response contains an error field")
    status = data.get("status_code")
    if status is not None and (
        not isinstance(status, int) or isinstance(status, bool) or not 200 <= status < 300
    ):
        raise ScoringError("upstream_error", f"status_code={status!r}")

    for flag in REQUIRED_FLAGS:
        if flag not in data:
            raise ScoringError("invalid_response", f"missing flag {flag}")
        if not isinstance(data[flag], bool):
            raise ScoringError("invalid_response", f"flag {flag} is not a boolean")

    score = 0
    categories: List[str] = []
    for level, category, flags in SEVERITY_CATEGORIES:
        if any(data[flag] for flag in flags):
            categories.append(category)
            score = max(score, level)

    return SeverityResult(score=score, categories=tuple(categories))
