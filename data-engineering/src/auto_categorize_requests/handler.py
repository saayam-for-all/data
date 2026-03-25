import json
import logging

from classifier import call_bedrock, validate_result

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """Lambda entry point. Parses input, classifies the request, and returns the result."""
    try:
        # Parse input — supports API Gateway, direct invoke, and raw dict
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        elif isinstance(event.get("body"), dict):
            body = event["body"]
        else:
            body = event

        subject     = (body.get("subject") or "").strip()
        description = (body.get("description") or "").strip()

        # Validate — at least one field must be present
        if not subject and not description:
            return {
                "statusCode": 400,
                "body": json.dumps({
                    "error": "Both subject and description are missing. Please provide at least one."
                })
            }

        if not subject:
            subject = "(no subject provided)"
        if not description:
            description = "(no description provided)"

        logger.info(f"Classifying — Subject: '{subject}' | Description: '{description[:80]}'")

        raw_result = call_bedrock(subject, description)
        result     = validate_result(raw_result)

        logger.info(f"Result: {result}")

        return {
            "statusCode": 200,
            "body": result
        }

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Bedrock response: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Failed to parse model response.",
                "category": "General",
                "subcategory": None,
                "confidence": 0.0,
                "reasoning": "Internal parsing error."
            })
        }

    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": f"Internal server error: {str(e)}"
            })
        }
