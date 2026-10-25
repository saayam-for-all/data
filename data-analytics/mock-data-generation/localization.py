"""Country- and state-aware formatting for addresses, phones and time zones.

Issue #301 requires country -> state -> city -> ZIP/location to stay coherent,
so postal codes are derived from the state a user was placed in rather than
generated at random.

Phone numbers use the 555 reserved-fiction block for every country, so no
generated number can route to a real subscriber.
"""

import random
import string

# Faker locale per focus country, so names and streets suit the country.
FAKER_LOCALE = {
    233: "en_US",
    101: "en_IN",
    39: "en_CA",
    14: "en_AU",
    82: "de_DE",
    105: "en_IE",
}

# --- US ZIP -----------------------------------------------------------------

# Inclusive range of leading three ZIP digits per state.
US_ZIP_PREFIX = {
    "AL": (350, 369), "AK": (995, 999), "AZ": (850, 865), "AR": (716, 729),
    "CA": (900, 961), "CO": (800, 816), "CT": (60, 69), "DE": (197, 199),
    "DC": (200, 205), "FL": (320, 349), "GA": (300, 319), "HI": (967, 968),
    "ID": (832, 838), "IL": (600, 629), "IN": (460, 479), "IA": (500, 528),
    "KS": (660, 679), "KY": (400, 427), "LA": (700, 714), "ME": (39, 49),
    "MD": (206, 219), "MA": (10, 27), "MI": (480, 499), "MN": (550, 567),
    "MS": (386, 397), "MO": (630, 658), "MT": (590, 599), "NE": (680, 693),
    "NV": (889, 898), "NH": (30, 38), "NJ": (70, 89), "NM": (870, 884),
    "NY": (100, 149), "NC": (270, 289), "ND": (580, 588), "OH": (430, 458),
    "OK": (730, 749), "OR": (970, 979), "PA": (150, 196), "RI": (28, 29),
    "SC": (290, 299), "SD": (570, 577), "TN": (370, 385), "TX": (750, 799),
    "UT": (840, 847), "VT": (50, 59), "VA": (220, 246), "WA": (980, 994),
    "WV": (247, 268), "WI": (530, 549), "WY": (820, 831), "PR": (6, 9),
}

# --- Other national postal schemes -----------------------------------------

# Canadian postal codes start with a province-specific letter.
CA_POSTAL_LETTER = {
    "ON": "KLMNP", "QC": "GHJ", "BC": "V", "AB": "T", "MB": "R",
    "SK": "S", "NS": "B", "NB": "E", "NL": "A", "PE": "C",
    "NT": "X", "NU": "X", "YT": "Y",
}

# Australian postcodes fall in per-state numeric ranges.
AU_POSTCODE_RANGE = {
    "NSW": (2000, 2599), "ACT": (2600, 2618), "VIC": (3000, 3999),
    "QLD": (4000, 4999), "SA": (5000, 5799), "WA": (6000, 6797),
    "TAS": (7000, 7799), "NT": (800, 899),
}

# German PLZ leading digits by federal state.
DE_PLZ_PREFIX = {
    "BE": "1", "BB": "1", "MV": "1", "ST": "3", "SN": "0", "TH": "9",
    "HH": "2", "SH": "2", "NI": "3", "HB": "2", "NW": "4", "HE": "6",
    "RP": "5", "SL": "6", "BW": "7", "BY": "8",
}

# Indian PIN leading digit by state/region.
IN_PIN_PREFIX = {
    "DL": "1", "HR": "1", "PB": "1", "CH": "1", "UP": "2", "UT": "2",
    "RJ": "3", "GJ": "3", "MH": "4", "MP": "4", "CT": "4", "AP": "5",
    "TG": "5", "KA": "5", "TN": "6", "KL": "6", "PY": "6", "WB": "7",
    "OR": "7", "AS": "7", "AN": "7", "BR": "8", "JH": "8", "GA": "4",
}

# Eircode routing keys by county.
IE_ROUTING_KEY = {
    "D": ["D01", "D02", "D04", "D06", "D08", "D12", "D15", "D24"],
    "CO": ["T12", "T23", "P31"], "G": ["H91"], "LK": ["V94"],
    "WD": ["X91"], "KE": ["W91"], "MH": ["C15"], "WW": ["A98"],
    "KK": ["R95"], "SO": ["F91"], "DL": ["F92"], "WX": ["Y35"],
    "MO": ["F23"], "CE": ["V95"], "KY": ["V92"],
}

