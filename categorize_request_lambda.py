import json
import re

CATEGORIES = {
    "Clothing Assistance": [
        "Donate Clothes",
        "Borrow Clothes",
        "Emergency Clothing Assistance",
        "Tailoring"
    ],
    "Education & Career Support": [
        "Job Search Help"
    ],
    "Elderly Community Assistance": [
        "Companionship"
    ],
    "Food & Essentials": [
        "Food Assistance",
        "Grocery Shopping & Delivery",
        "Cooking Help"
    ],
    "Healthcare & Wellness": [
        "Medical Assistance"
    ],
    "Housing Assistance": [
        "Emergency Housing Assistance"
    ],
    "General": [
        "Other"
    ]
}

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())

def handler(event, context):
    try:
        body = event.get("body", {})
        if isinstance(body, str):
            body = json.loads(body)

        subject = (body or {}).get("subject", "")
        description = (body or {}).get("description", "")
        text = f"{_clean(subject)} {_clean(description)}"

        if any(k in text for k in ["homeless", "evicted", "lost my apartment", "place to stay", "sleep tonight", "rent"]):
            result = {
                "category": "Housing Assistance",
                "subcategory": "Emergency Housing Assistance",
                "confidence": 0.9,
                "reasoning": "Detected housing related keywords."
            }

        elif any(k in text for k in ["hungry", "food", "groceries", "meal"]):
            result = {
                "category": "Food & Essentials",
                "subcategory": "Food Assistance",
                "confidence": 0.85,
                "reasoning": "Detected food related keywords."
            }

        elif any(k in text for k in ["clothes", "jacket", "dress", "coat"]):
            result = {
                "category": "Clothing Assistance",
                "subcategory": "Emergency Clothing Assistance",
                "confidence": 0.8,
                "reasoning": "Detected clothing related keywords."
            }

        elif any(k in text for k in ["doctor", "hospital", "medical", "medicine"]):
            result = {
                "category": "Healthcare & Wellness",
                "subcategory": "Medical Assistance",
                "confidence": 0.85,
                "reasoning": "Detected healthcare related keywords."
            }

        elif any(k in text for k in ["job", "resume", "career", "interview"]):
            result = {
                "category": "Education & Career Support",
                "subcategory": "Job Search Help",
                "confidence": 0.75,
                "reasoning": "Detected career related keywords."
            }

        else:
            result = {
                "category": "General",
                "subcategory": "Other",
                "confidence": 0.5,
                "reasoning": "No strong keywords detected."
            }

        return {
            "statusCode": 200,
            "body": json.dumps(result)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }