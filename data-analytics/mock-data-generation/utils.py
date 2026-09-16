"""Shared reference data and helper functions for mock data generation."""

import random
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Configuration defaults (overridable via CLI args in generate_mock_data.py)
# ---------------------------------------------------------------------------

DEFAULT_N_ROWS = 400
DEFAULT_VOLUNTEER_FRACTION = 0.5
DEFAULT_SEED = 42

DEFAULT_TODAY = datetime(2026, 9, 11, 0, 0, 0)
DEFAULT_EARLIEST_DATE = datetime(2024, 1, 1, 0, 0, 0)

# ---------------------------------------------------------------------------
# Reference data (represents real-world entities)
# ---------------------------------------------------------------------------

COUNTRIES = [
    {
        "country_name": "UNITED_STATES",
        "phone_code": "1",
        "country_code": "USA",
        "is_eu_member": False,
    },
    {
        "country_name": "CANADA",
        "phone_code": "1",
        "country_code": "CAN",
        "is_eu_member": False,
    },
    {
        "country_name": "MEXICO",
        "phone_code": "52",
        "country_code": "MEX",
        "is_eu_member": False,
    },
    {
        "country_name": "UNITED_KINGDOM",
        "phone_code": "44",
        "country_code": "GBR",
        "is_eu_member": False,
    },
    {
        "country_name": "GERMANY",
        "phone_code": "49",
        "country_code": "DEU",
        "is_eu_member": True,
    },
    {
        "country_name": "FRANCE",
        "phone_code": "33",
        "country_code": "FRA",
        "is_eu_member": True,
    },
    {
        "country_name": "SPAIN",
        "phone_code": "34",
        "country_code": "ESP",
        "is_eu_member": True,
    },
    {
        "country_name": "ITALY",
        "phone_code": "39",
        "country_code": "ITA",
        "is_eu_member": True,
    },
    {
        "country_name": "NETHERLANDS",
        "phone_code": "31",
        "country_code": "NLD",
        "is_eu_member": True,
    },
    {
        "country_name": "INDIA",
        "phone_code": "91",
        "country_code": "IND",
        "is_eu_member": False,
    },
    {
        "country_name": "AUSTRALIA",
        "phone_code": "61",
        "country_code": "AUS",
        "is_eu_member": False,
    },
    {
        "country_name": "BRAZIL",
        "phone_code": "55",
        "country_code": "BRA",
        "is_eu_member": False,
    },
    {
        "country_name": "JAPAN",
        "phone_code": "81",
        "country_code": "JPN",
        "is_eu_member": False,
    },
    {
        "country_name": "SOUTH_AFRICA",
        "phone_code": "27",
        "country_code": "ZAF",
        "is_eu_member": False,
    },
    {
        "country_name": "SWEDEN",
        "phone_code": "46",
        "country_code": "SWE",
        "is_eu_member": True,
    },
]

