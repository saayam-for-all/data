import argparse
import csv
import json
import random
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Dict, List, Tuple


REQUEST_COMMENTS_COLUMNS = [
    "request_comment_id",
    "req_id",
    "commenter_id",
    "comment_text",
    "created_at",
]

VOLUNTEER_RATING_COLUMNS = [
    "volunteer_rating_id",
    "user_id",
    "request_id",
    "rating",
    "review_comment",
    "created_at",
]


POSITIVE_COMMENTS = [
    "Very helpful and responsive volunteer.",
    "Support was quick and respectful.",
    "Issue was resolved smoothly.",
    "Great coordination and follow-up.",
    "Thank you for helping us so quickly.",
]

NEUTRAL_COMMENTS = [
    "Support was okay but could be faster.",
    "The process worked with minor delays.",
    "Request was partially addressed.",
    "Communication was average.",
]

NEGATIVE_COMMENTS = [
    "There was a delay in response.",
    "Support did not fully solve the issue.",
    "Needed better communication and updates.",
    "The help provided was limited.",
]


def _read_ids_from_csv(path: Path, id_column: str) -> List[int]:
    if not path.exists():
        return []
    ids: List[int] = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = row.get(id_column, "").strip()
            if raw.isdigit():
                ids.append(int(raw))
    return sorted(set(ids))


def load_parent_id_pools(mock_db_dir: Path, fallback_count: int) -> Tuple[List[int], List[int]]:
    request_ids = _read_ids_from_csv(mock_db_dir / "request.csv", "req_id")
    user_ids = _read_ids_from_csv(mock_db_dir / "users.csv", "user_id")

    if not request_ids:
        request_ids = list(range(1, fallback_count + 1))
    if not user_ids:
        user_ids = list(range(1, fallback_count + 1))

    return request_ids, user_ids


def _random_timestamp(days_back: int = 365) -> str:
    now = datetime.now(UTC)
    delta = timedelta(days=random.randint(0, days_back), minutes=random.randint(0, 1440))
    return (now - delta).strftime("%Y-%m-%d %H:%M:%S")


def _comment_for_rating(rating: int) -> str:
    if rating >= 4:
        return random.choice(POSITIVE_COMMENTS)
    if rating == 3:
        return random.choice(NEUTRAL_COMMENTS)
    return random.choice(NEGATIVE_COMMENTS)


def generate_request_comments(rows: int, request_ids: List[int], user_ids: List[int]) -> List[Dict[str, str]]:
    comments = []
    for i in range(1, rows + 1):
        comments.append(
            {
                "request_comment_id": str(i),
                "req_id": str(random.choice(request_ids)),
                "commenter_id": str(random.choice(user_ids)),
                "comment_text": random.choice(POSITIVE_COMMENTS + NEUTRAL_COMMENTS + NEGATIVE_COMMENTS),
                "created_at": _random_timestamp(),
            }
        )
    return comments


def generate_volunteer_ratings(rows: int, request_ids: List[int], user_ids: List[int]) -> List[Dict[str, str]]:
    ratings = []
    # Weighted distribution to make ratings realistic.
    rating_distribution = [1, 2, 3, 4, 5]
    weights = [5, 10, 20, 35, 30]

    for i in range(1, rows + 1):
        rating = random.choices(rating_distribution, weights=weights, k=1)[0]
        ratings.append(
            {
                "volunteer_rating_id": str(i),
                "user_id": str(random.choice(user_ids)),
                "request_id": str(random.choice(request_ids)),
                "rating": str(rating),
                "review_comment": _comment_for_rating(rating),
                "created_at": _random_timestamp(),
            }
        )
    return ratings


def _write_csv(path: Path, columns: List[str], rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _safe_read_schema(db_info_path: Path) -> Dict:
    if not db_info_path.exists():
        return {}
    try:
        with db_info_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic CSVs for request_comments and volunteer_rating."
    )
    parser.add_argument("--rows-request-comments", type=int, default=100)
    parser.add_argument("--rows-volunteer-rating", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fallback-parent-id-count", type=int, default=100)
    parser.add_argument(
        "--db-info",
        type=Path,
        default=Path("database/mock-data-generation/db_info.json"),
        help="Optional schema metadata source.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("database/mock_db"),
        help="Output folder for generated CSVs.",
    )
    args = parser.parse_args()

    random.seed(args.seed)

    # Optional schema read; currently used for compatibility and future extension.
    _ = _safe_read_schema(args.db_info)

    request_ids, user_ids = load_parent_id_pools(args.output_dir, args.fallback_parent_id_count)

    request_comments = generate_request_comments(args.rows_request_comments, request_ids, user_ids)
    volunteer_ratings = generate_volunteer_ratings(args.rows_volunteer_rating, request_ids, user_ids)

    _write_csv(args.output_dir / "request_comments.csv", REQUEST_COMMENTS_COLUMNS, request_comments)
    _write_csv(args.output_dir / "volunteer_rating.csv", VOLUNTEER_RATING_COLUMNS, volunteer_ratings)

    print(f"Generated {len(request_comments)} rows -> {args.output_dir / 'request_comments.csv'}")
    print(f"Generated {len(volunteer_ratings)} rows -> {args.output_dir / 'volunteer_rating.csv'}")
    print(f"request_id pool size: {len(request_ids)}; user_id pool size: {len(user_ids)}")


if __name__ == "__main__":
    main()

