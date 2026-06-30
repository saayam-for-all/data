import random
from datetime import timedelta
from typing import Dict, List

from utils import (
    format_ts,
    make_request_ids,
    make_user_ids,
    random_created_at,
)


RATINGS = ["1", "2", "3", "4", "5"]

FEEDBACK = [
    "Excellent support.",
    "Very helpful volunteer.",
    "Satisfied with the service.",
    "Quick response.",
    "Good communication.",
    "Could be improved.",
    "Thank you for your help.",
    "Highly recommended.",
]


def generate_volunteer_rating(count: int = 100) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    request_ids = make_request_ids(count)
    user_ids = make_user_ids(count)

    for index in range(count):
        updated_at = random_created_at(index) + timedelta(
            days=random.randint(1, 15),
            hours=random.randint(0, 12),
            minutes=random.randint(0, 59),
        )

        rows.append({
            "volunteer_rating_id": index + 1,
            "user_id": random.choice(user_ids),
            "request_id": request_ids[index],
            "rating": random.choice(RATINGS),
            "feedback": random.choice(FEEDBACK),
            "last_update_date": format_ts(updated_at),
        })

    return rows
