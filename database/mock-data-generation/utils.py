import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List

# CONFIG
NUM_RECORDS = 100


# RANDOM SEED (FIXED MISSING FUNCTION)
def set_seed(seed: int = 42):
    random.seed(seed)


# GLOBAL STATE
GLOBAL_DATA: Dict[str, List[str]] = {
    "users": [],
    "categories": []
}


# CONSTANTS
AVAILABILITY_OPTIONS = [
    {"weekdays": "morning"},
    {"weekdays": "afternoon"},
    {"weekdays": "evening"},
    {"weekends": "full_day"},
    {"weekdays": ["mon", "wed"]},
    {"weekdays": "flexible"},
]

APPLICATION_STATUSES = [
    "DRAFT",
    "IN_PROGRESS",
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED"
]



# TIME HELPERS
def base_time():
    return datetime(2026, 1, 1, 9, 0, 0)


def random_created_at(index: int):
    return base_time() + timedelta(
        days=index + random.randint(0, 5),
        hours=random.randint(0, 8),
        minutes=random.randint(0, 59),
    )


def random_timestamp():
    return base_time() + timedelta(
        days=random.randint(0, 365),
        hours=random.randint(0, 23),
        minutes=random.randint(0, 59),
    )



# SIMPLE VALUE GENERATOR
def generate_value(col_name: str, col_type: str) -> Any:
    col_type = col_type.lower()

    if "text" in col_type or "char" in col_type:
        return f"{col_name}_{random.randint(1000, 9999)}"

    if "int" in col_type:
        return random.randint(1, 1000)

    if "bigint" in col_type:
        return random.randint(10000, 999999)

    if "boolean" in col_type:
        return random.choice([True, False])

    if "timestamp" in col_type:
        return random_timestamp()

    if "date" in col_type:
        return base_time().date()

    if "json" in col_type:
        return "{}"

    return None