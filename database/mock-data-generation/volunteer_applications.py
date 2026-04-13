import json
import random
import uuid

from utils import (
    GLOBAL_DATA,
    AVAILABILITY_OPTIONS,
    APPLICATION_STATUSES,
    random_created_at,
)

# Generates mock volunteer application records for each user.
def generate_volunteer_applications():
    rows = []

    users = GLOBAL_DATA["users"]
    categories = GLOBAL_DATA["categories"]

    for i, user_id in enumerate(users):
        created_at = random_created_at(i)

        skills = random.sample(categories, k=min(3, len(categories)))

        rows.append({
            "user_id": user_id,
            "terms_and_conditions": True,
            "terms_accepted_at": created_at,
            "govt_id_path": f"/uploads/{uuid.uuid4()}.pdf",
            "path_updated_at": created_at,
            "skill_codes": json.dumps(skills),
            "availability": json.dumps(random.choice(AVAILABILITY_OPTIONS)),
            "current_page": random.randint(1, 5),
            "application_status": random.choice(APPLICATION_STATUSES),
            "is_completed": random.choice([True, False]),
            "created_at": created_at,
            "last_updated_at": created_at,
        })

    return rows