"""Table and column names used by the distance feature (issue #433).

Every name the distance code relies on lives here so it can be corrected in
one place. Sources used to pick them (none is a confirmed production DDL):

- database/mock-data-generation/db_info.json (schema dump)
- data-analytics/sql/*.csv (mock exports with plural table names)

Names marked ASSUMED differ between those sources or could not be verified;
check them against the real virginia_dev_saayam_rdbms schema.
"""

import os

DB_SCHEMA = os.environ.get("DB_SCHEMA", "virginia_dev_saayam_rdbms")

# --- requests --------------------------------------------------------------
REQUESTS_TABLE = "requests"                 # ASSUMED (db_info.json says "request")
REQUEST_ID_COLUMN = "req_id"
REQUEST_LOCATION_COLUMN = "req_loc"         # "longitude:<lon>,latitude:<lat>"
REQUEST_BENEFICIARY_COLUMN = "beneficiary_id"  # ASSUMED (only in requests.csv)

# --- user_locations --------------------------------------------------------
USER_LOCATIONS_TABLE = "user_locations"
USER_LOCATIONS_USER_ID_COLUMN = "user_id"
USER_LOCATIONS_CURRENT_COLUMN = "curr_loc"  # PostGIS geography(Point, 4326)

# --- users (beneficiary profile address) -----------------------------------
USERS_TABLE = "users"
USERS_ID_COLUMN = "user_id"
USERS_STREET_COLUMNS = ("addr_ln1",)        # addr_ln2/addr_ln3 left out on purpose
USERS_CITY_COLUMN = "city_name"             # users stores the city name directly
USERS_STATE_ID_COLUMN = "state_id"
USERS_ZIP_COLUMN = "zip_code"
USERS_COUNTRY_ID_COLUMN = "country_id"

# --- states / countries lookups --------------------------------------------
STATES_TABLE = "states"                     # ASSUMED (db_info.json says "state")
STATES_ID_COLUMN = "state_id"
STATES_NAME_COLUMN = "state_name"

COUNTRIES_TABLE = "countries"               # ASSUMED (db_info.json says "country")
COUNTRIES_ID_COLUMN = "country_id"
COUNTRIES_NAME_COLUMN = "country_name"

# --- organizations (DB orgs, read from the existing SELECT * result) -------
# Address parts in order. A tuple means "first of these columns that exists".
ORG_STREET_COLUMN = "street"
ORG_CITY_COLUMN = "city_name"
ORG_STATE_COLUMNS = ("state_id", "state_code")  # ASSUMED: csv vs db_info.json
ORG_ZIP_COLUMN = "zip_code"
ORG_COUNTRY_COLUMNS = ("country_name", "country")  # ASSUMED: neither source has one
# No online-only flag exists in either source. Add the column name here once
# one exists; a truthy value then yields distance_status="online".
ORG_ONLINE_FLAG_COLUMNS: tuple[str, ...] = ()

# --- GenAI orgs (fields of the GenAI Lambda response) ----------------------
GENAI_ADDRESS_COLUMNS = ("address", "location")  # first non-empty one wins
GENAI_ONLINE_FLAG_COLUMNS: tuple[str, ...] = ()
