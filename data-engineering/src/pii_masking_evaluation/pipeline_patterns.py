"""Approach 1 baseline: the free-text patterns the archive pipeline already uses.

Copied unchanged from SCRUB_PATTERNS / scrub_text in
data-engineering/src/requests_archive/lambda_function.py on the #416 branch
(hpant5_416_archive_datapipeline_rdbms_s3), so this evaluation measures exactly
what the pipeline does today. If that code changes, update this copy.
"""

import re

SCRUB_PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("SSN",   re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("CARD",  re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?!\d)")),
    ("URL",   re.compile(r"https?://\S+")),
]


def scrub_text(value, counts):
    """Replace patterned identifiers with a tag (same as the pipeline)."""
    if value is None:
        return None
    text = str(value)
    if not text.strip():
        return value
    for tag, pat in SCRUB_PATTERNS:
        text, n = pat.subn(f"[{tag}]", text)
        if n:
            counts[tag] = counts.get(tag, 0) + n
    return text
