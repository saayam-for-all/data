
import boto3

from methods.regex_masking import mask_pii


def mask_pii_with_comprehend(text, client=None):
    """Mask regex PII plus entities found by Amazon Comprehend."""
    masked = mask_pii(text)

    if client is None:
        client = boto3.client("comprehend", region_name="us-east-1")

    response = client.detect_pii_entities(
        Text=masked,
        LanguageCode="en",
    )

    # Offsets refer to the text sent to Comprehend.
    # Replace from right to left to preserve earlier offsets.
    entities = sorted(
        response.get("Entities", []),
        key=lambda item: item["BeginOffset"],
        reverse=True,
    )

    for entity in entities:
        start = entity["BeginOffset"]
        end = entity["EndOffset"]
        pii_type = entity["Type"]

        masked = (
            masked[:start]
            + f"[{pii_type}]"
            + masked[end:]
        )

    return masked
