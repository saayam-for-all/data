import json
import boto3
import re
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Bedrock client initialised once at module level — reused across warm Lambda invocations
bedrock_client = boto3.client("bedrock-runtime", region_name="us-east-1")

# ─────────────────────────────────────────────
# CATEGORY CONFIG
# ─────────────────────────────────────────────
CATEGORIES = {
    "Clothing Assistance": [
        "Donate Clothes",
        "Borrow Clothes",
        "Emergency Clothing Assistance",
        "Tailoring"
    ],
    "Education & Career Support": [
        "College Application Help",
        "SOP & Essay Review",
        "Tutoring",
        "Scholarship Knowledge",
        "Study Group Formation",
        "Career Guidance",
        "Education Resource Sharing"
    ],
    "Elderly Community Assistance": [
        "Senior Relocation Support",
        "Digital Support for Seniors",
        "Medication Management",
        "Medical Devices Setup",
        "Errands, Events & Transportation",
        "Transportation for Appointments",
        "Scheduling Appointments or Tasks",
        "Social Connection",
        "Meal Support"
    ],
    "Food & Essentials": [
        "Food Assistance",
        "Grocery Shopping & Delivery",
        "Cooking Help"
    ],
    "Healthcare & Wellness": [
        "Medical Consultation",
        "Medicine Delivery",
        "Mental Wellbeing Support",
        "Medication Reminders",
        "Health Education Guidance"
    ],
    "Housing Assistance": [
        "Lease Support",
        "Tenant Rent Support",
        "Repair & Maintenance Support",
        "Utilities Setup Support",
        "Looking for Rental",
        "Find a Roommate",
        "Move-in Help",
        "Packers & Movers Support",
        "Buy Household Items",
        "Sell Household Items"
    ],
    "General": []  # No subcategories — fallback
}


def build_category_list_text():
    lines = []
    for category, subcategories in CATEGORIES.items():
        if subcategories:
            for sub in subcategories:
                lines.append(f"- {category} > {sub}")
        else:
            lines.append(f"- {category} (no subcategory)")
    return "\n".join(lines)


SYSTEM_PROMPT = f"""You are a classification assistant for a community help platform.
Your job is to read a help request and assign it the most appropriate category and subcategory from the list below.

VALID CATEGORIES AND SUBCATEGORIES:
{build_category_list_text()}

RULES:
1. You MUST only return a category and subcategory from the list above. Never invent new ones.
2. If the request does not clearly fit any category, use: category = "General", subcategory = null.
3. Return your answer as a single JSON object with these exact keys:
   - "category": string (must match exactly)
   - "subcategory": string or null (must match exactly, or null for General)
   - "confidence": float between 0.0 and 1.0
   - "reasoning": string (1-2 sentences max)
4. Do not include any text outside the JSON object.
5. If the input is in another language, translate and classify it normally.
"""


def call_bedrock(subject: str, description: str) -> dict:
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


def lambda_handler(event, context):
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
