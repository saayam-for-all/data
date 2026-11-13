
import csv
import re
from pathlib import Path

from methods.regex_masking import mask_pii

BASE_DIR = Path(__file__).resolve().parents[1]
USERS_FILE = BASE_DIR / "data" / "mock_users.csv"


def load_user_names():
    """Load fictional names from the mock users table."""
    with USERS_FILE.open(
        newline="", encoding="utf-8-sig"
    ) as file:
        rows = csv.DictReader(file)
        return [
            row["full_name"].strip()
            for row in rows
            if row["full_name"].strip()
        ]


def mask_pii_with_lookup(text, names):
    """Apply regex masking, then mask known user names."""
    masked = mask_pii(text)

    for name in sorted(names, key=len, reverse=True):
        pattern = re.compile(
            r"(?<!\w)" + re.escape(name) + r"(?!\w)",
            re.IGNORECASE,
        )
        masked = pattern.sub("[NAME]", masked)

    return masked
