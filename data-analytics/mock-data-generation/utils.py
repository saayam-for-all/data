import csv
import json
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Sequence


def set_seed(seed: int = 42) -> None:
    random.seed(seed)


CAT_IDS = [
    "0.0.0.0.0","1","1.1","1.2","1.3","1.3.1","1.3.2","1.3.3","1.3.4","1.3.5",
    "2","2.1","2.2","2.3","2.4",
    "3","3.1","3.10","3.2","3.3","3.3.1","3.3.10","3.3.11","3.3.12","3.3.13","3.3.2","3.3.3","3.3.4","3.3.5","3.3.6","3.3.7","3.3.8","3.3.9","3.4","3.5","3.6","3.7","3.8","3.9",
    "4","4.1","4.2","4.3","4.3.1","4.3.2","4.3.3","4.3.4","4.3.5","4.3.6","4.4","4.5","4.6","4.7",
    "5","5.1","5.1.1","5.1.10","5.1.11","5.1.2","5.1.3","5.1.4","5.1.5","5.1.6","5.1.7","5.1.8","5.1.9","5.2","5.3","5.4","5.5",
    "6","6.1","6.2","6.3","6.4","6.5","6.6","6.7","6.8","6.9"
]
USABLE_CAT_IDS = [c for c in CAT_IDS if c != "0.0.0.0.0"]

AVAILABILITY_OPTIONS = [
    {"weekdays": "evening"},
    {"weekdays": "morning"},
    {"weekdays": "afternoon"},
    {"weekends": "full_day"},
    {"weekends": "morning", "weekdays": "evening"},
    {"weekdays": ["monday_evening", "wednesday_evening"]},
    {"weekdays": ["tuesday_morning", "thursday_afternoon"]},
    {"weekdays": "flexible", "weekends": "partial"},
]

STATUSES = ["DRAFT", "IN_PROGRESS", "SUBMITTED", "UNDER_REVIEW", "APPROVED"]


def format_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def format_date(value) -> str:
    return value.strftime("%Y-%m-%d")


def json_text(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def make_user_ids(count: int, start: int = 101) -> List[str]:
    return [f"U{start + i}" for i in range(count)]


def build_skill_map(volunteer_rows: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
    skill_map: Dict[str, List[str]] = {}
    for row in volunteer_rows:
        skill_map[row["user_id"]] = json.loads(row["skill_codes"])
    return skill_map


def write_csv(filename: str, rows: Sequence[Dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write for {filename}")
    with open(filename, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def base_created_at() -> datetime:
    return datetime(2026, 1, 1, 9, 0, 0)


def random_created_at(index: int) -> datetime:
    base_date = base_created_at()
    return base_date + timedelta(
        days=index + random.randint(0, 5),
        hours=random.randint(0, 8),
        minutes=random.randint(0, 59),
    )
