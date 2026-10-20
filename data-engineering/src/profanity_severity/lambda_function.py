"""Return a severity score for Help Request profanity classifications."""

import json


SEVERITY_NORMAL = 0
SEVERITY_PROFANITY = 1
SEVERITY_DEPRESSIVE_OR_SUICIDAL = 2
SEVERITY_THREATENING = 3


REQUIRED_FLAGS = (
    "contains_profanity",
    "contains_depressive_content",
    "contains_suicidal_content",
    "contains_threatening_content",
)


def build_response(status_code, body):
    """Build a Lambda-compatible response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body),
    }


def parse_event(event):
    """Parse the Lambda event or request body."""
    if event is None:
        return {}

    if not isinstance(event, dict):
        raise ValueError(
            "Request body must be a JSON object"
        )

    body = event.get("body")

    if body is None:
        return event

    if isinstance(body, dict):
        return body

    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Invalid JSON body"
            ) from exc

        if not isinstance(parsed, dict):
            raise ValueError(
                "Request body must be a JSON object"
            )

        return parsed

    raise ValueError(
        "Request body must be a JSON object"
    )


def validate_classification(classification):
    """Validate classification flags from the Profanity API."""
    if not isinstance(classification, dict):
        raise ValueError(
            "Classification must be a JSON object"
        )

    for flag in REQUIRED_FLAGS:
        if flag not in classification:
            raise ValueError(
                f"Missing classification field: {flag}"
            )

        if not isinstance(
            classification[flag],
            bool,
        ):
            raise ValueError(
                f"{flag} must be boolean"
            )


def get_severity_score(classification):
    """
    Return the highest applicable severity score.

    0 = normal
    1 = profanity
    2 = depressive or suicidal content
    3 = threatening content
    """
    validate_classification(
        classification
    )

    if classification[
        "contains_threatening_content"
    ]:
        return SEVERITY_THREATENING

    if (
        classification[
            "contains_depressive_content"
        ]
        or classification[
            "contains_suicidal_content"
        ]
    ):
        return SEVERITY_DEPRESSIVE_OR_SUICIDAL

    if classification[
        "contains_profanity"
    ]:
        return SEVERITY_PROFANITY

    return SEVERITY_NORMAL


def lambda_handler(event, context):
    """Return the Help Request severity score."""
    try:
        classification = parse_event(event)

        severity_score = get_severity_score(
            classification
        )

        return build_response(
            200,
            {
                "severity_score": severity_score,
            },
        )

    except ValueError as exc:
        return build_response(
            400,
            {
                "error": str(exc),
                "severity_score": None,
            },
        )

    except Exception as exc:
        print(
            f"Severity scoring failed: {exc}"
        )

        return build_response(
            500,
            {
                "error": (
                    "Unable to calculate severity score"
                ),
                "severity_score": None,
            },
        )


if __name__ == "__main__":
    samples = [
        {
            "name": "Normal",
            "event": {
                "contains_profanity": False,
                "contains_depressive_content": False,
                "contains_suicidal_content": False,
                "contains_threatening_content": False,
            },
        },
        {
            "name": "Profanity",
            "event": {
                "contains_profanity": True,
                "contains_depressive_content": False,
                "contains_suicidal_content": False,
                "contains_threatening_content": False,
            },
        },
        {
            "name": "Depressive",
            "event": {
                "contains_profanity": False,
                "contains_depressive_content": True,
                "contains_suicidal_content": False,
                "contains_threatening_content": False,
            },
        },
        {
            "name": "Suicidal",
            "event": {
                "contains_profanity": False,
                "contains_depressive_content": False,
                "contains_suicidal_content": True,
                "contains_threatening_content": False,
            },
        },
        {
            "name": "Threatening",
            "event": {
                "contains_profanity": False,
                "contains_depressive_content": False,
                "contains_suicidal_content": False,
                "contains_threatening_content": True,
            },
        },
        {
            "name": "Multiple",
            "event": {
                "contains_profanity": True,
                "contains_depressive_content": True,
                "contains_suicidal_content": False,
                "contains_threatening_content": True,
            },
        },
    ]

    for sample in samples:
        response = lambda_handler(
            sample["event"],
            None,
        )

        print(
            sample["name"],
            response["statusCode"],
            response["body"],
        )