import random
from datetime import timedelta
from typing import Dict, List

from utils import (
    AVAILABILITY_OPTIONS,
    STATUSES,
    USABLE_CAT_IDS,
    format_ts,
    json_text,
    make_user_ids,
    random_created_at,
)


def generate_volunteer_applications(count: int = 100) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    user_ids = make_user_ids(count)

    for index, user_id in enumerate(user_ids):
        created_at = random_created_at(index)

        terms_and_conditions = random.random() > 0.03
        terms_accepted_at = created_at + timedelta(minutes=random.randint(0, 180)) if terms_and_conditions else None
        path_updated_at = (terms_accepted_at or created_at) + timedelta(minutes=random.randint(0, 240))

        skill_count = random.randint(2, 4)
        skills = random.sample(USABLE_CAT_IDS, skill_count)

        is_completed = random.random() > 0.18
        application_status = random.choices(STATUSES, weights=[5, 12, 45, 20, 18], k=1)[0]

        if is_completed and application_status in {"DRAFT", "IN_PROGRESS"}:
            application_status = "SUBMITTED"
        if not is_completed and application_status == "APPROVED":
            application_status = "UNDER_REVIEW"

        current_page = random.randint(1, 5 if not is_completed else 4)
        last_updated_at = path_updated_at + timedelta(
            days=random.randint(0, 10),
            hours=random.randint(0, 12),
            minutes=random.randint(0, 59),
        )

        rows.append({
            "user_id": user_id,
            "terms_and_conditions": str(terms_and_conditions).upper(),
            "terms_accepted_at": format_ts(terms_accepted_at) if terms_accepted_at else "",
            "govt_id_path": f"/uploads/id/{user_id}.pdf",
            "path_updated_at": format_ts(path_updated_at),
            "skill_codes": json_text(skills),
            "availability": json_text(random.choice(AVAILABILITY_OPTIONS)),
            "current_page": current_page,
            "application_status": application_status,
            "is_completed": str(is_completed).upper(),
            "created_at": format_ts(created_at),
            "last_updated_at": format_ts(last_updated_at),
        })

    return rows
