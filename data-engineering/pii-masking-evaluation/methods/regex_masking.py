import re

PATTERNS = {
    "EMAIL": re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
    ),
    "PHONE": re.compile(
        r"(?<!\d)(?:\+1[\s.-]?)?"
        r"(?:\(\d{3}\)|\d{3})[\s.-]?"
        r"\d{3}[\s.-]?\d{4}(?!\d)"
    ),
    "ADDRESS": re.compile(
        r"\b\d{1,6}\s+(?:[A-Za-z]+\s+){0,3}"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|"
        r"Drive|Dr|Boulevard|Blvd)\b",
        re.IGNORECASE,
    ),
    "CREDIT_CARD": re.compile(
        r"\b(?:card|credit card|debit card|card number)"
        r"\s*(?:number\s*)?(?:is|:|#)?\s*"
        r"((?:\d[ -]?){12,18}\d)\b",
        re.IGNORECASE,
    ),
    "SSN": re.compile(
        r"\b(?:SSN|social security number)"
        r"\s*(?:is|:|#)?\s*"
        r"(\d{3}-\d{2}-\d{4})\b",
        re.IGNORECASE,
    ),
}

def mask_pii(text):
    masked = text
    for pii_type, pattern in PATTERNS.items():
        if pii_type in ("CREDIT_CARD", "SSN"):
            masked = pattern.sub(
                lambda match: match.group(0).replace(
                    match.group(1), f"[{pii_type}]"
                ),
                masked,
            )
        else:
            masked = pattern.sub(f"[{pii_type}]", masked)
    return masked
