import csv
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List, Sequence


CATEGORY_IDS = [
    "0.0.0.0.0", "1", "1.1", "1.2", "1.3", "1.3.1", "1.3.2", "1.3.3", "1.3.4", "1.3.5",
    "2", "2.1", "2.2", "2.3", "2.4",
    "3", "3.1", "3.10", "3.2", "3.3", "3.3.1", "3.3.10", "3.3.11", "3.3.12", "3.3.13",
    "3.3.2", "3.3.3", "3.3.4", "3.3.5", "3.3.6", "3.3.7", "3.3.8", "3.3.9", "3.4", "3.5", "3.6", "3.7", "3.8", "3.9",
    "4", "4.1", "4.2", "4.3", "4.3.1", "4.3.2", "4.3.3", "4.3.4", "4.3.5", "4.3.6", "4.4", "4.5", "4.6", "4.7",
    "5", "5.1", "5.1.1", "5.1.10", "5.1.11", "5.1.2", "5.1.3", "5.1.4", "5.1.5", "5.1.6", "5.1.7", "5.1.8", "5.1.9", "5.2", "5.3", "5.4", "5.5",
    "6", "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7", "6.8", "6.9"
]

SKILL_LEVELS = ["BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"]
LANGUAGE_IDS = [1, 2, 3, 4, 5, 6]
ORG_TYPES = ["non_profit", "for_profit"]
ORG_SIZES = ["small", "medium", "large"]


def set_seed(seed: int = 42) -> None:
    random.seed(seed)


def choose(values: Sequence[Any], rng: random.Random) -> Any:
    if not values:
        raise ValueError("Cannot choose from an empty sequence")
    return rng.choice(values)


def format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_date(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def parse_datetime(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def point_near_city(latitude: float, longitude: float, rng: random.Random, radius: float = 0.01) -> str:
    """Return WKT POINT(longitude latitude) for a PostGIS geography field."""
    lat = latitude + rng.uniform(-radius, radius)
    lon = longitude + rng.uniform(-radius, radius)
    return f"POINT({lon:.6f} {lat:.6f})"


def postgres_point_near_city(latitude: float, longitude: float, rng: random.Random, radius: float = 0.01) -> str:
    """Return PostgreSQL point literal (longitude,latitude) for users.last_location."""
    lat = latitude + rng.uniform(-radius, radius)
    lon = longitude + rng.uniform(-radius, radius)
    return f"({lon:.6f},{lat:.6f})"


def unique_email(first: str, last: str, index: int) -> str:
    safe_first = re.sub(r"[^a-z0-9]", "", first.lower())
    safe_last = re.sub(r"[^a-z0-9]", "", last.lower())
    return f"{safe_first}.{safe_last}{index}@example.com"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