# US states only (2-letter state_id)
US_STATES = [
    {"state_id": "AL", "state_name": "Alabama", "state_code": "US-AL"},
    {"state_id": "AK", "state_name": "Alaska", "state_code": "US-AK"},
    {"state_id": "AZ", "state_name": "Arizona", "state_code": "US-AZ"},
    {"state_id": "AR", "state_name": "Arkansas", "state_code": "US-AR"},
    {"state_id": "CA", "state_name": "California", "state_code": "US-CA"},
    {"state_id": "CO", "state_name": "Colorado", "state_code": "US-CO"},
    {"state_id": "CT", "state_name": "Connecticut", "state_code": "US-CT"},
    {"state_id": "DE", "state_name": "Delaware", "state_code": "US-DE"},
    {"state_id": "FL", "state_name": "Florida", "state_code": "US-FL"},
    {"state_id": "GA", "state_name": "Georgia", "state_code": "US-GA"},
    {"state_id": "HI", "state_name": "Hawaii", "state_code": "US-HI"},
    {"state_id": "ID", "state_name": "Idaho", "state_code": "US-ID"},
    {"state_id": "IL", "state_name": "Illinois", "state_code": "US-IL"},
    {"state_id": "IN", "state_name": "Indiana", "state_code": "US-IN"},
    {"state_id": "IA", "state_name": "Iowa", "state_code": "US-IA"},
    {"state_id": "KS", "state_name": "Kansas", "state_code": "US-KS"},
    {"state_id": "KY", "state_name": "Kentucky", "state_code": "US-KY"},
    {"state_id": "LA", "state_name": "Louisiana", "state_code": "US-LA"},
    {"state_id": "ME", "state_name": "Maine", "state_code": "US-ME"},
    {"state_id": "MD", "state_name": "Maryland", "state_code": "US-MD"},
    {"state_id": "MA", "state_name": "Massachusetts", "state_code": "US-MA"},
    {"state_id": "MI", "state_name": "Michigan", "state_code": "US-MI"},
    {"state_id": "MN", "state_name": "Minnesota", "state_code": "US-MN"},
    {"state_id": "MS", "state_name": "Mississippi", "state_code": "US-MS"},
    {"state_id": "MO", "state_name": "Missouri", "state_code": "US-MO"},
    {"state_id": "MT", "state_name": "Montana", "state_code": "US-MT"},
    {"state_id": "NE", "state_name": "Nebraska", "state_code": "US-NE"},
    {"state_id": "NV", "state_name": "Nevada", "state_code": "US-NV"},
    {"state_id": "NH", "state_name": "New Hampshire", "state_code": "US-NH"},
    {"state_id": "NJ", "state_name": "New Jersey", "state_code": "US-NJ"},
    {"state_id": "NM", "state_name": "New Mexico", "state_code": "US-NM"},
    {"state_id": "NY", "state_name": "New York", "state_code": "US-NY"},
    {"state_id": "NC", "state_name": "North Carolina", "state_code": "US-NC"},
    {"state_id": "ND", "state_name": "North Dakota", "state_code": "US-ND"},
    {"state_id": "OH", "state_name": "Ohio", "state_code": "US-OH"},
    {"state_id": "OK", "state_name": "Oklahoma", "state_code": "US-OK"},
    {"state_id": "OR", "state_name": "Oregon", "state_code": "US-OR"},
    {"state_id": "PA", "state_name": "Pennsylvania", "state_code": "US-PA"},
    {"state_id": "RI", "state_name": "Rhode Island", "state_code": "US-RI"},
    {"state_id": "SC", "state_name": "South Carolina", "state_code": "US-SC"},
    {"state_id": "SD", "state_name": "South Dakota", "state_code": "US-SD"},
    {"state_id": "TN", "state_name": "Tennessee", "state_code": "US-TN"},
    {"state_id": "TX", "state_name": "Texas", "state_code": "US-TX"},
    {"state_id": "UT", "state_name": "Utah", "state_code": "US-UT"},
    {"state_id": "VT", "state_name": "Vermont", "state_code": "US-VT"},
    {"state_id": "VA", "state_name": "Virginia", "state_code": "US-VA"},
    {"state_id": "WA", "state_name": "Washington", "state_code": "US-WA"},
    {"state_id": "WV", "state_name": "West Virginia", "state_code": "US-WV"},
    {"state_id": "WI", "state_name": "Wisconsin", "state_code": "US-WI"},
    {"state_id": "WY", "state_name": "Wyoming", "state_code": "US-WY"},
]

