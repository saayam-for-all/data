"""Reference data and helpers for the Virginia mock-data generator.

Everything here is either public reference data (ISO country codes, US state
names/codes, approximate state centroids) or synthetic pools used to compose
fake people, organizations and places. No real user data is present.
"""

import csv
import json
import os
from datetime import timedelta

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

# (country_id, country_name, phone_code, country_code, is_eu_member)
# country_id values match the ids already used in the Virginia countries
# table so the mock rows line up with existing reference data.
COUNTRIES = [
    (1, "AFGHANISTAN", "93", "AFG", False),
    (13, "AUSTRALIA", "61", "AUS", False),
    (14, "AUSTRIA", "43", "AUT", True),
    (21, "BELGIUM", "32", "BEL", True),
    (30, "BRAZIL", "55", "BRA", False),
    (38, "CANADA", "1", "CAN", False),
    (44, "CHINA", "86", "CHN", False),
    (57, "CZECH_REPUBLIC", "420", "CZE", True),
    (58, "DENMARK", "45", "DNK", True),
    (67, "EGYPT", "20", "EGY", False),
    (74, "FINLAND", "358", "FIN", True),
    (75, "FRANCE", "33", "FRA", True),
    (82, "GERMANY", "49", "DEU", True),
    (94, "GREECE", "30", "GRC", True),
    (104, "INDIA", "91", "IND", False),
    (105, "INDONESIA", "62", "IDN", False),
    (108, "IRELAND", "353", "IRL", True),
    (110, "ITALY", "39", "ITA", True),
    (113, "JAPAN", "81", "JPN", False),
    (120, "KENYA", "254", "KEN", False),
    (144, "MEXICO", "52", "MEX", False),
    (156, "NETHERLANDS", "31", "NLD", True),
    (158, "NEW_ZEALAND", "64", "NZL", False),
    (165, "NORWAY", "47", "NOR", False),
    (174, "PHILIPPINES", "63", "PHL", False),
    (176, "POLAND", "48", "POL", True),
    (177, "PORTUGAL", "351", "PRT", True),
    (203, "SPAIN", "34", "ESP", True),
    (211, "SWEDEN", "46", "SWE", True),
    (231, "UNITED_KINGDOM", "44", "GBR", False),
    (233, "UNITED_STATES_OF_AMERICA", "1", "USA", False),
]

US_COUNTRY_ID = 233

