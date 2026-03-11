import json
import re
from typing import Dict, List, Tuple

# ============================================================
# AWS Lambda - Request Category Classifier
# ============================================================

CATEGORY_CONFIG = {
    "GENERAL_CATEGORY": {
        "subcategories": {
            "GENERAL_REQUEST": [
                "help", "urgent", "support", "assistance", "need help"
            ]
        }
    },
    "FOOD_AND_ESSENTIALS_SUPPORT": {
        "subcategories": {
            "FOOD_ASSISTANCE": [
                "food", "hungry", "meal", "meals", "pantry", "food bank", "eat"
            ],
            "GROCERY_SHOPPING_AND_DELIVERY": [
                "grocery", "groceries", "shopping", "delivery", "store"
            ],
            "COOKING_HELP": [
                "cook", "cooking", "meal prep", "kitchen"
            ]
        }
    },
    "CLOTHING_SUPPORT": {
        "subcategories": {
            "DONATE_CLOTHES": [
                "donate clothes", "clothes donation", "give clothes"
            ],
            "BORROW_CLOTHES": [
                "need clothes", "borrow clothes", "jacket", "shoes", "uniform"
            ],
            "EMERGENCY_ASSISTANCE": [
                "emergency", "urgent crisis", "disaster"
            ],
            "EMERGENCY_CLOTHING_ASSISTANCE": [
                "lost clothes", "fire", "flood", "need clothing urgently"
            ],
            "SEASONAL_DRIVE_NOTIFICATION": [
                "winter coat", "seasonal clothing", "coat drive"
            ],
            "TAILORING": [
                "tailor", "hemming", "alteration", "repair clothes", "sew"
            ]
        }
    },
    "HOUSING_SUPPORT": {
        "subcategories": {
            "FIND_A_ROOMMATE": [
                "roommate", "shared room", "share apartment"
            ],
            "RENTING_SUPPORT": [
                "rent", "rental", "lease", "tenant", "eviction",
                "landlord", "apartment", "housing", "place to stay",
                "homeless", "lost my apartment", "sleep tonight", "shelter"
            ],
            "HOUSEHOLD_ITEM_EXCHANGE": [
                "furniture", "mattress", "table", "chair", "household items"
            ],
            "MOVING_ASSISTANCE": [
                "move", "moving", "packing", "boxes", "relocation"
            ],
            "CLEANING_HELP": [
                "cleaning", "clean house", "sweeping", "dusting"
            ],
            "HOME_REPAIR_SUPPORT": [
                "repair", "fix sink", "broken", "plumbing", "home repair"
            ],
            "UTILITIES_SETUP": [
                "utilities", "internet", "electricity", "water", "wifi", "gas"
            ]
        }
    },
    "EDUCATION_CAREER_SUPPORT": {
        "subcategories": {
            "COLLEGE_APPLICATION_HELP": [
                "college application", "admission", "apply to college"
            ],
            "SOP_ESSAY_REVIEW": [
                "sop", "essay review", "personal statement"
            ],
            "TUTORING": [
                "tutor", "tutoring", "homework", "study", "math help", "exam prep"
            ]
        }
    },
    "HEALTHCARE_WELLNESS_SUPPORT": {
        "subcategories": {
            "MEDICAL_NAVIGATION": [
                "doctor", "clinic", "hospital", "appointment", "health insurance"
            ],
            "MEDICINE_DELIVERY": [
                "medicine", "medication", "pharmacy", "prescription", "drugstore"
            ],
            "MENTAL_WELLBEING_SUPPORT": [
                "stress", "anxiety", "depressed", "mental health", "emotional support"
            ],
            "MEDICATION_REMINDERS": [
                "medication reminder", "pill reminder", "remind medicine"
            ],
            "HEALTH_EDUCATION_GUIDANCE": [
                "nutrition", "sleep", "hygiene", "healthy habits"
            ]
        }
    },
    "ELDERLY_SUPPORT": {
        "subcategories": {
            "SENIOR_LIVING_RELOCATION": [
                "senior housing", "elderly relocation", "assisted living"
            ],
            "DIGITAL_SUPPORT_FOR_SENIORS": [
                "help with phone", "tablet", "technology help", "zoom help"
            ],
            "MEDICAL_HELP": [
                "health device", "blood pressure machine", "elderly medical help"
            ],
            "ERRANDS_TRANSPORTATION": [
                "ride to doctor", "transport", "appointment ride", "errands"
            ],
            "SOCIAL_CONNECTION": [
                "lonely", "companionship", "visit senior", "social call"
            ],
            "MEAL_SUPPORT": [
                "cook meals for senior", "meal support", "prep meals"
            ]
        }
    }
}


def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def score_request(text: str) -> List[Tuple[str, str, float, List[str]]]:
    results = []

    for category, cat_meta in CATEGORY_CONFIG.items():
        for subcategory, keywords in cat_meta["subcategories"].items():
            score = 0.0
            matched = []

            for keyword in keywords:
                keyword_norm = normalize_text(keyword)
                if keyword_norm in text:
                    score += 1.5 if len(keyword_norm.split()) > 1 else 1.0
                    matched.append(keyword)

            if score > 0:
                results.append((category, subcategory, score, matched))

    results.sort(key=lambda x: x[2], reverse=True)
    return results


def build_reasoning(category: str, subcategory: str, matched_keywords: List[str]) -> str:
    if matched_keywords:
        return (
            f"Classified as {category} > {subcategory} based on matched terms: "
            + ", ".join(matched_keywords[:5])
            + "."
        )
    return f"Best available match is {category} > {subcategory} based on request content."


def classify_request(subject: str, description: str) -> Dict:
    combined = f"{subject or ''} {description or ''}".strip()
    if not combined:
        return {
            "category": "GENERAL_CATEGORY",
            "subcategory": "GENERAL_REQUEST",
            "confidence": 0.0,
            "reasoning": "Both subject and description are empty or missing."
        }

    text = normalize_text(combined)
    scored = score_request(text)

    if not scored:
        return {
            "category": "GENERAL_CATEGORY",
            "subcategory": "GENERAL_REQUEST",
            "confidence": 0.25,
            "reasoning": "Could not confidently match the request to a specific category, so it was placed in the general category."
        }

    best_category, best_subcategory, best_score, matched_keywords = scored[0]
    second_score = scored[1][2] if len(scored) > 1 else 0.0

    total_score = sum(item[2] for item in scored)
    base_confidence = best_score / total_score if total_score > 0 else 0.0
    margin = best_score - second_score

    confidence = min(0.98, round(base_confidence + min(margin * 0.1, 0.2), 2))
    reasoning = build_reasoning(best_category, best_subcategory, matched_keywords)

    return {
        "category": best_category,
        "subcategory": best_subcategory,
        "confidence": confidence,
        "reasoning": reasoning
    }


def lambda_handler(event, context):
    try:
        body = event

        if isinstance(event, dict) and "body" in event:
            body = event["body"]
            if isinstance(body, str):
                body = json.loads(body)

        subject = body.get("subject", "") if isinstance(body, dict) else ""
        description = body.get("description", "") if isinstance(body, dict) else ""

        result = classify_request(subject, description)

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(result)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "category": "GENERAL_CATEGORY",
                "subcategory": "GENERAL_REQUEST",
                "confidence": 0.0,
                "reasoning": f"Error processing request: {str(e)}"
            })
        }
        
if __name__ == "__main__":
    event = {
        "subject": "Need groceries",
        "description": "I cannot go to the store because I had surgery"
    }

    result = lambda_handler(event, None)
    print(result)