# A handful of real cities per state, with real lat/long and a real zip code
# (small curated pool). Tuple shape: (city_name, lat, lon, zip_code).
US_CITIES = {
    "AL": [
        ("Birmingham", 33.5207, -86.8025, "35203"),
        ("Montgomery", 32.3792, -86.3077, "36104"),
    ],
    "AK": [
        ("Anchorage", 61.2181, -149.9003, "99501"),
        ("Juneau", 58.3019, -134.4197, "99801"),
    ],
    "AZ": [
        ("Phoenix", 33.4484, -112.0740, "85004"),
        ("Tucson", 32.2226, -110.9747, "85701"),
    ],
    "AR": [
        ("Little Rock", 34.7465, -92.2896, "72201"),
        ("Fayetteville", 36.0626, -94.1574, "72701"),
    ],
    "CA": [
        ("Los Angeles", 34.0522, -118.2437, "90012"),
        ("San Francisco", 37.7749, -122.4194, "94102"),
        ("San Diego", 32.7157, -117.1611, "92101"),
    ],
    "CO": [
        ("Denver", 39.7392, -104.9903, "80202"),
        ("Boulder", 40.0150, -105.2705, "80301"),
    ],
    "CT": [
        ("Hartford", 41.7658, -72.6734, "06103"),
        ("New Haven", 41.3083, -72.9279, "06510"),
    ],
    "DE": [
        ("Wilmington", 39.7447, -75.5484, "19801"),
        ("Dover", 39.1582, -75.5244, "19901"),
    ],
    "FL": [
        ("Miami", 25.7617, -80.1918, "33130"),
        ("Orlando", 28.5383, -81.3792, "32801"),
        ("Tampa", 27.9506, -82.4572, "33602"),
    ],
    "GA": [
        ("Atlanta", 33.7490, -84.3880, "30303"),
        ("Savannah", 32.0809, -81.0912, "31401"),
    ],
    "HI": [
        ("Honolulu", 21.3069, -157.8583, "96813"),
        ("Hilo", 19.7297, -155.0900, "96720"),
    ],
    "ID": [
        ("Boise", 43.6150, -116.2023, "83702"),
        ("Idaho Falls", 43.4917, -112.0339, "83402"),
    ],
    "IL": [
        ("Chicago", 41.8781, -87.6298, "60601"),
        ("Springfield", 39.7817, -89.6501, "62701"),
    ],
    "IN": [
        ("Indianapolis", 39.7684, -86.1581, "46204"),
        ("Fort Wayne", 41.0793, -85.1394, "46802"),
    ],
    "IA": [
        ("Des Moines", 41.5868, -93.6250, "50309"),
        ("Cedar Rapids", 41.9779, -91.6656, "52401"),
    ],
    "KS": [
        ("Wichita", 37.6872, -97.3301, "67202"),
        ("Topeka", 39.0473, -95.6752, "66603"),
    ],
    "KY": [
        ("Louisville", 38.2527, -85.7585, "40202"),
        ("Lexington", 38.0406, -84.5037, "40507"),
    ],
    "LA": [
        ("New Orleans", 29.9511, -90.0715, "70112"),
        ("Baton Rouge", 30.4515, -91.1871, "70801"),
    ],
    "ME": [
        ("Portland", 43.6591, -70.2568, "04101"),
        ("Augusta", 44.3106, -69.7795, "04330"),
    ],
    "MD": [
        ("Baltimore", 39.2904, -76.6122, "21201"),
        ("Annapolis", 38.9784, -76.4922, "21401"),
    ],
    "MA": [
        ("Boston", 42.3601, -71.0589, "02108"),
        ("Worcester", 42.2626, -71.8023, "01608"),
    ],
    "MI": [
        ("Detroit", 42.3314, -83.0458, "48226"),
        ("Grand Rapids", 42.9634, -85.6681, "49503"),
    ],
    "MN": [
        ("Minneapolis", 44.9778, -93.2650, "55401"),
        ("Saint Paul", 44.9537, -93.0900, "55101"),
    ],
    "MS": [
        ("Jackson", 32.2988, -90.1848, "39201"),
        ("Gulfport", 30.3674, -89.0928, "39501"),
    ],
    "MO": [
        ("Kansas City", 39.0997, -94.5786, "64106"),
        ("St. Louis", 38.6270, -90.1994, "63101"),
    ],
    "MT": [
        ("Billings", 45.7833, -108.5007, "59101"),
        ("Missoula", 46.8721, -113.9940, "59801"),
    ],
    "NE": [
        ("Omaha", 41.2565, -95.9345, "68102"),
        ("Lincoln", 40.8136, -96.7026, "68508"),
    ],
    "NV": [
        ("Las Vegas", 36.1699, -115.1398, "89101"),
        ("Reno", 39.5296, -119.8138, "89501"),
    ],
    "NH": [
        ("Manchester", 42.9956, -71.4548, "03101"),
        ("Concord", 43.2081, -71.5376, "03301"),
    ],
    "NJ": [
        ("Newark", 40.7357, -74.1724, "07102"),
        ("Jersey City", 40.7178, -74.0431, "07302"),
    ],
    "NM": [
        ("Albuquerque", 35.0844, -106.6504, "87102"),
        ("Santa Fe", 35.6870, -105.9378, "87501"),
    ],
    "NY": [
        ("New York City", 40.7128, -74.0060, "10007"),
        ("Buffalo", 42.8864, -78.8784, "14202"),
        ("Albany", 42.6526, -73.7562, "12207"),
    ],
    "NC": [
        ("Charlotte", 35.2271, -80.8431, "28202"),
        ("Raleigh", 35.7796, -78.6382, "27601"),
    ],
    "ND": [
        ("Fargo", 46.8772, -96.7898, "58102"),
        ("Bismarck", 46.8083, -100.7837, "58501"),
    ],
    "OH": [
        ("Columbus", 39.9612, -82.9988, "43215"),
        ("Cleveland", 41.4993, -81.6944, "44113"),
    ],
    "OK": [
        ("Oklahoma City", 35.4676, -97.5164, "73102"),
        ("Tulsa", 36.1540, -95.9928, "74103"),
    ],
    "OR": [
        ("Portland", 45.5152, -122.6784, "97201"),
        ("Eugene", 44.0521, -123.0868, "97401"),
    ],
    "PA": [
        ("Philadelphia", 39.9526, -75.1652, "19107"),
        ("Pittsburgh", 40.4406, -79.9959, "15222"),
    ],
    "RI": [("Providence", 41.8240, -71.4128, "02903")],
    "SC": [
        ("Columbia", 34.0007, -81.0348, "29201"),
        ("Charleston", 32.7765, -79.9311, "29401"),
    ],
    "SD": [
        ("Sioux Falls", 43.5460, -96.7313, "57104"),
        ("Rapid City", 44.0805, -103.2310, "57701"),
    ],
    "TN": [
        ("Nashville", 36.1627, -86.7816, "37203"),
        ("Memphis", 35.1495, -90.0490, "38103"),
    ],
    "TX": [
        ("Houston", 29.7604, -95.3698, "77002"),
        ("Austin", 30.2672, -97.7431, "78701"),
        ("Dallas", 32.7767, -96.7970, "75201"),
    ],
    "UT": [
        ("Salt Lake City", 40.7608, -111.8910, "84101"),
        ("Provo", 40.2338, -111.6585, "84601"),
    ],
    "VT": [("Burlington", 44.4759, -73.2121, "05401")],
    "VA": [
        ("Richmond", 37.5407, -77.4360, "23219"),
        ("Virginia Beach", 36.8529, -75.9780, "23451"),
    ],
    "WA": [
        ("Seattle", 47.6062, -122.3321, "98101"),
        ("Spokane", 47.6588, -117.4260, "99201"),
    ],
    "WV": [("Charleston", 38.3498, -81.6326, "25301")],
    "WI": [
        ("Milwaukee", 43.0389, -87.9065, "53202"),
        ("Madison", 43.0731, -89.4012, "53703"),
    ],
    "WY": [("Cheyenne", 41.1400, -104.8202, "82001")],
}