# (state_id, state_name, centroid_lat, centroid_lon, zip_prefix, time_zone)
# state_id is the two-letter code because states.state_id is VARCHAR(50).
# Centroids are approximate and are only used to keep generated coordinates,
# cities and ZIP codes inside the state they claim to belong to.
US_STATES = [
    ("AL", "Alabama", 32.8, -86.8, "350", "America/Chicago"),
    ("AK", "Alaska", 64.0, -152.0, "995", "America/Anchorage"),
    ("AZ", "Arizona", 34.3, -111.7, "850", "America/Phoenix"),
    ("AR", "Arkansas", 34.9, -92.4, "720", "America/Chicago"),
    ("CA", "California", 37.2, -119.4, "940", "America/Los_Angeles"),
    ("CO", "Colorado", 39.0, -105.5, "802", "America/Denver"),
    ("CT", "Connecticut", 41.6, -72.7, "061", "America/New_York"),
    ("DE", "Delaware", 39.0, -75.5, "199", "America/New_York"),
    ("DC", "District of Columbia", 38.9, -77.0, "200", "America/New_York"),
    ("FL", "Florida", 28.6, -82.4, "331", "America/New_York"),
    ("GA", "Georgia", 32.6, -83.4, "303", "America/New_York"),
    ("HI", "Hawaii", 20.8, -156.4, "968", "Pacific/Honolulu"),
    ("ID", "Idaho", 44.4, -114.6, "837", "America/Boise"),
    ("IL", "Illinois", 40.0, -89.2, "606", "America/Chicago"),
    ("IN", "Indiana", 39.9, -86.3, "462", "America/Indiana/Indianapolis"),
    ("IA", "Iowa", 42.1, -93.5, "503", "America/Chicago"),
    ("KS", "Kansas", 38.5, -98.4, "662", "America/Chicago"),
    ("KY", "Kentucky", 37.5, -85.3, "402", "America/New_York"),
    ("LA", "Louisiana", 31.1, -92.0, "701", "America/Chicago"),
    ("ME", "Maine", 45.4, -69.2, "040", "America/New_York"),
    ("MD", "Maryland", 39.0, -76.8, "212", "America/New_York"),
    ("MA", "Massachusetts", 42.3, -71.8, "021", "America/New_York"),
    ("MI", "Michigan", 44.3, -85.4, "482", "America/Detroit"),
    ("MN", "Minnesota", 46.3, -94.3, "554", "America/Chicago"),
    ("MS", "Mississippi", 32.7, -89.7, "392", "America/Chicago"),
    ("MO", "Missouri", 38.4, -92.5, "631", "America/Chicago"),
    ("MT", "Montana", 47.0, -109.6, "591", "America/Denver"),
    ("NE", "Nebraska", 41.5, -99.8, "681", "America/Chicago"),
    ("NV", "Nevada", 39.3, -116.6, "891", "America/Los_Angeles"),
    ("NH", "New Hampshire", 43.7, -71.6, "032", "America/New_York"),
    ("NJ", "New Jersey", 40.2, -74.7, "070", "America/New_York"),
    ("NM", "New Mexico", 34.4, -106.1, "871", "America/Denver"),
    ("NY", "New York", 42.9, -75.5, "100", "America/New_York"),
    ("NC", "North Carolina", 35.5, -79.4, "272", "America/New_York"),
    ("ND", "North Dakota", 47.4, -100.5, "581", "America/Chicago"),
    ("OH", "Ohio", 40.3, -82.8, "432", "America/New_York"),
    ("OK", "Oklahoma", 35.6, -97.5, "731", "America/Chicago"),
    ("OR", "Oregon", 43.9, -120.6, "972", "America/Los_Angeles"),
    ("PA", "Pennsylvania", 40.9, -77.8, "191", "America/New_York"),
    ("RI", "Rhode Island", 41.7, -71.6, "029", "America/New_York"),
    ("SC", "South Carolina", 33.9, -80.9, "292", "America/New_York"),
    ("SD", "South Dakota", 44.4, -100.2, "571", "America/Chicago"),
    ("TN", "Tennessee", 35.9, -86.4, "372", "America/Chicago"),
    ("TX", "Texas", 31.5, -99.3, "750", "America/Chicago"),
    ("UT", "Utah", 39.3, -111.7, "841", "America/Denver"),
    ("VT", "Vermont", 44.1, -72.7, "054", "America/New_York"),
    ("VA", "Virginia", 37.5, -78.9, "232", "America/New_York"),
    ("WA", "Washington", 47.4, -120.5, "981", "America/Los_Angeles"),
    ("WV", "West Virginia", 38.6, -80.6, "250", "America/New_York"),
    ("WI", "Wisconsin", 44.6, -89.7, "537", "America/Chicago"),
    ("WY", "Wyoming", 43.0, -107.6, "820", "America/Denver"),
]

