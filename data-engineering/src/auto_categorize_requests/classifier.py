from .categories import CATEGORIES


def classify_request(text: str) -> str:
    text = text.lower()

    for category, keywords in CATEGORIES.items():
        for word in keywords:
            if word in text:
                return category

    return "other"