HELP_CATEGORIES = [
    ("1", "FOOD_AND_ESSENTIALS", "Assistance with food and essential daily needs"),
    ("1.1", "FOOD_ASSISTANCE", "Help accessing food resources"),
    ("1.2", "GROCERY_SHOPPING_AND_DELIVERY", "Help with grocery shopping and delivery"),
    ("1.3", "COOKING_HELP", "Assistance with meal preparation"),
    ("1.3.1", "MEAL_PREP_BASIC", "Basic meal preparation help"),
    ("1.3.2", "NUTRITIONAL_MEAL_PLANNING", "Help planning nutritious meals"),
    ("2", "CLOTHING_ASSISTANCE", "Assistance with clothing needs"),
    ("2.1", "DONATE_CLOTHES", "Donating clothing items"),
    ("2.2", "EMERGENCY_CLOTHING", "Emergency clothing assistance"),
    ("3", "HOUSING_ASSISTANCE", "Assistance with housing needs"),
    ("3.1", "TEMPORARY_SHELTER", "Help finding temporary shelter"),
    ("3.2", "RENT_SUPPORT", "Support with rent payments"),
    ("4", "TRANSPORTATION", "Transportation assistance"),
    ("4.1", "RIDE_TO_APPOINTMENTS", "Rides to medical or other appointments"),
    ("4.2", "PUBLIC_TRANSIT_ASSISTANCE", "Help navigating public transit"),
    ("5", "EDUCATION_SUPPORT", "Educational support and tutoring"),
    ("5.1", "TUTORING", "One-on-one or group tutoring"),
    ("5.2", "SCHOOL_SUPPLIES", "Help obtaining school supplies"),
    ("6", "HEALTHCARE_SUPPORT", "Healthcare-related assistance"),
    (
        "6.1",
        "MEDICAL_APPOINTMENT_HELP",
        "Help scheduling or attending medical appointments",
    ),
    ("6.2", "MENTAL_HEALTH_SUPPORT", "Mental health support resources"),
    ("7", "ELDER_CARE", "Support for elderly individuals"),
    ("7.1", "COMPANIONSHIP", "Companionship visits for elderly individuals"),
    ("7.2", "ERRANDS_FOR_ELDERLY", "Running errands for elderly individuals"),
    ("8", "TECHNOLOGY_HELP", "Technology assistance"),
    ("8.1", "DEVICE_SETUP", "Help setting up computers or phones"),
    ("8.2", "DIGITAL_LITERACY", "Basic digital literacy training"),
]

