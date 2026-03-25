# ─────────────────────────────────────────────
# CATEGORY CONFIG
# Update this dict if the platform adds or removes categories
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


def build_category_list_text() -> str:
    """Converts the CATEGORIES dict into a compact text block for the system prompt."""
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
