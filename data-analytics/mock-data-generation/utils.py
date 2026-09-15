"""
utils.py
--------
Shared helpers and reference data for the Virginia mock-data generator.

This module owns two things:
1. A small, hand-picked geographic reference set (countries -> states ->
   cities -> approximate lat/lng centroids) so that every generated row
   is geographically self-consistent (a city really is in the state it
   claims to be in, and coordinates land near that city).
2. Small utility functions (random timestamp pairs, jitter for lat/lng,
   id sequence helpers) reused across the generator.

Everything here is 100% synthetic / public reference data (real place
names and real approximate coordinates, but NO real people, emails,
phone numbers, or user records).
"""

import random
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Geographic reference data
# ---------------------------------------------------------------------------
# Structure:
# COUNTRIES: list of country names
# STATES_BY_COUNTRY: country_name -> list of state names
# CITIES_BY_STATE: state_name -> list of (city_name, lat, lng)
#
# Coordinates are approximate city-centroid values, used only to make
# curr_loc / prev_loc plausible -- not survey-accurate.

COUNTRIES = ["United States", "Canada", "India"]

STATES_BY_COUNTRY = {
    "United States": [
        "California", "Texas", "Arizona", "New York", "Florida",
        "Washington", "Illinois", "Georgia", "Colorado", "Massachusetts",
    ],
    "Canada": [
        "Ontario", "British Columbia", "Quebec",
    ],
    "India": [
        "Maharashtra", "Karnataka", "Telangana",
    ],
}

CITIES_BY_STATE = {
    "California": [
        ("San Jose", 37.3382, -121.8863),
        ("San Francisco", 37.7749, -122.4194),
        ("Los Angeles", 34.0522, -118.2437),
        ("Sacramento", 38.5816, -121.4944),
    ],
    "Texas": [
        ("Austin", 30.2672, -97.7431),
        ("Houston", 29.7604, -95.3698),
        ("Dallas", 32.7767, -96.7970),
    ],
    "Arizona": [
        ("Phoenix", 33.4484, -112.0740),
        ("Tempe", 33.4255, -111.9400),
        ("Tucson", 32.2226, -110.9747),
    ],
    "New York": [
        ("New York City", 40.7128, -74.0060),
        ("Buffalo", 42.8864, -78.8784),
        ("Albany", 42.6526, -73.7562),
    ],
    "Florida": [
        ("Miami", 25.7617, -80.1918),
        ("Orlando", 28.5383, -81.3792),
        ("Tampa", 27.9506, -82.4572),
    ],
    "Washington": [
        ("Seattle", 47.6062, -122.3321),
        ("Spokane", 47.6588, -117.4260),
    ],
    "Illinois": [
        ("Chicago", 41.8781, -87.6298),
        ("Springfield", 39.7817, -89.6501),
    ],
    "Georgia": [
        ("Atlanta", 33.7490, -84.3880),
        ("Savannah", 32.0809, -81.0912),
    ],
    "Colorado": [
        ("Denver", 39.7392, -104.9903),
        ("Boulder", 40.0150, -105.2705),
    ],
    "Massachusetts": [
        ("Boston", 42.3601, -71.0589),
        ("Cambridge", 42.3736, -71.1097),
    ],
    "Ontario": [
        ("Toronto", 43.6532, -79.3832),
        ("Ottawa", 45.4215, -75.6972),
    ],
    "British Columbia": [
        ("Vancouver", 49.2827, -123.1207),
        ("Victoria", 48.4284, -123.3656),
    ],
    "Quebec": [
        ("Montreal", 45.5019, -73.5674),
        ("Quebec City", 46.8139, -71.2080),
    ],
    "Maharashtra": [
        ("Mumbai", 19.0760, 72.8777),
        ("Pune", 18.5204, 73.8567),
    ],
    "Karnataka": [
        ("Bengaluru", 12.9716, 77.5946),
        ("Mysuru", 12.2958, 76.6394),
    ],
    "Telangana": [
        ("Hyderabad", 17.3850, 78.4867),
        ("Warangal", 17.9689, 79.5941),
    ],
}

# Help categories offered by Saayam For All (cat_id assigned sequentially
# by the generator; names only live here).
HELP_CATEGORY_NAMES = [
    "Education & Tutoring",
    "Food & Groceries",
    "Housing & Shelter",
    "Healthcare Access",
    "Legal Assistance",
    "Employment & Job Search",
    "Financial Assistance",
    "Mental Health Support",
    "Transportation",
    "Elder Care",
    "Childcare Support",
    "Technology Help",
    "Immigration Support",
    "Disaster Relief",
    "Community Outreach",
]

SKILL_PROFICIENCY_LEVELS = ["Beginner", "Intermediate", "Advanced", "Expert"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def random_country_state_city(rng: random.Random):
    """Return a geographically consistent (country, state, city, lat, lng) tuple."""
    country = rng.choice(COUNTRIES)
    state = rng.choice(STATES_BY_COUNTRY[country])
    city, lat, lng = rng.choice(CITIES_BY_STATE[state])
    return country, state, city, lat, lng


def jitter_coordinate(lat: float, lng: float, rng: random.Random, spread: float = 0.05):
    """
    Nudge a centroid lat/lng by a small random offset so points don't all
    stack exactly on the city center, while staying "near" that city.
    ~0.05 degrees is roughly a few miles at mid latitudes.
    """
    return (
        round(lat + rng.uniform(-spread, spread), 6),
        round(lng + rng.uniform(-spread, spread), 6),
    )


def random_datetime_between(start: datetime, end: datetime, rng: random.Random) -> datetime:
    """Uniform-random datetime between start and end (inclusive-ish)."""
    delta_seconds = int((end - start).total_seconds())
    if delta_seconds <= 0:
        return start
    offset = rng.randint(0, delta_seconds)
    return start + timedelta(seconds=offset)


def created_and_updated(rng: random.Random, earliest: datetime, latest: datetime):
    """
    Return (created_at, updated_at) as PostgreSQL-friendly strings with
    created_at <= updated_at guaranteed.
    """
    created = random_datetime_between(earliest, latest, rng)
    updated = random_datetime_between(created, latest, rng)
    fmt = "%Y-%m-%d %H:%M:%S"
    return created.strftime(fmt), updated.strftime(fmt)
