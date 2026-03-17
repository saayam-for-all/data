from typing import List, Dict, TypedDict


class CategoryOption(TypedDict):
    category: str
    subcategory: str
    canonical_label: str


# TODO: Replace with real categories/subcategories from test-saayam.netlify.app
RAW_CATEGORIES: Dict[str, List[str]] = {
    "Shelter": [
        "Emergency Shelter",
        "Temporary Housing",
        "Long-Term Housing",
    ],
    "Food": [
        "Food Pantry",
        "Hot Meals",
        "Food Vouchers",
    ],
    "Health": [
        "Medical Assistance",
        "Mental Health Support",
        "Medication",
    ],
    "Employment": [
        "Job Search Assistance",
        "Skills Training",
        "Resume Support",
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
