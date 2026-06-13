import random
from datetime import timedelta
from typing import Dict, List

from utils import format_ts, make_user_ids, random_created_at

COMMENT_TEMPLATES = [
    "I can help with this request. Please reach out to me.",
    "Have you tried contacting your local community center for assistance?",
    "I know a few organizations in the area that can help with this.",
    "Updating status: we are currently working on this request.",
    "Thank you for submitting this request. A volunteer will be assigned shortly.",
    "I have experience with this type of request. Happy to assist.",
    "Please provide more details about your location so we can connect you with nearby resources.",
    "This request has been forwarded to the appropriate volunteer team.",
    "I spoke with the requester and they need assistance by end of this week.",
    "We have a volunteer available in your area. They will reach out soon.",
    "Can someone with expertise in this category please take a look?",
    "The requester has been contacted and we are working on a solution.",
    "I recommend reaching out to the Salvation Army for immediate assistance.",
    "Just checking in — has anyone been able to help with this request yet?",
    "I will be visiting the area tomorrow and can provide in-person support.",
    "Requester confirmed they received the help. Marking as resolved.",
    "We need more volunteers for this type of request in this region.",
    "I left a voicemail with the requester. Will follow up again tomorrow.",
    "This is a high priority request. Please prioritize accordingly.",
    "Coordinating with local shelter to arrange temporary housing.",
    "The requester mentioned they also need help with transportation.",
    "Great work team! This request was handled very efficiently.",
    "I have attached some useful resources for the requester.",
    "Please note the requester prefers communication in Spanish.",
    "Volunteer has been matched. Awaiting confirmation from requester.",
]


def make_request_ids(count: int) -> List[str]:
    return [f"REQ{1000 + i}" for i in range(count)]


def generate_request_comments(
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
        created_at = random_created_at(i)
        is_edited = random.random() > 0.75
        last_updated_at = (
            created_at + timedelta(
                hours=random.randint(1, 48),
                minutes=random.randint(0, 59),
            )
            if is_edited
            else created_at
        )
        is_deleted = random.random() > 0.92

        rows.append({
            "comment_id": i + 1,
            "req_id": random.choice(request_ids),
            "commenter_id": random.choice(user_ids),
            "comment_desc": random.choice(COMMENT_TEMPLATES),
            "created_at": format_ts(created_at),
            "last_updated_at": format_ts(last_updated_at),
            "isdeleted": str(is_deleted).upper(),
        })

    return rows
