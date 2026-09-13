"""
Static, curated reference data used to keep the generated mock data
geographically consistent (country -> state -> city) and to give
organizations/help-categories realistic-looking (but non-authoritative)
labels.

Nothing in this file is personal or sensitive data - it is public
geography (country/state/city names and approximate coordinates) plus
generic name/word pools used to assemble fully synthetic people and
organizations.
"""

# ---------------------------------------------------------------------------
# Countries: (country_name, phone_code, country_code[ISO alpha-2], is_eu_member)
# ---------------------------------------------------------------------------
COUNTRIES = [
    ("United States", "1", "US", False),
    ("Canada", "1", "CA", False),
    ("India", "91", "IN", False),
    ("United Kingdom", "44", "GB", False),
    ("Germany", "49", "DE", True),
    ("France", "33", "FR", True),
    ("Ireland", "353", "IE", True),
    ("Sweden", "46", "SE", True),
    ("Spain", "34", "ES", True),
    ("Italy", "39", "IT", True),
    ("Netherlands", "31", "NL", True),
    ("Australia", "61", "AU", False),
    ("Mexico", "52", "MX", False),
    ("Brazil", "55", "BR", False),
    ("Japan", "81", "JP", False),
    ("South Africa", "27", "ZA", False),
    ("Nigeria", "234", "NG", False),
    ("Singapore", "65", "SG", False),
    ("New Zealand", "64", "NZ", False),
    ("United Arab Emirates", "971", "AE", False),
]

# ---------------------------------------------------------------------------
# States/provinces: (country_code, state_code, state_name)
# state_id in the generated data is built as f"{country_code}-{state_code}"
# so it stays globally unique across countries.
# ---------------------------------------------------------------------------
US_STATES = [
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
    ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
    ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"), ("ID", "Idaho"),
    ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"), ("KS", "Kansas"),
    ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"), ("MD", "Maryland"),
    ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"), ("MS", "Mississippi"),
    ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"), ("NV", "Nevada"),
    ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"), ("NY", "New York"),
    ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"), ("OK", "Oklahoma"),
    ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"), ("SC", "South Carolina"),
    ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"), ("UT", "Utah"),
    ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"), ("WV", "West Virginia"),
    ("WI", "Wisconsin"), ("WY", "Wyoming"), ("DC", "District of Columbia"),
]

OTHER_STATES = [
    # (country_code, state_code, state_name)
    ("CA", "ON", "Ontario"),
    ("CA", "BC", "British Columbia"),
    ("CA", "QC", "Quebec"),
    ("IN", "MH", "Maharashtra"),
    ("IN", "DL", "Delhi"),
    ("IN", "KA", "Karnataka"),
    ("GB", "ENG", "England"),
    ("GB", "SCT", "Scotland"),
    ("DE", "BY", "Bavaria"),
    ("DE", "BE", "Berlin"),
    ("FR", "IDF", "Ile-de-France"),
    ("IE", "L", "Leinster"),
    ("SE", "AB", "Stockholm County"),
    ("ES", "MD", "Madrid"),
    ("IT", "LAZ", "Lazio"),
    ("NL", "NH", "North Holland"),
    ("AU", "NSW", "New South Wales"),
    ("AU", "VIC", "Victoria"),
    ("MX", "CDMX", "Ciudad de Mexico"),
    ("BR", "SP", "Sao Paulo"),
    ("JP", "TKY", "Tokyo"),
    ("ZA", "GP", "Gauteng"),
    ("NG", "LA", "Lagos"),
    ("SG", "SG", "Singapore"),
    ("NZ", "AUK", "Auckland"),
    ("AE", "DXB", "Dubai"),
]

