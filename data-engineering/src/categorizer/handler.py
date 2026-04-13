import json
from src.categorizer.classifier import classify_request


def lambda_handler(event, context):
    try:
        # Parse body
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        else:
            body = event.get("body", event)

        subject = body.get("subject", "").strip()
        description = body.get("description", "").strip()

        result = classify_request(subject, description)

        return {
            "statusCode": 200,
            "body": result
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": {
                "error": str(e),
                "category": "General",
                "subcategory": "General",
                "confidence": 0.0,
                "reasoning": "Internal error occurred."
            }
        }