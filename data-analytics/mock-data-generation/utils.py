"""
Utility functions and constants for synthetic mock data generation.
Adheres to Virginia database schema specifications and relationship constraints.
"""

import csv
import json
import math
import os
import random
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple


def set_seed(seed: int = 42) -> None:
    """Set random seed for reproducibility."""
    random.seed(seed)


def format_ts(dt: datetime) -> str:
    """Format datetime into standard PostgreSQL compatible timestamp string."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_date(dt: datetime) -> str:
    """Format datetime into standard PostgreSQL compatible date string."""
    return dt.strftime("%Y-%m-%d")


def json_text(data: Any) -> str:
    """Serialize object into compact JSON text string."""
    return json.dumps(data, separators=(",", ":"))


def generate_sid(seq_id: int) -> str:
    """
    Generate Virginia DB compliant User ID (SID) based on sequential integer.
    Matches the schema sequence generator:
    SID-00-XXX-XXX-XXX-XXX-XXX (15 digit padded sequence).
    """
    padded = f"{seq_id:015d}"
    part1 = padded[0:3]
    part2 = padded[3:6]
    part3 = padded[6:9]
    part4 = padded[9:12]
    part5 = padded[12:15]
    return f"SID-00-{part1}-{part2}-{part3}-{part4}-{part5}"


def generate_org_id(seq_id: int) -> str:
    """Generate standardized unique Organization ID."""
    padded = f"{seq_id:013d}"
    return f"ORG-{padded[:3]}-{padded[3:6]}-{padded[6:9]}-{padded[9:]}"


def point_wkt(longitude: float, latitude: float) -> str:
    """Format geography Point into PostGIS WKT format: POINT(lon lat)."""
    return f"POINT({longitude:.6f} {latitude:.6f})"


def point_pg(latitude: float, longitude: float) -> str:
    """Format PostgreSQL native point type: (lat, lon)."""
    return f"({latitude:.6f}, {longitude:.6f})"


def jitter_coordinates(
    lat: float, lon: float, radius_km: float = 5.0
) -> Tuple[float, float]:
    """
    Generate plausible nearby coordinates within radius_km of a centroid.
    Ensures user/volunteer locations are geographically consistent with their city.
    """
    # 1 degree latitude ~ 111 km
    # 1 degree longitude ~ 111 km * cos(lat)
    r = radius_km * math.sqrt(random.random())
    theta = random.random() * 2 * math.pi

    delta_lat = (r * math.cos(theta)) / 111.0
    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-6:
        cos_lat = 1e-6
    delta_lon = (r * math.sin(theta)) / (111.0 * cos_lat)

    new_lat = max(-89.9, min(89.9, lat + delta_lat))
    new_lon = max(-179.9, min(179.9, lon + delta_lon))
    return round(new_lat, 6), round(new_lon, 6)


def write_csv(
    filepath: str,
    rows: Sequence[Dict[str, Any]],
    fieldnames: Optional[List[str]] = None,
) -> None:
    """Write list of dictionaries to a CSV file with deterministic header order."""
    if not rows and not fieldnames:
        raise ValueError(f"No rows or fieldnames provided to write {filepath}")

    if fieldnames is None:
        fieldnames = list(rows[0].keys())

    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(filepath: str) -> List[Dict[str, str]]:
    """Read CSV file into a list of row dictionaries."""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


# Reference Synthetic Name Pools
FIRST_NAMES = [
    "Alex",
    "Jordan",
    "Taylor",
    "Morgan",
    "Sam",
    "Chris",
    "Pat",
    "Robin",
    "Casey",
    "Jamie",
    "Avery",
    "Riley",
    "Logan",
    "Dakota",
    "Reese",
    "Quinn",
    "Cameron",
    "Rowan",
    "Skyler",
    "Kendall",
    "Devon",
    "Harper",
    "Finley",
    "Adrian",
    "Peyton",
    "Emerson",
    "River",
    "Jesse",
    "Alexis",
    "Angel",
    "Dallas",
    "Hayden",
    "Amara",
    "Arjun",
    "Elena",
    "Mateo",
    "Priya",
    "Chen",
    "Yuki",
    "Lars",
    "Fatima",
    "Kofi",
    "Zainab",
    "Dmitri",
    "Sofia",
    "Hassan",
    "Mei",
    "Lucia",
    "Noah",
    "Emma",
    "Liam",
    "Olivia",
    "William",
    "Ava",
    "James",
    "Isabella",
    "Oliver",
    "Sophia",
    "Benjamin",
    "Charlotte",
    "Elijah",
    "Mia",
    "Lucas",
    "Amelia",
    "Mason",
    "Harper",
    "Ethan",
    "Evelyn",
    "Alexander",
    "Abigail",
    "Henry",
    "Emily",
    "Sebastian",
    "Elizabeth",
    "Jack",
    "Mila",
    "Owen",
    "Ella",
    "Theodore",
    "Avery",
]

LAST_NAMES = [
    "Smith",
    "Johnson",
    "Williams",
    "Brown",
    "Jones",
    "Garcia",
    "Miller",
    "Davis",
    "Rodriguez",
    "Martinez",
    "Hernandez",
    "Lopez",
    "Gonzalez",
    "Wilson",
    "Anderson",
    "Thomas",
    "Taylor",
    "Moore",
    "Jackson",
    "Martin",
    "Lee",
    "Perez",
    "Thompson",
    "White",
    "Harris",
    "Sanchez",
    "Clark",
    "Ramirez",
    "Lewis",
    "Robinson",
    "Walker",
    "Young",
    "Allen",
    "King",
    "Wright",
    "Scott",
    "Torres",
    "Nguyen",
    "Hill",
    "Flores",
    "Green",
    "Adams",
    "Nelson",
    "Baker",
    "Hall",
    "Rivera",
    "Campbell",
    "Mitchell",
    "Carter",
    "Roberts",
    "Patel",
    "Sharma",
    "Kaur",
    "Singh",
    "Das",
    "Gupta",
    "Tanaka",
    "Yamamoto",
    "Sato",
    "Suzuki",
    "Watanabe",
    "Takahashi",
    "Ito",
    "Nakamura",
    "Mueller",
    "Schmidt",
    "Schneider",
    "Fischer",
    "Weber",
    "Meyer",
    "Wagner",
    "Becker",
]

ORG_NAME_PREFIXES = [
    "Global Hope",
    "Community First",
    "Beacon",
    "Caring Hands",
    "United Relief",
    "Evergreen",
    "Compassion",
    "Helping Hearts",
    "Sunrise",
    "Unity",
    "Pinnacle Care",
    "Open Door",
    "Frontier",
    "Civic Action",
    "Harbor Aid",
    "Kindred Spirit",
    "NextGen",
    "Vitality",
    "New Horizons",
    "Alliance",
    "Solidarity",
    "Bridge of Hope",
    "Pathway",
    "Starlight",
    "Golden Bridge",
]

ORG_NAME_SUFFIXES = [
    "Foundation",
    "Initiative",
    "Network",
    "Charity",
    "Services",
    "Alliance",
    "Coalition",
    "Society",
    "Partnership",
    "Association",
    "Trust",
    "Care Project",
    "Relief Fund",
    "Volunteers",
    "Outreach",
    "Solutions",
    "Collective",
    "Guild",
    "Corps",
    "Exchange",
]

MISSIONS = [
    (
        "Dedicated to providing essential food, shelter, and medical relief to "
        "underserved communities."
    ),
    (
        "Empowering youth and vulnerable families through education, "
        "mentorship, and emergency aid."
    ),
    (
        "Mobilizing volunteers and resources to support crisis response and "
        "disaster recovery."
    ),
    "Promoting community wellness, mental health support, and social welfare programs.",
    (
        "Fostering sustainable livelihoods and vocational skills training for "
        "low-income households."
    ),
    (
        "Connecting community volunteers with individuals in need of urgent "
        "daily assistance."
    ),
    (
        "Enhancing public safety, disaster preparedness, and resilient "
        "neighborhood networks."
    ),
    (
        "Supporting elderly citizens with accessible transportation, groceries, "
        "and companionship."
    ),
    (
        "Providing clothing, warmth, and dignity to displaced families and "
        "individuals in crisis."
    ),
    "Advancing localized humanitarian impact through collaborative volunteer action.",
]

SKILL_LEVELS = ["BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"]
ORG_TYPES = ["non_profit", "for_profit"]
ORG_SIZES = ["small", "medium", "large"]
AUTH_PROVIDERS = ["GOOGLE", "APPLE", "EMAIL", "MICROSOFT", "FACEBOOK"]
GENDERS = ["Male", "Female", "Non-Binary", "Prefer not to say"]
