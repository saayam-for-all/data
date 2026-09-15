"""Shared helpers for Saayam mock-data generation (issue #301).

Pure standard library - no external dependencies required beyond stdlib,
so this runs on any machine with Python 3.8+.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

def set_seed(seed: int = 42) -> None:
    random.seed(seed)


# ---------------------------------------------------------------------------
# Reference data (small, realistic, hand-picked - not the full real world,
# just enough variety to exercise every relationship in the schema)
# ---------------------------------------------------------------------------

COUNTRIES = [
    # (country_name, phone_code, country_code, is_eu_member)
    ("United States", "+1", "US", False),
    ("Canada", "+1", "CA", False),
    ("India", "+91", "IN", False),
    ("Germany", "+49", "DE", True),
    ("Ireland", "+353", "IE", True),
]

# US states used as the primary pool, since Saayam's live deployment is
# "Virginia" schema-scoped - keeping most rows realistically US-based.
US_STATES = [
    # (state_name, state_code)
    ("Virginia", "VA"), ("Maryland", "MD"), ("North Carolina", "NC"),
    ("California", "CA"), ("Texas", "TX"), ("New York", "NY"),
    ("Ohio", "OH"), ("Pennsylvania", "PA"), ("Georgia", "GA"),
    ("Florida", "FL"),
]

# Cities with approximate real centroids (lat, lon), grouped by state code.
CITIES_BY_STATE = {
    "VA": [("Richmond", 37.5407, -77.4360), ("Norfolk", 36.8508, -76.2859),
           ("Arlington", 38.8816, -77.0910), ("Roanoke", 37.2710, -79.9414)],
    "MD": [("Baltimore", 39.2904, -76.6122), ("Annapolis", 38.9784, -76.4922)],
    "NC": [("Charlotte", 35.2271, -80.8431), ("Raleigh", 35.7796, -78.6382)],
    "CA": [("San Jose", 37.3382, -121.8863), ("Sacramento", 38.5816, -121.4944)],
    "TX": [("Austin", 30.2672, -97.7431), ("Dallas", 32.7767, -96.7970)],
    "NY": [("Albany", 42.6526, -73.7562), ("Buffalo", 42.8864, -78.8784)],
    "OH": [("Columbus", 39.9612, -82.9988), ("Cleveland", 41.4993, -81.6944)],
    "PA": [("Philadelphia", 39.9526, -75.1652), ("Pittsburgh", 40.4406, -79.9959)],
    "GA": [("Atlanta", 33.7490, -84.3880), ("Savannah", 32.0809, -81.0912)],
    "FL": [("Orlando", 28.5383, -81.3792), ("Tampa", 27.9506, -82.4572)],
}

FIRST_NAMES = [
    "Priya", "Rohan", "Maria", "John", "Aisha", "David", "Emily", "Carlos",
    "Sophia", "Ahmed", "Daniel", "Neha", "Liam", "Zara", "Noah", "Fatima",
    "Ethan", "Maya", "Ibrahim", "Chloe", "Omar", "Harper", "Victor", "Nina",
]
LAST_NAMES = [
    "Kapoor", "Singh", "Lopez", "Smith", "Khan", "Lee", "Chen", "Martinez",
    "Brown", "Ali", "Wilson", "Patel", "Johnson", "Ahmed", "Walker", "Sheikh",
    "Anderson", "Krishnan", "Scott", "Menon", "Gupta", "Roy", "Iyer", "Nair",
]

HELP_CATEGORIES = [
    # (cat_id, cat_name, cat_desc) - this is the FULL, real help_category.csv
    # pulled directly from data-analytics/sql/help_category.csv in this repo
    # (not a hand-picked subset), so cat_id values here line up exactly with
    # what the rest of the codebase already uses.
    ("0.0.0.0.0", "GENERAL_CATEGORY", "GENERAL_CATEGORY_DESC"),
    ("1", "FOOD_AND_ESSENTIALS", "FOOD_AND_ESSENTIALS_DESC"),
    ("1.1", "FOOD_ASSISTANCE", "FOOD_ASSISTANCE_DESC"),
    ("1.2", "GROCERY_SHOPPING_AND_DELIVERY", "GROCERY_SHOPPING_AND_DELIVERY_DESC"),
    ("1.3", "COOKING_HELP", "COOKING_HELP_DESC"),
    ("1.3.1", "MEAL_PREP_BASIC", "MEAL_PREP_BASIC_DESC"),
    ("1.3.2", "FESTIVE_OR_BULK_COOKING", "FESTIVE_OR_BULK_COOKING_DESC"),
    ("1.3.3", "NUTRITIONAL_MEAL_PLANNING", "NUTRITIONAL_MEAL_PLANNING_DESC"),
    ("1.3.4", "CULTURAL_CUISINE_GUIDANCE", "CULTURAL_CUISINE_GUIDANCE_DESC"),
    ("1.3.5", "OTHER_COOKING_HELP", "OTHER_COOKING_HELP_DESC"),
    ("2", "CLOTHING_ASSISTANCE", "CLOTHING_ASSISTANCE_DESC"),
    ("2.1", "DONATE_CLOTHES", "DONATE_CLOTHES_DESC"),
    ("2.2", "BORROW_CLOTHES", "BORROW_CLOTHES_DESC"),
    ("2.3", "EMERGENCY_CLOTHING_ASSISTANCE", "EMERGENCY_CLOTHING_ASSISTANCE_DESC"),
    ("2.4", "TAILORING", "TAILORING_DESC"),
    ("3", "HOUSING_ASSISTANCE", "HOUSING_ASSISTANCE_DESC"),
    ("3.1", "LEASE_SUPPORT", "LEASE_SUPPORT_DESC"),
    ("3.2", "TENANT_RENT_SUPPORT", "TENANT_RENT_SUPPORT_DESC"),
    ("3.3", "REPAIR_MAINTENANCE_SUPPORT", "REPAIR_MAINTENANCE_SUPPORT_DESC"),
    ("3.3.1", "PLUMBING", "PLUMBING_DESC"),
    ("3.3.2", "HANDYMAN", "HANDYMAN_DESC"),
    ("3.3.3", "ELECTRICIAN", "ELECTRICIAN_DESC"),
    ("3.3.4", "CARPENTRY", "CARPENTRY_DESC"),
    ("3.3.5", "GARDEN", "GARDEN_DESC"),
    ("3.3.6", "HVAC_AIR_CONDITIONING", "HVAC_AIR_CONDITIONING_DESC"),
    ("3.3.7", "ROOFING", "ROOFING_DESC"),
    ("3.3.8", "LOCKSMITH", "LOCKSMITH_DESC"),
    ("3.3.9", "PAINTING", "PAINTING_DESC"),
    ("3.3.10", "MASONRY_OR_CONCRETE", "MASONRY_OR_CONCRETE_DESC"),
    ("3.3.11", "METALWORK_OR_WELDING", "METALWORK_OR_WELDING_DESC"),
    ("3.3.12", "POOL_AND_SPA_MAINTENANCE", "POOL_AND_SPA_MAINTENANCE_DESC"),
    ("3.3.13", "OTHER_REPAIR_MAINTENANCE_SUPPORT", "OTHER_REPAIR_MAINTENANCE_SUPPORT_DESC"),
    ("3.4", "UTILITIES_SETUP_SUPPORT", "UTILITIES_SETUP_SUPPORT_DESC"),
    ("3.5", "LOOKING_FOR_RENTAL", "LOOKING_FOR_RENTAL_DESC"),
    ("3.6", "FIND_ROOMATE", "FIND_ROOMATE_DESC"),
    ("3.7", "MOVE_IN_HELP", "MOVE_IN_HELP_DESC"),
    ("3.8", "BOOKING_PACKERS_MOVERS_SUPPORT", "BOOKING_PACKERS_MOVERS_SUPPORT_DESC"),
    ("3.9", "BUY_THINGS", "BUY_THINGS_DESC"),
    ("3.10", "SELL_THINGS", "SELL_THINGS_DESC"),
    ("4", "EDUCATION_CAREER_SUPPORT", "EDUCATION_CAREER_SUPPORT_DESC"),
    ("4.1", "COLLEGE_APPLICATION_HELP", "COLLEGE_APPLICATION_HELP_DESC"),
    ("4.2", "SOP_ESSAY_REVIEW", "SOP_ESSAY_REVIEW_DESC"),
    ("4.3", "TUTORING", "TUTORING_DESC"),
    ("4.3.1", "MATH", "MATH_DESC"),
    ("4.3.2", "ENGLISH", "ENGLISH_DESC"),
    ("4.3.3", "SCIENCE", "SCIENCE_DESC"),
    ("4.3.4", "COMPUTER_SCIENCE", "COMPUTER_SCIENCE_DESC"),
    ("4.3.5", "TEST_PREP", "TEST_PREP_DESC"),
    ("4.3.6", "OTHER_SUBJECTS", "OTHER_SUBJECTS_DESC"),
    ("4.4", "SCHOLARSHIP_KNOWLEDGE", "SCHOLARSHIP_KNOWLEDGE_DESC"),
    ("4.5", "STUDY_GROUP_FORMATION", "STUDY_GROUP_FORMATION_DESC"),
    ("4.6", "CAREER_GUIDANCE", "CAREER_GUIDANCE_DESC"),
    ("4.7", "EDUCATION_RESOURCE_SHARING", "EDUCATION_RESOURCE_SHARING_DESC"),
    ("5", "HEALTHCARE_AND_WELLNESS", "HEALTHCARE_AND_WELLNESS_DESC"),
    ("5.1", "MEDICAL_CONSULTATION", "MEDICAL_CONSULTATION_DESC"),
    ("5.1.1", "GENERAL_CONSULTATION", "GENERAL_CONSULTATION_DESC"),
    ("5.1.2", "ENT(EAR_NOSE_AND_THROAT)", "ENT(EAR_NOSE_AND_THROAT)_DESC"),
    ("5.1.3", "DENTAL_OR_ORAL_HEALTH", "DENTAL_OR_ORAL_HEALTH_DESC"),
    ("5.1.4", "EYE_OR_VISION_CARE", "EYE_OR_VISION_CARE_DESC"),
    ("5.1.5", "CARDIAC_OR_BLOOD_PRESSURE", "CARDIAC_OR_BLOOD_PRESSURE_DESC"),
    ("5.1.6", "ORTHOPEDIC_OR_PHYSIOTHERAPY", "ORTHOPEDIC_OR_PHYSIOTHERAPY_DESC"),
    ("5.1.7", "SKIN_OR_DERMATOLOGY", "SKIN_OR_DERMATOLOGY_DESC"),
    ("5.1.8", "WOMENS_OR_REPRODUCTIVE_HEALTH", "WOMENS_OR_REPRODUCTIVE_HEALTH_DESC"),
    ("5.1.9", "VACCINATIONS_AND_PREVENTIVE_SCREENINGS", "VACCINATIONS_AND_PREVENTIVE_SCREENINGS_DESC"),
    ("5.1.10", "PEDIATRICS_OR_CHILD_HEALTH", "PEDIATRICS_OR_CHILD_HEALTH_DESC"),
    ("5.1.11", "OTHER_MEDICAL_CONCERN", "OTHER_MEDICAL_CONCERN_DESC"),
    ("5.2", "MEDICINE_DELIVERY", "MEDICINE_DELIVERY_DESC"),
    ("5.3", "MENTAL_WELLBEING_SUPPORT", "MENTAL_WELLBEING_SUPPORT_DESC"),
    ("5.4", "MEDICATION_REMINDERS", "MEDICATION_REMINDERS_DESC"),
    ("5.5", "HEALTH_EDUCATION_GUIDANCE", "HEALTH_EDUCATION_GUIDANCE_DESC"),
    ("6", "ELDERLY_COMMUNITY_ASSISTANCE", "ELDERLY_COMMUNITY_ASSISTANCE_DESC"),
    ("6.1", "SENIOR_RELOCATION_SUPPORT", "SENIOR_RELOCATION_SUPPORT_DESC"),
    ("6.2", "DIGITAL_SUPPORT_FOR_SENIORS", "DIGITAL_SUPPORT_FOR_SENIORS_DESC"),
    ("6.3", "MEDICATION_MANAGEMENT", "MEDICATION_MANAGEMENT_DESC"),
    ("6.4", "MEDICAL_DEVICES_SETUP", "MEDICAL_DEVICES_SETUP_DESC"),
    ("6.5", "ERRANDS_EVENTS_TRANSPORTATION", "ERRANDS_EVENTS_TRANSPORTATION_DESC"),
    ("6.6", "TRANSPORTATION_APPOINTMENTS_EVENTS", "TRANSPORTATION_APPOINTMENTS_EVENTS_DESC"),
    ("6.7", "SCHEDULING_APPOINTMENTS_OR_TASKS", "SCHEDULINGG_APPOINTMENTS_OR_TASKS_DESC"),
    ("6.8", "SOCIAL_CONNECTION", "SOCIAL_CONNECTION_DESC"),
    ("6.9", "MEAL_SUPPORT", "MEAL_SUPPORT_DESC"),
]

ORG_TYPES = ["Non-Profit", "For-profit"]
ORG_SIZES = ["Small", "Medium", "Large"]

ORG_NAME_PREFIXES = ["Harbor", "Summit", "Riverside", "Maplewood", "Lakeside",
                      "Northgate", "Oakwood", "Cedar Valley", "Meadowbrook", "Unity"]
ORG_NAME_SUFFIXES = ["Veterans Support", "Community Foundation", "Food Bank",
                      "Housing Trust", "Education Fund", "Health Initiative",
                      "Senior Care Network", "Animal Rescue"]


# ---------------------------------------------------------------------------
# ID generators - formats copied from real IDs observed in this repo's own
# CSVs (SID-00-000-XXX-XXX in users.csv, ORG#####  - no dashes - in
# organizations.csv), not invented from scratch.
# ---------------------------------------------------------------------------

def make_user_id(n: int) -> str:
    return f"SID-00-000-{n:03d}-{(n * 7) % 1000:03d}"


def make_org_id(n: int) -> str:
    return f"ORG{n:05d}"


def make_city_id(n: int) -> int:
    return n


# ---------------------------------------------------------------------------
# Geography helpers
# ---------------------------------------------------------------------------

def jitter(value: float, spread: float = 0.15) -> float:
    """Nudge a coordinate randomly, staying plausibly near the source point."""
    return round(value + random.uniform(-spread, spread), 6)


def to_ewkt(lat: float, lon: float) -> str:
    """Format as SRID=4326;POINT(lon lat) - confirmed format from the
    database repo wiki ('Importing CSV rows with geography parsing...')
    and matches real volunteer_locations.csv data already in this repo.
    Note: POINT order is (longitude latitude), not (lat, lon).
    """
    return f"SRID=4326;POINT({lon} {lat})"


# ---------------------------------------------------------------------------
# Date/time helpers
# ---------------------------------------------------------------------------

def random_datetime(start_days_ago: int = 365, end_days_ago: int = 0) -> datetime:
    days_ago = random.randint(end_days_ago, start_days_ago)
    seconds_offset = random.randint(0, 86399)
    return datetime.now() - timedelta(days=days_ago, seconds=-seconds_offset)


def fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def created_and_updated_pair(start_days_ago: int = 365):
    """Return (created_at, updated_at) with created_at <= updated_at always."""
    created = random_datetime(start_days_ago, 30)
    updated = created + timedelta(days=random.randint(0, 29), hours=random.randint(0, 23))
    if updated > datetime.now():
        updated = datetime.now()
    return fmt_ts(created), fmt_ts(updated)


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

def write_csv(path: str, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)