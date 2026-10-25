"""Configuration for Saayam mock-data generation (issue #301).

Every row count and ratio the generators use is declared here so larger or
smaller datasets can be produced without touching the generation logic.
"""

from pathlib import Path

# --- Paths ----------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR
REFERENCE_DIR = BASE_DIR / "reference"

# Real reference data already loaded into the Saayam database. Reused so that
# generated country/state values are guaranteed to match production lookups.
LOOKUP_DIR = BASE_DIR.parent.parent / "database" / "lookup_tables"
COUNTRY_LOOKUP = LOOKUP_DIR / "country.csv"
STATE_LOOKUP = LOOKUP_DIR / "state.csv"
HELP_CATEGORY_LOOKUP = LOOKUP_DIR / "help_categories.csv"

# --- Determinism ----------------------------------------------------------

RANDOM_SEED = 42

# --- Geographic scope -----------------------------------------------------

# Countries that users and organizations are placed in. Every one of these has
# curated real cities with coordinates in reference/cities_seed.csv, which is
# what keeps country -> state -> city -> coordinates coherent.
#
# country_id values come from database/lookup_tables/country.csv.
FOCUS_COUNTRY_IDS = [
    233,  # UNITED_STATES_OF_AMERICA
    101,  # INDIA
    39,   # CANADA
    14,   # AUSTRALIA
    82,   # GERMANY      (EU member -> exercises users.is_eu)
    105,  # IRELAND      (EU member -> exercises users.is_eu)
]

# Relative share of users/organizations placed in each focus country.
COUNTRY_WEIGHTS = {233: 0.50, 101: 0.20, 39: 0.10, 14: 0.08, 82: 0.08, 105: 0.04}

# --- Row counts -----------------------------------------------------------

# countries.csv and help_categories.csv are reference tables: they are emitted
# at their natural real-world size rather than padded to an artificial count.
# states.csv is limited to the focus countries above.
#
# Set STATE_SCOPE_ALL = True to emit every state of every country instead.
STATE_SCOPE_ALL = False

# cities.csv is capped by the curated real-city seed; asking for more than the
# seed holds emits the whole seed rather than inventing unreal geography.
CITY_ROWS = 400

USER_ROWS = 400

# Share of users who completed volunteer onboarding (drives volunteer_details).
VOLUNTEER_RATIO = 0.55

# Share of volunteers that have shared a location (drives volunteer_locations).
VOLUNTEER_LOCATION_RATIO = 0.90

# Share of users that have shared a location (drives user_locations).
USER_LOCATION_RATIO = 1.00

# Skills per user. Volunteers declare more skills than non-volunteers.
SKILLS_PER_VOLUNTEER = (2, 5)
SKILLS_PER_NON_VOLUNTEER = (0, 2)

ORGANIZATION_ROWS = 400

# --- Time window ----------------------------------------------------------

# All generated timestamps fall inside this window, and related timestamps are
# ordered created_at <= last_updated_at.
WINDOW_START = "2025-01-01 00:00:00"
WINDOW_END = "2026-09-01 00:00:00"

# --- Fixed lookup values --------------------------------------------------

# database/lookup_tables/user_status.csv currently defines exactly one status.
USER_STATUS_IDS = [1]

# database/lookup_tables/supporting_languages.csv defines language_id 1..12.
LANGUAGE_IDS = list(range(1, 13))
