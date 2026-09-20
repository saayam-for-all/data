"""Word pools for synthetic values.

Everything here is generic vocabulary combined at random, so any resemblance to a
real person, address or organization is coincidental. Emails use the reserved
example.com / example.org domains and phone numbers use the fictional 555-01xx
range, so no generated contact detail can reach a real person.
"""

from typing import Dict, List, Tuple

# --- People ------------------------------------------------------------------
# Keyed by name group; each country maps to one group (see COUNTRY_NAME_GROUP).
FIRST_NAMES: Dict[str, Dict[str, List[str]]] = {
    "western": {
        "Female": ["Olivia", "Emma", "Sofia", "Grace", "Hannah", "Maya", "Chloe", "Nora",
                   "Lucia", "Amara", "Isabel", "Naomi", "Claire", "Zoe", "Aaliyah", "Mei",
                   "Elena", "Priscilla", "Tessa", "Renee"],
        "Male": ["Liam", "Noah", "Mateo", "Ethan", "Lucas", "Daniel", "Marcus", "Andre",
                 "Samuel", "Julian", "Owen", "Caleb", "Diego", "Kenji", "Isaac", "Victor",
                 "Malik", "Theo", "Rafael", "Simon"],
    },
    "indian": {
        "Female": ["Ananya", "Diya", "Kavya", "Meera", "Priya", "Riya", "Sneha", "Isha",
                   "Lakshmi", "Nisha", "Pooja", "Tara", "Divya", "Shruti", "Aditi", "Swati"],
        "Male": ["Arjun", "Rohan", "Vikram", "Aarav", "Karthik", "Nikhil", "Sanjay", "Rahul",
                 "Aditya", "Manish", "Suresh", "Varun", "Devansh", "Harish", "Kiran", "Ravi"],
    },
    "german": {
        "Female": ["Anna", "Lena", "Marie", "Sophie", "Clara", "Greta", "Ilse", "Katrin",
                   "Johanna", "Frieda", "Laura", "Nele"],
        "Male": ["Lukas", "Felix", "Jonas", "Max", "Leon", "Paul", "Elias", "Tobias",
                 "Stefan", "Jan", "Matthias", "Florian"],
    },
}

LAST_NAMES: Dict[str, List[str]] = {
    "western": ["Hartwell", "Delgado", "Okafor", "Nguyen", "Whitfield", "Castellano", "Brennan",
                "Yamada", "Alvarez", "Sinclair", "Oyelaran", "Fairbanks", "Moreau", "Kowalski",
                "Lindqvist", "Ramirez", "Thornton", "Abernathy", "Petrov", "Calloway",
                "Ferreira", "Mbeki", "Halloran", "Rosales", "Tanaka", "Winslow", "Duarte",
                "Everhart", "Chowdhury", "Lockwood"],
    "indian": ["Iyer", "Kulkarni", "Reddy", "Banerjee", "Deshmukh", "Nair", "Chatterjee",
               "Menon", "Pillai", "Joshi", "Bhatt", "Saxena", "Verma", "Rangan", "Mahajan",
               "Sengupta", "Balan", "Trivedi", "Krishnan", "Malhotra"],
    "german": ["Brandt", "Vogel", "Kessler", "Lehmann", "Hartmann", "Engel", "Roth", "Baumann",
               "Neumann", "Falk", "Sommer", "Winkler", "Kruger", "Albrecht", "Lorenz"],
}

MIDDLE_INITIAL_RATE = 0.30

GENDERS: List[Tuple[str, float]] = [
    ("Female", 0.47), ("Male", 0.47), ("Non-binary", 0.03), ("Prefer not to say", 0.03),
]

# Country code (ISO alpha-3, as in countries.country_code) -> name group.
COUNTRY_NAME_GROUP: Dict[str, str] = {
    "USA": "western", "CAN": "western", "AUS": "western", "IND": "indian", "DEU": "german",
}

# --- Languages (supporting_languages.language_id) -------------------------------
# Weighted (language_id, weight) choices for language_1 per country; language_2/3
# are drawn from SECONDARY_LANGUAGES[country].
PRIMARY_LANGUAGES: Dict[str, List[Tuple[int, float]]] = {
    "USA": [(1, 0.85), (4, 0.10), (2, 0.03), (3, 0.02)],
    "CAN": [(1, 0.70), (5, 0.25), (2, 0.05)],
    "AUS": [(1, 0.90), (2, 0.07), (3, 0.03)],
    "IND": [(3, 0.40), (1, 0.20), (12, 0.15), (7, 0.15), (10, 0.10)],
    "DEU": [(11, 0.90), (1, 0.05), (9, 0.05)],
}
SECONDARY_LANGUAGES: Dict[str, List[int]] = {
    "USA": [1, 4, 5, 2, 3, 6],
    "CAN": [1, 5, 4, 2],
    "AUS": [1, 2, 3, 4],
    "IND": [1, 3, 12, 7, 10, 4],
    "DEU": [1, 11, 5, 9],
}
# India: state_code -> home-state language id overriding the weighted draw.
INDIA_STATE_LANGUAGE: Dict[str, int] = {"TG": 12, "WB": 7, "DL": 3, "UP": 3, "RJ": 3}