# ---------------------------------------------------------------------------
# Cities: keyed by (country_code, state_code) -> [(city_name, lat, lon), ...]
# Coordinates are approximate (state-capital / major-city centroids), which
# is sufficient for "plausibly located" synthetic data.
# ---------------------------------------------------------------------------
US_STATE_CAPITALS = {
    "AL": ("Montgomery", 32.3792, -86.3077), "AK": ("Juneau", 58.3019, -134.4197),
    "AZ": ("Phoenix", 33.4484, -112.0740), "AR": ("Little Rock", 34.7465, -92.2896),
    "CA": ("Sacramento", 38.5816, -121.4944), "CO": ("Denver", 39.7392, -104.9903),
    "CT": ("Hartford", 41.7658, -72.6734), "DE": ("Dover", 39.1582, -75.5244),
    "FL": ("Tallahassee", 30.4383, -84.2807), "GA": ("Atlanta", 33.7490, -84.3880),
    "HI": ("Honolulu", 21.3069, -157.8583), "ID": ("Boise", 43.6150, -116.2023),
    "IL": ("Springfield", 39.7817, -89.6501), "IN": ("Indianapolis", 39.7684, -86.1581),
    "IA": ("Des Moines", 41.5868, -93.6250), "KS": ("Topeka", 39.0473, -95.6752),
    "KY": ("Frankfort", 38.2009, -84.8733), "LA": ("Baton Rouge", 30.4515, -91.1871),
    "ME": ("Augusta", 44.3106, -69.7795), "MD": ("Annapolis", 38.9784, -76.4922),
    "MA": ("Boston", 42.3601, -71.0589), "MI": ("Lansing", 42.7325, -84.5555),
    "MN": ("Saint Paul", 44.9537, -93.0900), "MS": ("Jackson", 32.2988, -90.1848),
    "MO": ("Jefferson City", 38.5767, -92.1735), "MT": ("Helena", 46.5891, -112.0391),
    "NE": ("Lincoln", 40.8136, -96.7026), "NV": ("Carson City", 39.1638, -119.7674),
    "NH": ("Concord", 43.2081, -71.5376), "NJ": ("Trenton", 40.2206, -74.7597),
    "NM": ("Santa Fe", 35.6870, -105.9378), "NY": ("Albany", 42.6526, -73.7562),
    "NC": ("Raleigh", 35.7796, -78.6382), "ND": ("Bismarck", 46.8083, -100.7837),
    "OH": ("Columbus", 39.9612, -82.9988), "OK": ("Oklahoma City", 35.4676, -97.5164),
    "OR": ("Salem", 44.9429, -123.0351), "PA": ("Harrisburg", 40.2732, -76.8867),
    "RI": ("Providence", 41.8240, -71.4128), "SC": ("Columbia", 34.0007, -81.0348),
    "SD": ("Pierre", 44.3683, -100.3510), "TN": ("Nashville", 36.1627, -86.7816),
    "TX": ("Austin", 30.2672, -97.7431), "UT": ("Salt Lake City", 40.7608, -111.8910),
    "VT": ("Montpelier", 44.2601, -72.5754), "VA": ("Richmond", 37.5407, -77.4360),
    "WA": ("Olympia", 47.0379, -122.9007), "WV": ("Charleston", 38.3498, -81.6326),
    "WI": ("Madison", 43.0731, -89.4012), "WY": ("Cheyenne", 41.1400, -104.8202),
    "DC": ("Washington", 38.9072, -77.0369),
}

# A second, larger city for a subset of states, for variety.
US_EXTRA_CITIES = {
    "CA": ("Los Angeles", 34.0522, -118.2437),
    "NY": ("New York City", 40.7128, -74.0060),
    "IL": ("Chicago", 41.8781, -87.6298),
    "TX": ("Houston", 29.7604, -95.3698),
    "FL": ("Miami", 25.7617, -80.1918),
    "WA": ("Seattle", 47.6062, -122.3321),
    "NV": ("Las Vegas", 36.1699, -115.1398),
    "NC": ("Charlotte", 35.2271, -80.8431),
    "MI": ("Detroit", 42.3314, -83.0458),
    "PA": ("Philadelphia", 39.9526, -75.1652),
    "OH": ("Cleveland", 41.4993, -81.6944),
    "VA": ("Virginia Beach", 36.8529, -75.9780),
}

