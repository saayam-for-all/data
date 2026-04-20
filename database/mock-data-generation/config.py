"""
config.py
---------
Single source of truth for all tunables in the mock-data generation pipeline.

Changing a value here propagates to every generator automatically.
No magic numbers should appear in generators.py or generate_mock_data.py.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------

SCRIPT_DIR: Path = Path(__file__).resolve().parent
DB_INFO_PATH: Path = SCRIPT_DIR / "db_info.json"
LOOKUP_DIR: Path = SCRIPT_DIR.parent / "lookup_tables"
OUTPUT_DIR: Path = SCRIPT_DIR.parent / "mock_db"

# ---------------------------------------------------------------------------
# Global random seed
# ---------------------------------------------------------------------------

DEFAULT_SEED: int = 42

# ---------------------------------------------------------------------------
# Row-count targets per mode
#
# "dev"  – small, fast, good for local iteration and CI smoke tests
# "full" – production-scale targets (5 000 users / 20 000 requests)
#
# Tables driven by a ratio (e.g. volunteers = N% of users) are expressed
# as floats between 0 and 1 under the "ratios" sub-key.
# Tables whose counts are derived from other tables (e.g. user_skills comes
# from volunteer_applications.skill_codes) have no entry here — their
# generators compute the count themselves.
# ---------------------------------------------------------------------------

ROW_COUNTS: dict[str, dict] = {
    "dev": {
        "counts": {
            # Independent / lookup-adjacent
            "action": 10,
            "identity_type": 10,
            "sla": 5,
            "news_snippets": 10,
            "user_signoff": 10,
            "volunteer_organizations": 10,
            "city": 30,
            "emergency_numbers": 20,
            "organizations": 15,
            # Core entities
            "users": 50,
            "meetings": 5,
            # Request pipeline
            "request": 200,
            "request_comments": 60,   # across all requests
            "req_add_info": 140,       # across all requests
            "notifications": 100,
            "volunteers_assigned": 300,
            "volunteer_rating": 80,
        },
        "ratios": {
            # fraction of users that appear in each child table
            "volunteer_applications": 0.40,
            "volunteer_details": 0.15,
            "volunteer_locations": 0.15,
            "user_additional_details": 0.80,
            "user_availability": 0.70,
            "user_locations": 0.60,
            "user_notification_preferences": 0.90,
            "user_notification_status": 0.95,
            "user_org_map": 0.10,
            "fraud_requests": 0.05,
            # fraction of requests that have guest details
            "request_guest_details": 0.20,
            # fraction of meetings that create participant rows (avg participants)
            "meeting_participants_per_meeting": 4,
        },
    },
    "full": {
        "counts": {
            # Independent / lookup-adjacent
            "action": 30,
            "identity_type": 20,
            "sla": 10,
            "news_snippets": 100,
            "user_signoff": 100,
            "volunteer_organizations": 100,
            "city": 500,
            "emergency_numbers": 250,
            "organizations": 500,
            # Core entities
            "users": 5_000,
            "meetings": 200,
            # Request pipeline
            "request": 20_000,
            "request_comments": 6_000,
            "req_add_info": 14_000,
            "notifications": 10_000,
            "volunteers_assigned": 25_000,
            "volunteer_rating": 8_000,
        },
        "ratios": {
            "volunteer_applications": 0.30,
            "volunteer_details": 0.15,
            "volunteer_locations": 0.15,
            "user_additional_details": 0.80,
            "user_availability": 0.70,
            "user_locations": 0.60,
            "user_notification_preferences": 0.90,
            "user_notification_status": 0.95,
            "user_org_map": 0.10,
            "fraud_requests": 0.02,
            "request_guest_details": 0.20,
            "meeting_participants_per_meeting": 6,
        },
    },
}

# ---------------------------------------------------------------------------
# Enum / domain values that are not declared in db_info.json
#
# Keys match the pattern  "<table>.<column>"  so relationship_resolver.py
# and generators.py can look them up without hard-coding table logic.
# ---------------------------------------------------------------------------

ENUM_VALUES: dict[str, list] = {
    "volunteer_applications.application_status": [
        "DRAFT",
        "IN_PROGRESS",
        "SUBMITTED",
        "UNDER_REVIEW",
        "APPROVED",
    ],
    # volunteer_rating.rating  (1–5 integer star rating)
    "volunteer_rating.rating": [1, 2, 3, 4, 5],
    # notifications.status
    "notifications.status": ["PENDING", "SENT", "FAILED", "READ"],
    # user_notification_preferences.preference
    "user_notification_preferences.preference": ["ENABLED", "DISABLED"],
    # organizations.org_type
    "organizations.org_type": [
        "NON_PROFIT",
        "NGO",
        "GOVERNMENT",
        "COMMUNITY",
        "CORPORATE",
    ],
    # organizations.source
    "organizations.source": ["MANUAL", "SCRAPED", "PARTNER"],
    # users.external_auth_provider
    "users.external_auth_provider": ["GOOGLE", "FACEBOOK", "APPLE", "LOCAL"],
    # users.gender  (open-ended varchar in schema, but constrained in practice)
    "users.gender": ["MALE", "FEMALE", "NON_BINARY", "PREFER_NOT_TO_SAY"],
    # request_guest_details.req_gender
    "request_guest_details.req_gender": [
        "MALE",
        "FEMALE",
        "NON_BINARY",
        "PREFER_NOT_TO_SAY",
    ],
    # user_availability.day_of_week
    "user_availability.day_of_week": [
        "MONDAY",
        "TUESDAY",
        "WEDNESDAY",
        "THURSDAY",
        "FRIDAY",
        "SATURDAY",
        "SUNDAY",
    ],
    # volunteer_details / volunteer_applications availability days
    "volunteer_details.availability_days": [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ],
    "volunteers_assigned.volunteer_type": ["IN_PERSON", "REMOTE"],
    # action.action_desc  (sample values)
    "action.action_desc": [
        "CREATE_REQUEST",
        "UPDATE_REQUEST",
        "CANCEL_REQUEST",
        "ASSIGN_VOLUNTEER",
        "CLOSE_REQUEST",
        "FLAG_FRAUD",
        "SEND_NOTIFICATION",
    ],
    # identity_type.identity_value
    "identity_type.identity_value": [
        "PASSPORT",
        "DRIVERS_LICENSE",
        "NATIONAL_ID",
        "STATE_ID",
        "MILITARY_ID",
        "STUDENT_ID",
    ],
    # news_snippets profile_links keys
    "news_snippets.profile_links_keys": [
        "linkedin",
        "twitter",
        "facebook",
        "instagram",
        "website",
    ],
    # user_signoff.reason
    "user_signoff.reason": [
        "COMPLETED_TASK",
        "SESSION_EXPIRED",
        "USER_REQUESTED",
        "ADMIN_ACTION",
        "INACTIVITY",
    ],
}

# ---------------------------------------------------------------------------
# Per-column generation overrides
#
# When the generic type-driven generator is not enough, register an override
# here.  The key is "<table>.<column>" and the value is a plain dict that
# generators.py interprets.  Supported override kinds:
#
#   {"kind": "constant",  "value": <v>}
#       — always emit this fixed value
#   {"kind": "enum",      "key": "<table>.<column>"}
#       — sample from ENUM_VALUES[key]
#   {"kind": "fk_pool",   "pool": "<context_key>"}
#       — sample from context[pool] (a list of generated PKs)
#   {"kind": "template",  "pattern": "<str with {user_id} etc.>"}
#       — format string; available vars are the row dict being built
# ---------------------------------------------------------------------------

COLUMN_OVERRIDES: dict[str, dict] = {
    # File paths
    "volunteer_applications.govt_id_path": {
        "kind": "template",
        "pattern": "/mock-storage/kyc/{user_id}/govt_id_front.pdf",
    },
    "volunteer_details.govt_id_path1": {
        "kind": "template",
        "pattern": "/mock-storage/kyc/{user_id}/govt_id_front.pdf",
    },
    "volunteer_details.govt_id_path2": {
        "kind": "template",
        "pattern": "/mock-storage/kyc/{user_id}/govt_id_back.pdf",
    },
    "news_snippets.image_path": {
        "kind": "template",
        "pattern": "/assets/news/{news_id}.jpg",
    },
    # Boolean columns that should default to TRUE rather than random
    "volunteer_applications.terms_and_conditions": {
        "kind": "weighted_bool",
        "true_weight": 0.97,
    },
    "volunteer_details.terms_and_conditions": {
        "kind": "constant",
        "value": "true",
    },
    "request.to_public": {
        "kind": "weighted_bool",
        "true_weight": 0.75,
    },
    "request.iscalamity": {
        "kind": "weighted_bool",
        "true_weight": 0.05,
    },
    "volunteer_applications.is_completed": {
        "kind": "weighted_bool",
        "true_weight": 0.82,
    },
    "request_comments.isdeleted": {
        "kind": "weighted_bool",
        "true_weight": 0.04,
    },
    # Pagination / wizard stage fields
    "volunteer_applications.current_page": {
        "kind": "randint",
        "low": 1,
        "high": 5,
    },
    "users.promotion_wizard_stage": {
        "kind": "randint",
        "low": 0,
        "high": 4,
    },
    # Rating integer (separate from enum — stored as integer in schema)
    "organizations.rating": {
        "kind": "randint",
        "low": 1,
        "high": 5,
    },
    "volunteer_rating.rating": {
        "kind": "randint",
        "low": 1,
        "high": 5,
    },
    # Household / count integers
    "request_guest_details.req_age": {
        "kind": "randint",
        "low": 18,
        "high": 85,
    },
    "emergency_numbers.is_country": {
        "kind": "weighted_bool",
        "true_weight": 0.60,
    },
}

# ---------------------------------------------------------------------------
# Date / timestamp range for generated data
# All generated timestamps fall within [DATA_START, DATA_END].
# ---------------------------------------------------------------------------

DATA_START_YEAR: int = 2024
DATA_START_MONTH: int = 1
DATA_START_DAY: int = 1

DATA_END_YEAR: int = 2026
DATA_END_MONTH: int = 4
DATA_END_DAY: int = 15

TIMESTAMP_FORMAT: str = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT: str = "%Y-%m-%d"

# ---------------------------------------------------------------------------
# User ID format
# ---------------------------------------------------------------------------

USER_ID_PREFIX: str = "U"
USER_ID_ZERO_PAD: int = 5   # e.g. U00001 … U05000

# ---------------------------------------------------------------------------
# Request ID format
# ---------------------------------------------------------------------------

REQUEST_ID_PREFIX: str = "REQ"
REQUEST_ID_ZERO_PAD: int = 6  # e.g. REQ000001 … REQ020000

# ---------------------------------------------------------------------------
# Org ID format
# ---------------------------------------------------------------------------

ORG_ID_PREFIX: str = "ORG"
ORG_ID_ZERO_PAD: int = 5  # e.g. ORG00001

# ---------------------------------------------------------------------------
# Tables whose data comes entirely from lookup_tables/ CSVs (not generated).
# The pipeline copies them to OUTPUT_DIR as-is so mock_db/ is self-contained.
# ---------------------------------------------------------------------------

LOOKUP_ONLY_TABLES: list[str] = [
    "country",
    "state",
    "help_categories",
    "help_categories_map",
    "req_add_info_metadata",
    "list_item_metadata",
    "notification_channels",
    "notification_types",
    "request_for",
    "request_isleadvol",
    "request_priority",
    "request_status",
    "request_type",
    "user_category",
    "user_status",
    "supporting_languages",
]

# ---------------------------------------------------------------------------
# Geography bounding box for WKT POINT generation
# Defaults to continental United States.
# ---------------------------------------------------------------------------

GEO_LAT_MIN: float = 25.0
GEO_LAT_MAX: float = 49.0
GEO_LON_MIN: float = -124.0
GEO_LON_MAX: float = -67.0
