import random
from typing import List, Dict, Set, Tuple
from datetime import datetime

from utils import GLOBAL_DATA, NUM_RECORDS


def generate_user_skills() -> List[Dict]:
    rows = []
    seen: Set[Tuple[str, str]] = set()

    users = GLOBAL_DATA["users"]
    categories = GLOBAL_DATA["categories"]

    for _ in range(NUM_RECORDS):
        user_id = random.choice(users)
        cat_id = random.choice(categories)

        if (user_id, cat_id) in seen:
            continue

        seen.add((user_id, cat_id))

        # Single source of truth timestamp (like volunteer_applications)
        base_time = datetime.now()

        rows.append({
            "user_id": user_id,
            "cat_id": cat_id,
            "created_date": base_time,
            "last_update_date": base_time
        })

    return rows