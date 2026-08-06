import random
from datetime import timedelta
from typing import Dict, List

from utils import (
    format_ts,
    make_request_ids,
    make_user_ids,
    random_created_at,
)


COMMENTS = [
    "Request received.",
    "Volunteer assigned.",
    "Waiting for documents.",
    "Need more information.",
    "Request verified.",
    "Issue resolved.",
    "Follow-up completed.",
    "Escalated to coordinator.",
    "Volunteer contacted beneficiary.",
    "Pending approval.",
]


def generate_request_comments(count: int = 100) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    request_ids = make_request_ids(count)
    user_ids = make_user_ids(count)

    for index in range(count):
        created_at = random_created_at(index)
        updated_at = created_at + timedelta(
            days=random.randint(0, 5),
            hours=random.randint(0, 10),
            minutes=random.randint(0, 59),
        )

        rows.append({
            "comment_id": index + 1,
            "req_id": request_ids[index],
            "commenter_id": random.choice(user_ids),
            "comment_desc": random.choice(COMMENTS),
            "created_at": format_ts(created_at),
            "last_updated_at": format_ts(updated_at),
            "isdeleted": "FALSE",
        })

    return rows