# --- Addresses -----------------------------------------------------------------
STREET_NAMES: List[str] = [
    "Maple", "Oak", "Cedar", "Pine", "Elm", "Willow", "Lakeview", "Sunset", "Hillcrest",
    "Meadow", "Riverside", "Highland", "Mill", "Spring", "Ridge", "Orchard", "Chestnut",
    "Birch", "Magnolia", "Harbor", "Prairie", "Summit", "Juniper", "Laurel", "Heritage",
    "Canyon", "Brookfield", "Cypress", "Aspen", "Foxglove",
]
STREET_SUFFIXES: List[str] = ["Street", "Avenue", "Road", "Lane", "Drive", "Court", "Boulevard", "Way"]
GERMAN_STREET_STEMS: List[str] = [
    "Linden", "Bahnhof", "Garten", "Schul", "Berg", "Wald", "Wiesen", "Kirch", "Muhlen", "Rosen",
]
SECONDARY_ADDRESS: List[str] = ["Apt {n}", "Unit {n}", "Suite {n}", "Floor {n}"]

# --- Volunteer availability -----------------------------------------------------
DAYS: List[str] = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
TIME_SLOTS: List[str] = ["morning", "afternoon", "evening"]
GOVT_ID_KINDS: List[str] = ["drivers_license", "passport", "state_id"]

AUTH_PROVIDERS: List[Tuple[str, float]] = [("google", 0.45), ("apple", 0.20), ("facebook", 0.10)]
# remaining probability (0.25) -> NULL: user signed up with email/password.

# --- Organizations --------------------------------------------------------------
ORG_PREFIXES: List[str] = [
    "Harbor Light", "Willow Creek", "Summit", "Riverbend", "Cedar Grove", "Northgate",
    "Bright Horizon", "Open Door", "Common Ground", "Steady Hands", "Meridian", "Evergreen",
    "Lantern", "Keystone", "Bridgeway", "Sunrise", "Stonebridge", "Clearwater", "Silver Oak",
    "Greenfield", "Oakridge", "Trailhead", "Cornerstone", "Lakeside", "Fieldstone",
    "Beacon", "Hearth", "Compass", "Pathway", "Kindred",
]
# (name word, mission sentence). {city} is replaced by the organization's city.
ORG_FOCUS: List[Tuple[str, str]] = [
    ("Food Bank", "Distributes groceries and hot meals to households facing food insecurity in {city}."),
    ("Housing", "Helps families in {city} find and keep safe, affordable housing."),
    ("Literacy", "Offers free reading and adult-education classes to learners in {city}."),
    ("Health Clinic", "Provides low-cost primary care and health screenings for residents of {city}."),
    ("Youth Services", "Runs after-school programs and mentoring for young people in {city}."),
    ("Senior Care", "Supports older adults in {city} with rides, home visits and companionship."),
    ("Immigrant Aid", "Connects newcomers in {city} with legal help, language classes and job training."),
    ("Disability Services", "Advocates for and assists people with disabilities living in {city}."),
    ("Veterans Support", "Assists veterans in {city} with benefits, housing and employment."),
    ("Environmental Action", "Organizes community cleanups and conservation projects around {city}."),
    ("Mental Health", "Offers counseling, peer support groups and crisis referrals in {city}."),
    ("Job Training", "Trains and places job seekers in {city} in in-demand skills."),
    ("Disaster Relief", "Coordinates volunteers and supplies for emergency response in {city}."),
    ("Legal Aid", "Provides free legal advice and representation to residents of {city}."),
    ("Clothing Closet", "Collects and distributes clothing and household essentials in {city}."),
    ("Transportation", "Arranges volunteer rides to medical and work appointments in {city}."),
]
NON_PROFIT_KINDS: List[str] = ["Foundation", "Alliance", "Network", "Collective", "Coalition",
                               "Project", "Association", "Fund", "Society", "Council"]
FOR_PROFIT_KINDS: List[str] = ["Solutions", "Services", "Partners", "Group", "Consulting", "Care Co."]