OTHER_CITIES = {
    ("CA", "ON"): [("Toronto", 43.6532, -79.3832)],
    ("CA", "BC"): [("Vancouver", 49.2827, -123.1207)],
    ("CA", "QC"): [("Montreal", 45.5019, -73.5674)],
    ("IN", "MH"): [("Mumbai", 19.0760, 72.8777)],
    ("IN", "DL"): [("New Delhi", 28.6139, 77.2090)],
    ("IN", "KA"): [("Bengaluru", 12.9716, 77.5946)],
    ("GB", "ENG"): [("London", 51.5072, -0.1276)],
    ("GB", "SCT"): [("Edinburgh", 55.9533, -3.1883)],
    ("DE", "BY"): [("Munich", 48.1351, 11.5820)],
    ("DE", "BE"): [("Berlin", 52.5200, 13.4050)],
    ("FR", "IDF"): [("Paris", 48.8566, 2.3522)],
    ("IE", "L"): [("Dublin", 53.3498, -6.2603)],
    ("SE", "AB"): [("Stockholm", 59.3293, 18.0686)],
    ("ES", "MD"): [("Madrid", 40.4168, -3.7038)],
    ("IT", "LAZ"): [("Rome", 41.9028, 12.4964)],
    ("NL", "NH"): [("Amsterdam", 52.3676, 4.9041)],
    ("AU", "NSW"): [("Sydney", -33.8688, 151.2093)],
    ("AU", "VIC"): [("Melbourne", -37.8136, 144.9631)],
    ("MX", "CDMX"): [("Mexico City", 19.4326, -99.1332)],
    ("BR", "SP"): [("Sao Paulo", -23.5505, -46.6333)],
    ("JP", "TKY"): [("Tokyo", 35.6762, 139.6503)],
    ("ZA", "GP"): [("Johannesburg", -26.2041, 28.0473)],
    ("NG", "LA"): [("Lagos", 6.5244, 3.3792)],
    ("SG", "SG"): [("Singapore", 1.3521, 103.8198)],
    ("NZ", "AUK"): [("Auckland", -36.8485, 174.7633)],
    ("AE", "DXB"): [("Dubai", 25.2048, 55.2708)],
}

# ---------------------------------------------------------------------------
# Synthetic person-name pools (generic given/family names - not tied to any
# real individual). Used only to assemble fake full names/emails.
# ---------------------------------------------------------------------------
FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Avery",
    "Sam", "Drew", "Cameron", "Reese", "Quinn", "Rowan", "Hayden", "Skyler",
    "Priya", "Wei", "Fatima", "Diego", "Amara", "Kenji", "Liam", "Noah",
    "Emma", "Olivia", "Sofia", "Mateo", "Chidi", "Anika", "Lucas", "Grace",
]
MIDDLE_INITIALS = list("ABCDEFGHJKLMNPRSTW")
LAST_NAMES = [
    "Anderson", "Baker", "Carter", "Diaz", "Evans", "Foster", "Garcia",
    "Harris", "Ibrahim", "Johnson", "Kumar", "Lee", "Martinez", "Nguyen",
    "OBrien", "Patel", "Quinn", "Robinson", "Singh", "Thompson", "Ueda",
    "Vargas", "Williams", "Xu", "Young", "Zimmerman",
]
GENDERS = ["Female", "Male", "Non-binary", "Prefer not to say"]
TIME_ZONES = [
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "America/Toronto", "Europe/London", "Europe/Berlin", "Europe/Dublin",
    "Asia/Kolkata", "Asia/Tokyo", "Australia/Sydney", "Asia/Singapore",
]
AUTH_PROVIDERS = ["google", "email", "facebook", "apple", "microsoft"]