# The Virginia help_categories taxonomy, mirrored from
# data-analytics/sql/help_category.csv so mock user_skills rows join against
# the same cat_id values the application uses.
HELP_CATEGORIES = [
    ("0.0.0.0.0", "GENERAL_CATEGORY"),
    ("1", "FOOD_AND_ESSENTIALS"),
    ("1.1", "FOOD_ASSISTANCE"),
    ("1.2", "GROCERY_SHOPPING_AND_DELIVERY"),
    ("1.3", "COOKING_HELP"),
    ("1.3.1", "MEAL_PREP_BASIC"),
    ("1.3.2", "FESTIVE_OR_BULK_COOKING"),
    ("1.3.3", "NUTRITIONAL_MEAL_PLANNING"),
    ("1.3.4", "CULTURAL_CUISINE_GUIDANCE"),
    ("1.3.5", "OTHER_COOKING_HELP"),
    ("2", "CLOTHING_ASSISTANCE"),
    ("2.1", "DONATE_CLOTHES"),
    ("2.2", "BORROW_CLOTHES"),
    ("2.3", "EMERGENCY_CLOTHING_ASSISTANCE"),
    ("2.4", "TAILORING"),
    ("3", "HOUSING_ASSISTANCE"),
    ("3.1", "LEASE_SUPPORT"),
    ("3.2", "TENANT_RENT_SUPPORT"),
    ("3.3", "REPAIR_MAINTENANCE_SUPPORT"),
    ("3.3.1", "PLUMBING"),
    ("3.3.2", "HANDYMAN"),
    ("3.3.3", "ELECTRICIAN"),
    ("3.3.4", "CARPENTRY"),
    ("3.3.5", "GARDEN"),
    ("3.3.6", "HVAC_AIR_CONDITIONING"),
    ("3.3.7", "ROOFING"),
    ("3.3.8", "LOCKSMITH"),
    ("3.3.9", "PAINTING"),
    ("3.3.10", "MASONRY_OR_CONCRETE"),
    ("4", "HEALTHCARE_SUPPORT"),
    ("4.1", "MEDICAL_APPOINTMENT_ASSISTANCE"),
    ("4.2", "MEDICATION_PICKUP"),
    ("4.3", "ELDER_CARE_SUPPORT"),
    ("4.4", "MENTAL_HEALTH_SUPPORT"),
    ("4.5", "DISABILITY_SUPPORT"),
    ("5", "EDUCATION_SUPPORT"),
    ("5.1", "TUTORING"),
    ("5.2", "SCHOOL_SUPPLIES"),
    ("5.3", "COLLEGE_APPLICATION_GUIDANCE"),
    ("5.4", "LANGUAGE_LEARNING"),
    ("5.5", "ADULT_LITERACY"),
    ("6", "EMPLOYMENT_SUPPORT"),
    ("6.1", "RESUME_REVIEW"),
    ("6.2", "INTERVIEW_PREPARATION"),
    ("6.3", "JOB_SEARCH_ASSISTANCE"),
    ("6.4", "CAREER_MENTORING"),
    ("6.5", "SKILL_TRAINING"),
    ("7", "TRANSPORTATION_SUPPORT"),
    ("7.1", "RIDE_TO_APPOINTMENT"),
    ("7.2", "GROCERY_RUN"),
    ("7.3", "AIRPORT_PICKUP"),
    ("7.4", "VEHICLE_REPAIR_GUIDANCE"),
    ("8", "LEGAL_ASSISTANCE"),
    ("8.1", "IMMIGRATION_PAPERWORK"),
    ("8.2", "TENANT_RIGHTS_GUIDANCE"),
    ("8.3", "SMALL_CLAIMS_GUIDANCE"),
    ("8.4", "DOCUMENT_NOTARIZATION"),
    ("9", "FINANCIAL_ASSISTANCE"),
    ("9.1", "BUDGETING_GUIDANCE"),
    ("9.2", "TAX_FILING_HELP"),
    ("9.3", "BENEFITS_ENROLLMENT"),
    ("9.4", "DEBT_COUNSELING"),
    ("10", "TECHNOLOGY_SUPPORT"),
    ("10.1", "DEVICE_SETUP"),
    ("10.2", "INTERNET_ACCESS_GUIDANCE"),
    ("10.3", "SOFTWARE_TROUBLESHOOTING"),
    ("10.4", "DIGITAL_LITERACY"),
    ("11", "DISASTER_RELIEF"),
    ("11.1", "EMERGENCY_SHELTER"),
    ("11.2", "SUPPLY_DISTRIBUTION"),
    ("11.3", "EVACUATION_SUPPORT"),
    ("11.4", "POST_DISASTER_CLEANUP"),
    ("12", "COMMUNITY_SERVICES"),
    ("12.1", "EVENT_VOLUNTEERING"),
    ("12.2", "TRANSLATION_SERVICES"),
    ("12.3", "COMPANIONSHIP_VISITS"),
    ("12.4", "PET_CARE_SUPPORT"),
    ("12.5", "CHILD_CARE_SUPPORT"),
    ("12.6", "MOVING_HELP"),
    ("12.7", "OTHER_COMMUNITY_SERVICES"),
]

