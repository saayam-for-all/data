import random
from datetime import timedelta
from typing import Dict, List

from utils import format_ts, random_created_at


def generate_request(count: int = 100) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    for index in range(count):
        req_id = f"R{1000 + index}"

        submission_date = random_created_at(index)
        serviced_date = submission_date + timedelta(
            days=random.randint(1, 10),
            hours=random.randint(0, 12),
        )
        last_update_date = serviced_date + timedelta(
            days=random.randint(0, 5),
            hours=random.randint(0, 6),
        )

        rows.append({
            "req_id": req_id,
            "req_user_id": f"U{1000 + index}",
            "req_for_id": 1,
            "req_islead_id": 1,
            "req_cat_id": "1",
            "req_type_id": 1,
            "req_priority_id": 1,
            "req_status_id": 1,
            "req_loc": "Sample Location",
            "iscalamity": random.choice(["TRUE", "FALSE"]),
            "req_subj": f"Help Request {index}",
            "req_desc": f"This is a sample help request description {index}",
            "req_doc_link": "",
            "audio_req_desc": "",
            "submission_date": format_ts(submission_date),
            "serviced_date": format_ts(serviced_date),
            "last_update_date": format_ts(last_update_date),
            "to_public": random.choice(["TRUE", "FALSE"]),
        })

    return rows