# --- Time zones -------------------------------------------------------------

US_TIMEZONE = {
    "PACIFIC": ["CA", "WA", "OR", "NV"],
    "MOUNTAIN": ["AZ", "CO", "UT", "NM", "MT", "WY", "ID"],
    "CENTRAL": [
        "TX", "IL", "MN", "WI", "IA", "MO", "AR", "LA", "MS", "AL", "TN",
        "OK", "KS", "NE", "SD", "ND",
    ],
}
US_TIMEZONE_NAME = {
    "PACIFIC": "America/Los_Angeles",
    "MOUNTAIN": "America/Denver",
    "CENTRAL": "America/Chicago",
    "EASTERN": "America/New_York",
}

COUNTRY_TIMEZONE = {
    101: "Asia/Kolkata",
    82: "Europe/Berlin",
    105: "Europe/Dublin",
}

CA_TIMEZONE = {
    "BC": "America/Vancouver", "AB": "America/Edmonton",
    "SK": "America/Regina", "MB": "America/Winnipeg",
    "ON": "America/Toronto", "QC": "America/Toronto",
    "NB": "America/Halifax", "NS": "America/Halifax",
    "PE": "America/Halifax", "NL": "America/St_Johns",
}

AU_TIMEZONE = {
    "NSW": "Australia/Sydney", "ACT": "Australia/Sydney",
    "VIC": "Australia/Melbourne", "QLD": "Australia/Brisbane",
    "SA": "Australia/Adelaide", "WA": "Australia/Perth",
    "TAS": "Australia/Hobart", "NT": "Australia/Darwin",
}


def postal_code(country_id: int, state_code: str) -> str:
    if country_id == 233:
        low, high = US_ZIP_PREFIX.get(state_code, (100, 999))
        return f"{random.randint(low, high):03d}{random.randint(0, 99):02d}"
    if country_id == 39:
        letters = CA_POSTAL_LETTER.get(state_code, "KLMNP")
        first = random.choice(letters)
        rest = random.choice(string.ascii_uppercase)
        last = random.choice(string.ascii_uppercase)
        return (
            f"{first}{random.randint(0, 9)}{rest} "
            f"{random.randint(0, 9)}{last}{random.randint(0, 9)}"
        )
    if country_id == 14:
        low, high = AU_POSTCODE_RANGE.get(state_code, (2000, 2599))
        return f"{random.randint(low, high):04d}"
    if country_id == 82:
        prefix = DE_PLZ_PREFIX.get(state_code, "1")
        return f"{prefix}{random.randint(0, 9999):04d}"
    if country_id == 101:
        prefix = IN_PIN_PREFIX.get(state_code, "1")
        return f"{prefix}{random.randint(0, 99999):05d}"
    if country_id == 105:
        keys = IE_ROUTING_KEY.get(state_code, ["A65"])
        body = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(4))
        return f"{random.choice(keys)} {body}"
    return f"{random.randint(10000, 99999)}"


def time_zone(country_id: int, state_code: str) -> str:
    if country_id == 233:
        for zone, codes in US_TIMEZONE.items():
            if state_code in codes:
                return US_TIMEZONE_NAME[zone]
        if state_code == "AK":
            return "America/Anchorage"
        if state_code == "HI":
            return "Pacific/Honolulu"
        return US_TIMEZONE_NAME["EASTERN"]
    if country_id == 39:
        return CA_TIMEZONE.get(state_code, "America/Toronto")
    if country_id == 14:
        return AU_TIMEZONE.get(state_code, "Australia/Sydney")
    return COUNTRY_TIMEZONE.get(country_id, "UTC")


def phone_number(phone_code: str) -> str:
    """A number inside the 555-0100..555-0199 reserved-fiction block.

    That range is reserved for fictional use, so no generated number can reach
    a real subscriber. The country's real phone_code is kept as the prefix so
    the number still lines up with the user's country.
    """
    return f"+{phone_code}-555-{random.randint(100, 199):04d}"
