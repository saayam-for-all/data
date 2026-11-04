import random
from datetime import timedelta
from typing import Dict, List, Sequence

from utils import format_ts, random_created_at


def generate_request_comments(
    request_rows: Sequence[Dict[str, str]],
    user_rows: Sequence[Dict[str, str]],
    count: int = 100,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    request_ids = [row["req_id"] for row in request_rows]
    user_ids = [row["user_id"] for row in user_rows]

    for index in range(count):
        created_at = random_created_at(index)
        last_updated_at = created_at + timedelta(
            days=random.randint(0, 3),
            hours=random.randint(0, 6),
            minutes=random.randint(0, 59),
        )

        rows.append({
            "comment_id": 10000 + index,
            "req_id": random.choice(request_ids),
            "commenter_id": random.choice(user_ids),
            "comment_desc": f"Sample comment {index} for request follow-up and coordination.",
            "created_at": format_ts(created_at),
            "last_updated_at": format_ts(last_updated_at),
            "isdeleted": random.choice(["TRUE", "FALSE"]),
        })

    return rows