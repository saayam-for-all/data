import json
import re
import logging
import boto3

from categories import CATEGORIES, SYSTEM_PROMPT

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Bedrock client initialised once at module level — reused across warm Lambda invocations
bedrock_client = boto3.client("bedrock-runtime", region_name="us-east-1")


def call_bedrock(subject: str, description: str) -> dict:
    """Sends the subject and description to Bedrock and returns the raw classification result."""
    user_message = f"Subject: {subject}\nDescription: {description}"

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 300,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": user_message}
        ]
    }

    response = bedrock_client.invoke_model(
        modelId="anthropic.claude-3-haiku-20240307-v1:0",
        body=json.dumps(request_body),
        contentType="application/json",
        accept="application/json"
    )

    response_body = json.loads(response["body"].read())
    raw_text = response_body["content"][0]["text"].strip()

    # Strip markdown code fences if model wraps response in ```json ... ```
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    return json.loads(raw_text)


def validate_result(result: dict) -> dict:
    """Validates that the returned category and subcategory exist in the predefined list.
    Falls back to General if the model returns an invalid value.
    """
    category    = result.get("category", "General")
    subcategory = result.get("subcategory")
    confidence  = result.get("confidence", 0.0)
    reasoning   = result.get("reasoning", "")

    # Validate category
    if category not in CATEGORIES:
        logger.warning(f"Invalid category from model: '{category}'. Falling back to General.")
        return {
            "category": "General",
            "subcategory": None,
            "confidence": 0.1,
            "reasoning": "Could not determine a valid category. Defaulting to General."
        }

    # Validate subcategory
    valid_subcategories = CATEGORIES[category]
    if valid_subcategories and subcategory not in valid_subcategories:
        logger.warning(f"Invalid subcategory '{subcategory}' for '{category}'. Setting to None.")
        subcategory = None
        confidence = max(0.1, float(confidence) - 0.2)

    # General must have no subcategory
    if category == "General":
        subcategory = None

    return {
        "category": category,
        "subcategory": subcategory,
        "confidence": round(float(confidence), 2),
        "reasoning": reasoning
    }