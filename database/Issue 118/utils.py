from __future__ import annotations

import random
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent


def random_timestamp(start_year: int = 2023, end_year: int = 2025) -> datetime:
    start = datetime(start_year, 1, 1, 8, 0, 0)
    end = datetime(end_year, 12, 31, 18, 0, 0)
    delta = end - start
    seconds = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=seconds)


def fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def maybe_none(value, probability: float = 0.15):
    return None if random.random() < probability else value


def read_users(count: int = 5000) -> list[int]:
    """
    Try reading user IDs from users.csv in the same folder.
    If missing/empty, fall back to synthetic IDs.
    """
    users_path = BASE_DIR / "users.csv"

    if users_path.exists() and users_path.stat().st_size > 0:
        try:
            df = pd.read_csv(users_path)
            if "user_id" in df.columns and not df.empty:
                user_ids = (
                    pd.to_numeric(df["user_id"], errors="coerce")
                    .dropna()
                    .astype(int)
                    .drop_duplicates()
                    .tolist()
                )
                if user_ids:
                    return user_ids
        except Exception:
            pass

    return list(range(101, 101 + count))


def read_help_categories() -> list[int]:
    """
    Try reading cat_id values from help_categories.csv in the same folder.
    If missing, fall back to synthetic category IDs.
    """
    candidate_files = [
        BASE_DIR / "help_categories.csv",
        BASE_DIR / "help_category.csv",
        BASE_DIR / "categories.csv",
    ]

    for path in candidate_files:
        if path.exists() and path.stat().st_size > 0:
            try:
                df = pd.read_csv(path)
                for col in ["cat_id", "category_id", "id"]:
                    if col in df.columns:
                        cat_ids = (
                            pd.to_numeric(df[col], errors="coerce")
                            .dropna()
                            .astype(int)
                            .drop_duplicates()
                            .tolist()
                        )
                        if cat_ids:
                            return cat_ids
            except Exception:
                pass

    return [1, 2, 3, 4, 5, 6, 7, 8]


def choose_skill_codes(cat_ids: list[int], min_k: int = 2, max_k: int = 4) -> list[int]:
    k = random.randint(min_k, min(max_k, len(cat_ids)))
    return sorted(random.sample(cat_ids, k))


def weighted_choice(mapping: dict[str, float]) -> str:
    keys = list(mapping.keys())
    weights = list(mapping.values())
    return random.choices(keys, weights=weights, k=1)[0]