FIRST_NAMES = [
    "James",
    "Mary",
    "Robert",
    "Patricia",
    "John",
    "Jennifer",
    "Michael",
    "Linda",
    "David",
    "Elizabeth",
    "William",
    "Barbara",
    "Richard",
    "Susan",
    "Joseph",
    "Jessica",
    "Thomas",
    "Sarah",
    "Charles",
    "Karen",
    "Ananya",
    "Wei",
    "Fatima",
    "Carlos",
    "Priya",
    "Hiroshi",
    "Amara",
    "Liam",
    "Olivia",
    "Noah",
    "Emma",
    "Sofia",
]

MIDDLE_NAMES = [
    "Lee",
    "Ann",
    "Marie",
    "Ray",
    "Jean",
    "Lynn",
    "Grace",
    "Rose",
    "Alan",
    "Kai",
    "Rae",
    "Dean",
    "",
    "",
    "",
    "",  # some blanks -> no middle name
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
]

ORG_NAME_PREFIXES = [
    "Community",
    "United",
    "Hope",
    "Bright",
    "Helping",
    "Neighborhood",
    "Global",
    "Caring",
    "Unity",
    "New Horizon",
    "Better",
    "Shared",
    "Open Hand",
    "Steady",
]
ORG_NAME_SUFFIXES = [
    "Foundation",
    "Alliance",
    "Network",
    "Outreach",
    "Initiative",
    "Coalition",
    "Partners",
    "Society",
    "Fellowship",
    "Trust",
]

GENDERS = ["MALE", "FEMALE", "NON_BINARY", "PREFER_NOT_TO_SAY"]
AUTH_PROVIDERS = ["google", "facebook", "linkedin"]
SKILL_LEVELS = ["BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"]
ORG_TYPES = ["non_profit", "for_profit"]
ORG_SIZES = ["small", "medium", "large"]
TIME_ZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
]

# ---------------------------------------------------------------------------
# ID generation helpers (replicate DB trigger formats)
# ---------------------------------------------------------------------------


def generate_sid(seq: int) -> str:
    """Replicate the users.user_id trigger format: SID-00-XXX-XXX-XXX-XXX-XXX."""
    padded = str(seq).zfill(15)
    parts = [padded[i : i + 3] for i in range(0, 15, 3)]
    return "SID-00-" + "-".join(parts)


def generate_org_id(seq: int) -> str:
    """Replicate the organizations.org_id trigger format: ORG-XXX-XXX-XXX-XXXX."""
    padded = str(seq).zfill(13)
    parts = [padded[0:3], padded[3:6], padded[6:9], padded[9:13]]
    return "ORG-" + "-".join(parts)


# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------


def jitter_point(
    lat: float, lon: float, max_delta: float = 0.05
) -> tuple[float, float]:
    """Return a lat/long slightly offset from the given point (~a few km)."""
    return (
        round(lat + random.uniform(-max_delta, max_delta), 6),
        round(lon + random.uniform(-max_delta, max_delta), 6),
    )


# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------


def random_name_parts() -> tuple[str, str, str, str]:
    """Return (first_name, middle_name, last_name, full_name)."""
    first = random.choice(FIRST_NAMES)
    middle = random.choice(MIDDLE_NAMES)
    last = random.choice(LAST_NAMES)
    full = " ".join(p for p in [first, middle, last] if p)
    return first, middle, last, full


def random_org_name() -> str:
    return f"{random.choice(ORG_NAME_PREFIXES)} {random.choice(ORG_NAME_SUFFIXES)}"


# ---------------------------------------------------------------------------
# Date/time helpers (PostgreSQL-compatible formatting + logical ordering)
# ---------------------------------------------------------------------------


def pg_timestamp(dt: datetime) -> str:
    """Format a datetime as a PostgreSQL-compatible TIMESTAMP literal."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def pg_date(dt: datetime) -> str:
    """Format a datetime as a PostgreSQL-compatible DATE literal."""
    return dt.strftime("%Y-%m-%d")


def random_datetime(start: datetime, end: datetime) -> datetime:
    """Return a random datetime uniformly between start and end (inclusive)."""
    delta = end - start
    seconds = random.uniform(0, delta.total_seconds())
    return start + timedelta(seconds=seconds)


def created_then_updated(
    earliest_date: datetime,
    today: datetime,
    base: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Return (created_at, last_updated_at) with created_at <= last_updated_at."""
    created = base if base is not None else random_datetime(earliest_date, today)
    updated = random_datetime(created, today)
    return created, updated


def random_dob(today: datetime, min_age: int = 18, max_age: int = 60) -> datetime:
    """Return a random date of birth for an age between min_age and max_age (inclusive)."""
    earliest_dob = today.replace(year=today.year - max_age)
    latest_dob = today.replace(year=today.year - min_age)
    return random_datetime(earliest_dob, latest_dob)
