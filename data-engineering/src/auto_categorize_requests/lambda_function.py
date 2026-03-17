"""
Lambda entry point for help request auto-categorization (issue #100).
CONTRIBUTING.md requires lambda_handler(event, context).
"""
import json
import logging
from typing import Any, Dict

from .classifier import classify_help_request

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _build_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }


def lambda_handler(event, context):
    """
    AWS Lambda handler (API Gateway proxy compatible).
    Expected event body: { "subject": "...", "description": "..." }
    """
    try:
        raw_body = event.get("body", {})
        if isinstance(raw_body, str):
            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON body; defaulting to empty payload.")
                payload = {}
        elif isinstance(raw_body, dict):
            payload = raw_body
        else:
            payload = {}

        subject = payload.get("subject")
        description = payload.get("description")

        result = classify_help_request(subject=subject, description=description)

        response_body = {
            "category": result.category,
            "subcategory": result.subcategory,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
        }

        return _build_response(200, response_body)

    except Exception as exc:
        logger.error("Unhandled error in handler: %s", exc, exc_info=True)
        return _build_response(
            500,
            {
                "error": "Internal server error",
                "details": "An unexpected error occurred while classifying the request.",
            },
        )


if __name__ == "__main__":
    test_event = {
        "body": json.dumps(
            {
                "subject": "I need a place to stay tonight",
                "description": "I just lost my apartment and I'm on the streets with my kids.",
            }
        )
    }
    print(lambda_handler(test_event, None))
