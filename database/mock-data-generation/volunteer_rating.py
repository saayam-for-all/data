import random
from datetime import timedelta
from typing import Dict, List

from utils import format_ts, make_user_ids, random_created_at

RATINGS = [1, 2, 3, 4, 5]
RATING_WEIGHTS = [3, 5, 15, 40, 37]

FEEDBACK_TEMPLATES = {
    5: [
        "Excellent volunteer! Went above and beyond to help.",
        "Very responsive and caring. Solved my issue quickly.",
        "Outstanding support. Truly grateful for the help.",
        "Best experience I have had. Highly recommend this volunteer.",
        "Prompt, professional, and genuinely kind. Thank you!",
    ],
    4: [
        "Very helpful volunteer. Addressed most of my needs.",
        "Good communication and follow-through on the request.",
        "Solid support overall. Would work with them again.",
        "Helpful and friendly. Just needed a bit more follow-up.",
        "Reliable and knowledgeable. Handled the request well.",
    ],
    3: [
        "Decent help but took longer than expected.",
        "Average experience. Could improve on communication.",
        "The volunteer tried their best but resources were limited.",
        "Okay support. Some aspects could have been handled better.",
        "Satisfactory help. Met the basic requirements.",
    ],
    2: [
        "Volunteer was hard to reach and slow to respond.",
        "The help provided did not fully address my needs.",
        "Communication was lacking throughout the process.",
        "Expected more effort and follow-through.",
        "Below average experience. Room for improvement.",
    ],
    1: [
        "Unfortunately the volunteer did not follow through.",
        "Very poor communication. Request was not handled.",
        "Did not receive any meaningful assistance.",
    ],
}


def make_request_ids(count: int) -> List[str]:
    return [f"REQ{1000 + i}" for i in range(count)]


def generate_volunteer_rating(
    count: int = 100,
    user_ids: List[str] = None,
    request_ids: List[str] = None,
) -> List[Dict[str, str]]:
    if user_ids is None:
        user_ids = make_user_ids(count)
    if request_ids is None:
        request_ids = make_request_ids(count)

    rows: List[Dict[str, str]] = []

    for i in range(count):
        rating = random.choices(RATINGS, weights=RATING_WEIGHTS, k=1)[0]
        last_update = random_created_at(i) + timedelta(
            days=random.randint(1, 14),
            hours=random.randint(0, 12),
            minutes=random.randint(0, 59),
        )

        rows.append({
            "volunteer_rating_id": i + 1,
            "user_id": random.choice(user_ids),
            "request_id": random.choice(request_ids),
            "rating": rating,
            "feedback": random.choice(FEEDBACK_TEMPLATES[rating]),
            "last_update_date": format_ts(last_update),
        })

    return rows