# ---------------------------------------------------------------------------
# Organization name pools (fully synthetic org names, not real organizations)
# ---------------------------------------------------------------------------
ORG_ADJECTIVES = [
    "Bright", "Unity", "Hopeful", "Bridge", "Harbor", "Cedar", "Evergreen",
    "Sunrise", "Compass", "Willow", "Maple", "Horizon", "Anchor", "Beacon",
]
ORG_NOUNS = [
    "Community", "Neighbors", "Outreach", "Volunteers", "Alliance", "Circle",
    "Network", "Coalition", "Foundation", "Collective", "Partners",
]
ORG_SUFFIXES = ["Initiative", "Project", "Society", "Fund", "Group", "Network"]

# ---------------------------------------------------------------------------
# Help-category taxonomy (reused cat_id hierarchy convention from the
# existing database/mock-data-generation/utils.py CAT_IDS list).
# ---------------------------------------------------------------------------
CAT_IDS = [
    "0.0.0.0.0",
    "1", "1.1", "1.2", "1.3", "1.3.1", "1.3.2", "1.3.3", "1.3.4", "1.3.5",
    "2", "2.1", "2.2", "2.3", "2.4",
    "3", "3.1", "3.10", "3.2", "3.3", "3.3.1", "3.3.10", "3.3.11", "3.3.12",
    "3.3.13", "3.3.2", "3.3.3", "3.3.4", "3.3.5", "3.3.6", "3.3.7", "3.3.8",
    "3.3.9", "3.4", "3.5", "3.6", "3.7", "3.8", "3.9",
    "4", "4.1", "4.2", "4.3", "4.3.1", "4.3.2", "4.3.3", "4.3.4", "4.3.5",
    "4.3.6", "4.4", "4.5", "4.6", "4.7",
    "5", "5.1", "5.1.1", "5.1.10", "5.1.11", "5.1.2", "5.1.3", "5.1.4",
    "5.1.5", "5.1.6", "5.1.7", "5.1.8", "5.1.9", "5.2", "5.3", "5.4", "5.5",
    "6", "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7", "6.8", "6.9",
]
USABLE_CAT_IDS = [c for c in CAT_IDS if c != "0.0.0.0.0"]

TOP_LEVEL_CATEGORY_NAMES = {
    "1": "Food & Groceries",
    "2": "Housing & Shelter",
    "3": "Healthcare & Medical",
    "4": "Education & Tutoring",
    "5": "Transportation",
    "6": "Emotional & Social Support",
}

CATEGORY_LABEL_BANKS = {
    "1": ["Grocery Delivery", "Meal Preparation", "Food Pantry Referral",
          "SNAP/WIC Assistance", "Community Garden Support"],
    "2": ["Emergency Shelter", "Rent Assistance", "Utility Bill Support",
          "Home Repair", "Furniture Donation"],
    "3": ["Doctor Visit Transport", "Prescription Pickup", "Health Insurance Navigation",
          "Mental Health Check-in", "Medical Equipment Loan", "Vaccination Support",
          "Elder Care Assistance", "Caregiver Respite", "Wellness Coaching",
          "Physical Therapy Transport", "Home Health Visit Support", "Hospice Companionship",
          "Dental Care Referral"],
    "4": ["Tutoring - K-12", "ESL Support", "College Application Help",
          "Job Skills Training", "Computer Literacy", "Reading Buddy Program"],
    "5": ["Rides to Appointments", "Grocery Run Transport", "Airport Pickup/Dropoff",
          "Wheelchair-Accessible Rides", "Public Transit Assistance", "Carpool Coordination",
          "Moving Day Help", "Non-Emergency Medical Transport", "School Run Transport",
          "Errand Running", "Wheelchair Ramp Assistance"],
    "6": ["Friendly Phone Call", "Companionship Visit", "Grief Support Group",
          "New Parent Support", "Isolation Check-in", "Peer Mentoring",
          "Community Event Buddy", "Holiday Companionship"],
}
