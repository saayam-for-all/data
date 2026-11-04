import random
from datetime import timedelta
from typing import Dict, List

from utils import format_ts, random_created_at


def generate_users(count: int = 100) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    for index in range(count):
        user_id = f"U{1000 + index}"

        created_at = random_created_at(index)
        last_updated = created_at + timedelta(
            days=random.randint(0, 10),
            hours=random.randint(0, 12),
        )

        rows.append({
            "user_id": user_id,
            "state_id": "S1",
            "country_id": 1,
            "user_status_id": 1,
            "user_category_id": 1,
            "full_name": f"User {index}",
            "first_name": f"First{index}",
            "middle_name": "",
            "last_name": f"Last{index}",
            "primary_email_address": f"user{index}@example.com",
            "primary_phone_number": f"999999{index:04d}",
            "addr_ln1": "123 Main St",
            "addr_ln2": "",
            "addr_ln3": "",
            "city_name": "Sample City",
            "zip_code": "10001",
            "last_location": "Sample Location",
            "last_update_date": format_ts(last_updated),
            "time_zone": "UTC",
            "profile_picture_path": "",
            "gender": random.choice(["Male", "Female"]),
            "language_1": "English",
            "language_2": "",
            "language_3": "",
            "promotion_wizard_stage": 1,
            "promotion_wizard_last_update_date": format_ts(last_updated),
            "external_auth_provider": "LOCAL",
            "dob": "1990-01-01",
        })

    return rows