SKILL_LEVELS = ["BEGINNER", "INTERMEDIATE", "ADVANCED", "EXPERT"]
ORG_TYPES = ["non_profit", "for_profit"]
ORG_SIZES = ["small", "medium", "large"]
GENDERS = ["Male", "Female", "Non-binary", "Prefer not to say"]
AUTH_PROVIDERS = ["cognito", "google", "facebook", "apple"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday"]
TIME_SLOTS = ["06:00-09:00", "09:00-12:00", "12:00-15:00", "15:00-18:00",
              "18:00-21:00", "21:00-00:00"]

# Synthetic name pools. Common given/family names carry no personal
# information on their own, and they are recombined at random.
FIRST_NAMES = [
    "Aarav", "Abigail", "Adrian", "Aisha", "Alejandro", "Amara", "Amelia",
    "Andre", "Anika", "Arjun", "Ayana", "Beatriz", "Benjamin", "Bianca",
    "Caleb", "Camila", "Carmen", "Chen", "Chloe", "Damian", "Daniela",
    "Darius", "Devon", "Diego", "Elena", "Eli", "Emeka", "Esther", "Ethan",
    "Fatima", "Felix", "Gabriel", "Grace", "Hana", "Harold", "Hiroshi",
    "Ibrahim", "Imani", "Isabel", "Ivan", "Jasmine", "Javier", "Jonas",
    "Julia", "Kaito", "Karim", "Katya", "Kwame", "Lars", "Leilani", "Liam",
    "Lucia", "Mateo", "Maya", "Mei", "Miriam", "Nadia", "Nathan", "Nia",
    "Noor", "Olivia", "Omar", "Priya", "Quinn", "Rafael", "Rania", "Ravi",
    "Rosa", "Samuel", "Sana", "Sebastian", "Simone", "Sofia", "Tariq",
    "Theo", "Uma", "Valeria", "Viktor", "Wei", "Yara", "Yusuf", "Zara",
]

MIDDLE_NAMES = [
    "Alex", "Blake", "Cruz", "Dae", "Ellis", "Faye", "Gray", "Hale", "Iris",
    "Jae", "Kai", "Lee", "Marin", "Noel", "Ove", "Paz", "Quill", "Rae",
    "Sage", "True", "Vale", "Wren", "Yun", "Zane",
]

LAST_NAMES = [
    "Abara", "Ahmed", "Alvarez", "Andersen", "Bakker", "Banerjee", "Bello",
    "Bergman", "Bianchi", "Boateng", "Cabrera", "Castillo", "Chandra",
    "Chowdhury", "Costa", "Dalton", "Diallo", "Dubois", "Duarte", "Eriksen",
    "Espinoza", "Farah", "Fernandes", "Fischer", "Gallagher", "Garcia",
    "Gomes", "Grover", "Haddad", "Hansen", "Hoffman", "Ibarra", "Ishikawa",
    "Jimenez", "Kapoor", "Keller", "Khalil", "Kimura", "Kowalski", "Larsen",
    "Lindqvist", "Lombardi", "Mabaso", "Marchetti", "Mendes", "Mensah",
    "Nakamura", "Navarro", "Nguyen", "Novak", "Okafor", "Oliveira", "Ortega",
    "Padilla", "Pereira", "Petrov", "Quintero", "Rahman", "Ramirez", "Reyes",
    "Rossi", "Sandoval", "Santos", "Sharma", "Silva", "Sorensen", "Suzuki",
    "Tanaka", "Tremblay", "Vargas", "Vasquez", "Vogel", "Wagner", "Walsh",
    "Yamada", "Yilmaz", "Zaman", "Zhang", "Ziegler",
]

# City-name components. Combined into plausible but invented place names so
# the dataset does not lean on any specific real municipality.
CITY_PREFIXES = [
    "Auburn", "Bayside", "Birch", "Bridge", "Cedar", "Clear", "Crest",
    "Eagle", "Elm", "Fair", "Fern", "Glen", "Granite", "Harbor", "Hazel",
    "Iron", "Juniper", "Lake", "Laurel", "Maple", "Meadow", "Mill", "North",
    "Oak", "Pine", "Prairie", "Quarry", "Red", "River", "Rock", "Rose",
    "Silver", "South", "Spring", "Stone", "Summit", "Sunny", "Thorn",
    "Union", "Valley", "Walnut", "West", "White", "Willow", "Winter",
]

CITY_SUFFIXES = [
    "brook", "burg", "bury", "creek", "dale", "field", "ford", "haven",
    "hill", "lake", "mont", "port", "ridge", "shire", "side", "ton", "vale",
    "view", "ville", "wood",
]

STREET_NAMES = [
    "Alder", "Beacon", "Birchwood", "Canal", "Chestnut", "Clover", "Copper",
    "Dogwood", "Foundry", "Garnet", "Harvest", "Hickory", "Juniper",
    "Kingfisher", "Lantern", "Linden", "Marigold", "Merchant", "Mulberry",
    "Orchard", "Pembroke", "Quarry", "Redwood", "Sable", "Sycamore",
    "Tanglewood", "Thistle", "Wexford", "Windmill", "Yarrow",
]

STREET_TYPES = ["Ave", "Blvd", "Ct", "Dr", "Ln", "Pkwy", "Pl", "Rd", "St",
                "Ter", "Way"]

UNIT_TYPES = ["Apt", "Suite", "Unit", "Bldg"]

ORG_PREFIXES = [
    "Bright", "Common", "Compass", "Cornerstone", "Evergreen", "First Light",
    "Golden Bridge", "Harbor", "Helping Hands", "Horizon", "Keystone",
    "Lantern", "Lighthouse", "New Leaf", "Northstar", "Open Door", "Pathway",
    "Riverstone", "Safe Harbor", "Silver Oak", "Solidarity", "Steady Hand",
    "Sunrise", "Together", "Trailhead", "Trueline", "Unity", "Waypoint",
    "Wellspring", "Willow Creek",
]

ORG_SUFFIXES = [
    "Alliance", "Assistance Network", "Care Collective", "Community Fund",
    "Community Services", "Cooperative", "Foundation", "Initiative",
    "Mutual Aid", "Outreach", "Partners", "Relief Group", "Resource Center",
    "Support Society", "Trust", "Volunteers",
]

ORG_MISSIONS = [
    "Connects neighbors with volunteers who can help during short-term crises.",
    "Provides groceries and hot meals to households facing food insecurity.",
    "Coordinates transportation for medical appointments in rural counties.",
    "Runs after-school tutoring and literacy programs for local families.",
    "Distributes emergency supplies in the first 72 hours after a disaster.",
    "Offers free resume review and interview coaching to job seekers.",
    "Matches retired professionals with community groups needing expertise.",
    "Supports older adults with home repairs and regular companionship visits.",
    "Helps newly arrived families navigate housing, schools and paperwork.",
    "Provides bilingual translation support at clinics and public offices.",
    "Delivers digital-literacy workshops in libraries and community centers.",
    "Operates a seasonal clothing bank serving low-income households.",
    "Pairs volunteer tradespeople with residents needing urgent home repairs.",
    "Runs peer mental-health support circles for caregivers.",
    "Coordinates pet fostering for owners in temporary housing crises.",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_user_id(seq):
    """Mirror the DB generate_sid() trigger: SID-00-NNN-NNN-NNN-NNN-NNN."""
    padded = str(seq).zfill(15)
    return "SID-00-" + "-".join(padded[i:i + 3] for i in range(0, 15, 3))


def make_org_id(seq):
    """Mirror the DB generate_org_id() trigger: ORG-NNN-NNN-NNN-NNNN."""
    padded = str(seq).zfill(13)
    return "ORG-{}-{}-{}-{}".format(padded[0:3], padded[3:6], padded[6:9],
                                    padded[9:13])


def ts(dt):
    """PostgreSQL-compatible timestamp literal, e.g. 2026-08-31 14:30:00."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def random_datetime(rng, start, end):
    """A random datetime in [start, end)."""
    return start + timedelta(seconds=rng.randrange(int((end - start).total_seconds())))


def jitter_point(rng, lat, lon, radius_deg=0.35):
    """A coordinate near (lat, lon), used to keep points inside their state."""
    return (round(lat + rng.uniform(-radius_deg, radius_deg), 6),
            round(lon + rng.uniform(-radius_deg, radius_deg), 6))


def wkt_point(lat, lon):
    """EWKT for a geography(Point, 4326) column. Longitude comes first."""
    return "SRID=4326;POINT({} {})".format(lon, lat)


def pg_point(lat, lon):
    """Literal for a PostgreSQL point column, stored as (x, y) = (lon, lat)."""
    return "({},{})".format(lon, lat)


def fictional_phone(rng):
    """555-01xx is the reserved fictional US exchange - never a real number."""
    area = rng.choice([202, 205, 212, 213, 214, 303, 305, 312, 404, 415, 503,
                       512, 602, 617, 702, 703, 704, 801, 804, 907])
    return "+1-{}-555-01{:02d}".format(area, rng.randrange(100))


def json_field(value):
    """JSONB column value, rendered compactly so the CSV stays readable."""
    return json.dumps(value, separators=(",", ":"))


def write_csv(out_dir, table, header, rows):
    """Write one table to <out_dir>/<table>.csv and return the path."""
    path = os.path.join(out_dir, table + ".csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def read_csv(out_dir, table):
    """Read <out_dir>/<table>.csv back as a list of dicts."""
    path = os.path.join(out_dir, table + ".csv")
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
