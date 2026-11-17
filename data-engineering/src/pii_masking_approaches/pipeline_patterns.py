"""Approach 1 baseline: the free-text patterns the archive pipeline uses today.

Copied unchanged from ``SCRUB_PATTERNS`` in
``data-engineering/src/requests_archive/lambda_function.py`` on branch
``hpant5_416_archive_datapipeline_rdbms_s3`` so the evaluation measures exactly
what the pipeline does. If that list changes, update this copy.
"""

import re

SCRUB_PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("SSN",   re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("CARD",  re.compile(r"(?<!\d)(?:\d[ -]?){13,16}(?!\d)")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}(?!\d)")),
    ("URL",   re.compile(r"https?://\S+")),
]


def pipeline_spans(text):
    """Return (start, end, tag) for every pipeline match.

    The pipeline applies the patterns one after another with ``re.subn``, so a
    later pattern never sees text an earlier one already replaced. Matching on
    the original text and dropping overlaps keeps that behaviour.
    """
    spans = []
    for tag, pattern in SCRUB_PATTERNS:
        for m in pattern.finditer(text):
            if not any(m.start() < e and s < m.end() for s, e, _ in spans):
                spans.append((m.start(), m.end(), tag))
    return spans
