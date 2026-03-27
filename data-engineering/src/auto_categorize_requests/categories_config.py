from typing import List, Dict, TypedDict


class CategoryOption(TypedDict):
    category: str
    subcategory: str
    canonical_label: str


# Categories/subcategories captured from the current request form (General)
RAW_CATEGORIES: Dict[str, List[str]] = {
    "Clothing Assistance": [
        "Donate Clothes",
        "Borrow Clothes",
        "Emergency Clothing Assistance",
        "Tailoring",
    ],
    "Education & Career Support": [
        "College Application Help",
        "SOP & Essay Review",
        "Tutoring",
        "Scholarship Knowledge",
        "Study Group Formation",
        "Career Guidance",
    ],
    "Elderly Community Assistance": [
        "Senior Relocation Support",
        "Digital Support for Seniors",
        "Medication Management",
        "Medical Devices Setup",
        "Errands, Events & Transportation",
        "Transportation for Appointments",
    ],
    "Food & Essentials": [
        "Food Assistance",
        "Grocery Shopping & Delivery",
        "Cooking Help",
    ],
    "Healthcare & Wellness": [
        "Medical Consultation",
        "Medicine Delivery",
        "Mental Wellbeing Support",
        "Medication Reminders",
        "Health Education Guidance",
    ],
    "Housing Assistance": [
        "Lease Support",
        "Tenant Rent Support",
        "Repair & Maintenance Support",
        "Utilities Setup Support",
        "Looking for Rental",
        "Find a Roommate",
    ],
    "Uncategorized": [
        "Uncategorized",
    ],
}


def build_category_options() -> List[CategoryOption]:
    options: List[CategoryOption] = []
    for category, subcategories in RAW_CATEGORIES.items():
        for sub in subcategories:
            canonical = f"{category} - {sub}"
            options.append(
                CategoryOption(
                    category=category,
                    subcategory=sub,
                    canonical_label=canonical,
                )
            )
    return options


CATEGORY_OPTIONS: List[CategoryOption] = build_category_options()

UNCATEGORIZED: CategoryOption = CategoryOption(
    category="Uncategorized",
    subcategory="Uncategorized",
    canonical_label="Uncategorized - Uncategorized",
)
