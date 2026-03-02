from .categories import CATEGORIES


def classify_request(text: str) -> str:
    text = text.lower()

    for category, keywords in CATEGORIES.items():
        for keyword in keywords:
            if keyword in text:
                return category

    return "unknown"