"""Approach 3: pipeline patterns + Amazon Comprehend ``DetectPiiEntities``.

``boto3`` is only imported when a live client is created, so the module loads
without AWS packages. A live run needs credentials allowed to call
``comprehend:DetectPiiEntities`` (the team does not have that permission yet).

Every live response is saved to ``results/comprehend_cache.json`` so the
numbers can be re-scored later without calling AWS again.
"""

import json
from pathlib import Path

from detectors import merge_spans
from pipeline_patterns import pipeline_spans

# DATE_TIME and AGE are skipped: Comprehend tags every "Friday" or "9am",
# which would wreck the false-positive count. A date of birth is therefore
# only caught if Comprehend tags the surrounding words, which it does not.
IGNORED_TYPES = {"DATE_TIME", "AGE"}
MIN_SCORE = 0.5
TAG_MAP = {
    "NAME": "NAME", "ADDRESS": "ADDRESS", "PHONE": "PHONE", "EMAIL": "EMAIL",
    "SSN": "ID", "PASSPORT_NUMBER": "ID", "DRIVER_ID": "ID", "IN_AADHAAR": "ID",
    "CREDIT_DEBIT_NUMBER": "CARD", "URL": "URL", "USERNAME": "ID",
}

CACHE_PATH = Path(__file__).resolve().parent / "results" / "comprehend_cache.json"


def credentials_available():
    """True when boto3 is installed and can find AWS credentials."""
    try:
        import boto3
    except ImportError:
        return False
    return boto3.Session().get_credentials() is not None


class ComprehendDetector:
    """Calls Comprehend once per text and caches the raw entities."""

    def __init__(self, region="us-east-1", client=None, language="en"):
        if client is None:
            import boto3
            client = boto3.client("comprehend", region_name=region)
        self.client = client
        self.language = language
        self.cache = {}
        if CACHE_PATH.exists():
            self.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        self.calls = 0

    def entities(self, text):
        if text not in self.cache:
            resp = self.client.detect_pii_entities(Text=text, LanguageCode=self.language)
            self.cache[text] = resp.get("Entities", [])
            self.calls += 1
        return self.cache[text]

    def save_cache(self):
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1),
                              encoding="utf-8")

    def spans(self, text):
        out = []
        for ent in self.entities(text):
            if ent["Type"] in IGNORED_TYPES or ent.get("Score", 1.0) < MIN_SCORE:
                continue
            out.append((ent["BeginOffset"], ent["EndOffset"], TAG_MAP.get(ent["Type"], ent["Type"])))
        return out

    def __call__(self, text, name_parts=None):
        return merge_spans(pipeline_spans(text) + self.spans(text))


def monthly_cost(requests_per_month, avg_chars_per_request, price_per_unit=0.0001,
                 min_units=3, free_units=0):
    """Comprehend DetectPiiEntities cost when subject + description go in one call.

    1 unit = 100 characters, minimum 3 units per call, $0.0001 per unit
    (aws.amazon.com/comprehend/pricing). ``free_units`` is the 50,000-unit
    monthly free tier, which only applies in the first 12 months.
    """
    units_per_call = max(min_units, -(-int(avg_chars_per_request) // 100))
    units = requests_per_month * units_per_call
    billable = max(0, units - free_units)
    return round(billable * price_per_unit, 2), units_per_call
