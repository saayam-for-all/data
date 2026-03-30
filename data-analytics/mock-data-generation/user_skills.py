from datetime import datetime, timedelta
from typing import Dict, List

from utils import build_skill_map, format_date


def generate_user_skills(volunteer_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    skill_map = build_skill_map(volunteer_rows)
    rows: List[Dict[str, str]] = []

    for volunteer_row in volunteer_rows:
        user_id = volunteer_row["user_id"]
        created_at = datetime.strptime(volunteer_row["created_at"], "%Y-%m-%d %H:%M").date()

        for cat_id in skill_map[user_id]:
            rows.append({
                "user_id": user_id,
                "cat_id": cat_id,
                "created_date": format_date(created_at),
                "last_update_date": format_date(created_at + timedelta(days=0)),
            })

    return rows
