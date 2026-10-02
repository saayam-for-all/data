"""Curated, self-consistent reference data used to seed the generators.

The geographic tree (country -> state -> city) is hand-picked with real-world
names, approximate coordinates, a canonical IANA time zone per state, and a real
country-appropriate postal code per seed city -- so every generated foreign key
is valid and every derived attribute (time zone, postal code) is consistent with
the row's location. No personal data appears here: only place names, generic name
pools, and category metadata.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Countries: (country_id, country_name, phone_code, country_code, is_eu_member)
# ---------------------------------------------------------------------------
COUNTRIES: List[Tuple[int, str, str, str, bool]] = [
    (1, "UNITED_STATES", "1", "USA", False),
    (2, "CANADA", "1", "CAN", False),
    (3, "UNITED_KINGDOM", "44", "GBR", False),
    (4, "INDIA", "91", "IND", False),
    (5, "AUSTRALIA", "61", "AUS", False),
    (6, "GERMANY", "49", "DEU", True),
]

# ---------------------------------------------------------------------------
# Geo tree:
#   country_code -> [ (state_name, state_code, iana_tz,
#                       [ (city_name, lat, lon, postal) ]) ]
# ``postal`` is a real, country-appropriately-formatted postal code for that
# city. Generators keep the city-identifying prefix and only vary the local part
# for synthesized cities, so a postal code always stays within its city/region.
# ---------------------------------------------------------------------------
GEO: Dict[str, List[Tuple[str, str, str, List[Tuple[str, float, float, str]]]]] = {
    "USA": [
        ("VIRGINIA", "VA", "America/New_York", [
            ("Richmond", 37.5407, -77.4360, "23219"),
            ("Norfolk", 36.8508, -76.2859, "23510"),
            ("Arlington", 38.8799, -77.1068, "22201"),
            ("Alexandria", 38.8048, -77.0469, "22314"),
        ]),
        ("CALIFORNIA", "CA", "America/Los_Angeles", [
            ("Los Angeles", 34.0522, -118.2437, "90012"),
            ("San Francisco", 37.7749, -122.4194, "94103"),
            ("San Diego", 32.7157, -117.1611, "92101"),
        ]),
        ("NEW_YORK", "NY", "America/New_York", [
            ("New York", 40.7128, -74.0060, "10001"),
            ("Buffalo", 42.8864, -78.8784, "14202"),
            ("Albany", 42.6526, -73.7562, "12207"),
        ]),
        ("TEXAS", "TX", "America/Chicago", [
            ("Houston", 29.7604, -95.3698, "77002"),
            ("Austin", 30.2672, -97.7431, "78701"),
            ("Dallas", 32.7767, -96.7970, "75201"),
        ]),
        ("WASHINGTON", "WA", "America/Los_Angeles", [
            ("Seattle", 47.6062, -122.3321, "98101"),
            ("Spokane", 47.6588, -117.4260, "99201"),
        ]),
    ],
    "CAN": [
        ("ONTARIO", "ON", "America/Toronto", [
            ("Toronto", 43.6532, -79.3832, "M5H 2N2"),
            ("Ottawa", 45.4215, -75.6972, "K1P 1J1"),
        ]),
        ("BRITISH_COLUMBIA", "BC", "America/Vancouver", [
            ("Vancouver", 49.2827, -123.1207, "V6B 1A1"),
            ("Victoria", 48.4284, -123.3656, "V8W 1P6"),
        ]),
        ("QUEBEC", "QC", "America/Toronto", [
            ("Montreal", 45.5019, -73.5674, "H2Y 1C6"),
            ("Quebec City", 46.8139, -71.2080, "G1R 4P3"),
        ]),
    ],
    "GBR": [
        ("ENGLAND", "ENG", "Europe/London", [
            ("London", 51.5074, -0.1278, "SW1A 1AA"),
            ("Manchester", 53.4808, -2.2426, "M1 1AE"),
            ("Birmingham", 52.4862, -1.8904, "B1 1BB"),
        ]),
        ("SCOTLAND", "SCT", "Europe/London", [
            ("Edinburgh", 55.9533, -3.1883, "EH1 1YZ"),
            ("Glasgow", 55.8642, -4.2518, "G1 1XW"),
        ]),
    ],
    "IND": [
        ("MAHARASHTRA", "MH", "Asia/Kolkata", [
            ("Mumbai", 19.0760, 72.8777, "400001"),
            ("Pune", 18.5204, 73.8567, "411001"),
        ]),
        ("KARNATAKA", "KA", "Asia/Kolkata", [
            ("Bengaluru", 12.9716, 77.5946, "560001"),
            ("Mysuru", 12.2958, 76.6394, "570001"),
        ]),
        ("DELHI", "DL", "Asia/Kolkata", [
            ("New Delhi", 28.6139, 77.2090, "110001"),
        ]),
    ],
    "AUS": [
        ("NEW_SOUTH_WALES", "NSW", "Australia/Sydney", [
            ("Sydney", -33.8688, 151.2093, "2000"),
            ("Newcastle", -32.9283, 151.7817, "2300"),
        ]),
        ("VICTORIA", "VIC", "Australia/Melbourne", [
            ("Melbourne", -37.8136, 144.9631, "3000"),
            ("Geelong", -38.1499, 144.3617, "3220"),
        ]),
    ],
    "DEU": [
        ("BERLIN", "BE", "Europe/Berlin", [
            ("Berlin", 52.5200, 13.4050, "10115"),
        ]),
        ("BAVARIA", "BY", "Europe/Berlin", [
            ("Munich", 48.1351, 11.5820, "80331"),
            ("Nuremberg", 49.4521, 11.0767, "90402"),
        ]),
        ("HAMBURG", "HH", "Europe/Berlin", [
            ("Hamburg", 53.5511, 9.9937, "20095"),
        ]),
    ],
}

# Extra city-name fragments used to synthesize additional cities per state
# (config.CITIES_PER_STATE). Coordinates are jittered only slightly around a
# state seed city so they stay plausible (not pushed across a border/coastline).
CITY_PREFIXES = ["North", "South", "East", "West", "New", "Port", "Lake", "Mount", "Fort", "Green"]
CITY_SUFFIXES = ["field", "ton", "ville", "burg", "haven", "dale", "wood", "ford", "bridge", "crest"]

# Small jitter (degrees) for synthesized city centers -- ~11km max, chosen to
# keep synthetic cities within their state without landing in the ocean.
CITY_JITTER_DEG = 0.005
# Even smaller jitter (degrees) for per-row coordinate points around a city.
POINT_JITTER_DEG = 0.003

# ---------------------------------------------------------------------------
# Help categories (hierarchical). (cat_id, cat_name, cat_desc)
# cat_id uses a dotted hierarchy; every child's parent id is also present.
# ---------------------------------------------------------------------------
HELP_CATEGORIES: List[Tuple[str, str, str]] = [
    ("1", "FOOD_AND_ESSENTIALS", "Food, groceries and daily essentials"),
    ("1.1", "FOOD_ASSISTANCE", "Meals and food distribution support"),
    ("1.2", "GROCERY_DELIVERY", "Grocery shopping and delivery help"),
    ("1.3", "COOKING_HELP", "Meal preparation and cooking assistance"),
    ("2", "HEALTH_AND_WELLNESS", "Physical and mental health support"),
    ("2.1", "MEDICAL_TRANSPORT", "Rides to medical appointments"),
    ("2.2", "MEDICATION_PICKUP", "Prescription pickup and delivery"),
    ("2.3", "MENTAL_HEALTH", "Counseling and emotional support"),
    ("2.4", "ELDER_CARE", "Assistance and companionship for elders"),
    ("3", "EDUCATION", "Tutoring, mentoring and learning support"),
    ("3.1", "TUTORING", "Academic tutoring across subjects"),
    ("3.2", "CAREER_MENTORING", "Career guidance and mentoring"),
    ("3.3", "LANGUAGE_HELP", "Language learning and translation"),
    ("4", "HOUSING_AND_SHELTER", "Housing, shelter and utilities support"),
    ("4.1", "TEMPORARY_SHELTER", "Emergency and temporary shelter"),
    ("4.2", "HOME_REPAIR", "Basic home repair and maintenance"),
    ("4.3", "UTILITY_ASSISTANCE", "Help with utility bills and setup"),
    ("5", "TRANSPORTATION", "Rides and mobility assistance"),
    ("5.1", "RIDE_SHARE", "Community rides to appointments and errands"),
    ("5.2", "VEHICLE_REPAIR", "Basic vehicle repair assistance"),
    ("6", "EMPLOYMENT", "Job search and employment support"),
    ("6.1", "RESUME_HELP", "Resume writing and review"),
    ("6.2", "JOB_SEARCH", "Job search and application help"),
    ("6.3", "INTERVIEW_PREP", "Interview preparation and coaching"),
    ("7", "LEGAL_AND_FINANCIAL", "Legal aid and financial guidance"),
    ("7.1", "LEGAL_AID", "Basic legal information and referrals"),
    ("7.2", "FINANCIAL_LITERACY", "Budgeting and financial literacy"),
    ("8", "DISASTER_RELIEF", "Support during and after disasters"),
    ("8.1", "EVACUATION_HELP", "Evacuation and relocation assistance"),
    ("8.2", "SUPPLY_DISTRIBUTION", "Emergency supply distribution"),
    ("9", "TECHNOLOGY", "Digital access and tech support"),
    ("9.1", "DEVICE_SETUP", "Device setup and troubleshooting"),
    ("9.2", "DIGITAL_LITERACY", "Basic digital literacy training"),
    ("10", "COMMUNITY", "General community support"),
    ("10.1", "EVENT_VOLUNTEERING", "Help staffing community events"),
    ("10.2", "COMPANIONSHIP", "Social companionship and check-ins"),
]

# ---------------------------------------------------------------------------
# Verified external lookup ids, checked 2026-09-08 at data commit:
# a9a14a18aaac012f425b946ae4639e0535f7efce
# database/lookup_tables/supporting_languages.csv
# database/lookup_tables/user_status.csv
# Exact source links and local seed instructions are in README.md.
#   supporting_languages.language_id -> 1..12 (12 rows in the lookup)
#   user_status.user_status_id       -> only 1 (ACTIVE) is seeded/committed
# These are the ONLY values the generator will emit; validation checks against
# the same verified sets. Widen them (config / CLI) only after the corresponding
# lookup rows are actually seeded.
# ---------------------------------------------------------------------------
VERIFIED_LANGUAGE_IDS = list(range(1, 13))
VERIFIED_USER_STATUS_IDS = [1]

# user_skills.skill_level -- values for the skill_levels enum.
SKILL_LEVELS = ["BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"]

# ---------------------------------------------------------------------------
# Synthetic name pools (generic, not tied to any real person)
# ---------------------------------------------------------------------------
FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery",
    "Quinn", "Skyler", "Reese", "Dakota", "Rowan", "Sage", "Emerson", "Finley",
    "Harper", "Kai", "Logan", "Micah", "Noel", "Parker", "River", "Shiloh",
    "Devon", "Ellis", "Frankie", "Gray", "Hayden", "Indie", "Jules", "Kendall",
]
MIDDLE_NAMES = ["", "", "", "Lee", "Marie", "Ray", "Jo", "Blake", "Drew", "Lane"]
LAST_NAMES = [
    "Rivers", "Stone", "Meadows", "Brooks", "Fields", "Hart", "Vale", "Frost",
    "Lane", "Wells", "Pace", "Quill", "Marsh", "Reed", "Snow", "Thorn",
    "Vance", "Wren", "Ashby", "Blythe", "Crane", "Dune", "Eaves", "Flint",
    "Glade", "Holt", "Ives", "Kerr", "Locke", "Nash", "Orme", "Pike",
]
GENDERS = ["FEMALE", "MALE", "NON_BINARY", "PREFER_NOT_TO_SAY"]
AUTH_PROVIDERS = ["COGNITO", "GOOGLE", "FACEBOOK", "APPLE"]

# Availability building blocks for volunteer_details jsonb columns.
AVAILABILITY_DAYS = [
    ["MON", "WED", "FRI"], ["SAT", "SUN"], ["TUE", "THU"],
    ["MON", "TUE", "WED", "THU", "FRI"], ["SAT"], ["SUN"],
    ["MON", "WED", "FRI", "SAT"],
]
AVAILABILITY_TIMES = [
    ["MORNING"], ["AFTERNOON"], ["EVENING"],
    ["MORNING", "EVENING"], ["AFTERNOON", "EVENING"], ["FULL_DAY"],
]

# Organization synthesis pools.
ORG_NAME_PREFIX = [
    "Harbor", "Summit", "Unity", "Beacon", "Bright", "Cornerstone", "Evergreen",
    "Guardian", "Helping", "Lighthouse", "Open", "Riverside", "Solace", "Trinity",
]
ORG_NAME_CORE = [
    "Community", "Family", "Neighbor", "Care", "Relief", "Hope", "Outreach",
    "Support", "Assistance", "Foundation", "Alliance", "Network",
]
ORG_NAME_SUFFIX = [
    "Foundation", "Services", "Network", "Coalition", "Center", "Trust",
    "Initiative", "Society", "Partners", "Collective",
]
# org_type_enum / org_size_enum -- EXACT values from the schema wiki.
ORG_TYPES = ["non_profit", "for_profit"]
ORG_SIZES = ["small", "medium", "large"]
STREET_NAMES = [
    "Main", "Oak", "Maple", "Cedar", "Pine", "Elm", "Washington", "Lake",
    "Hill", "Park", "River", "Sunset", "Highland", "Union", "Church",
]
STREET_TYPES = ["St", "Ave", "Blvd", "Rd", "Ln", "Dr", "Way", "Ct"]
MISSION_WORDS = [
    "support", "empower", "connect", "serve", "uplift", "strengthen", "assist",
    "communities", "neighbors", "families", "volunteers", "resources", "care",
    "dignity", "resilience", "access", "opportunity", "wellbeing", "relief",
]
