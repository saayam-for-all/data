from .classifier import classify_request


def handler(event, context):
    text = event.get("text") or event.get("body") or ""

    category = classify_request(text)

    return {
        "statusCode": 200,
        "category": category
    }