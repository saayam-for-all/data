import random
from datetime import timedelta
from typing import Dict, List, Sequence

from utils import format_ts, random_created_at


RATINGS = ["1", "2", "3", "4", "5"]


def generate_volunteer_rating(
    user_rows: Sequence[Dict[str, str]],
    request_rows: Sequence[Dict[str, str]],
    count: int = 100,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    user_ids = [row["user_id"] for row in user_rows]
    request_ids = [row["req_id"] for row in request_rows]

    for index in range(count):
        last_update_date = random_created_at(index) + timedelta(
            days=random.randint(0, 5),
            hours=random.randint(0, 12),
            minutes=random.randint(0, 59),
        )

        rating = random.choice(RATINGS)

        rows.append({
            "volunteer_rating_id": 20000 + index,
            "user_id": random.choice(user_ids),
            "request_id": random.choice(request_ids),
            "rating": rating,
            "feedback": f"Volunteer provided support with rating {rating}.",
            "last_update_date": format_ts(last_update_date),
        })

    return rows