"""Central configuration for the Saayam mock-data generator.

All row counts and tunables live here so the dataset can be resized without
touching generator logic. Values may also be overridden from the command line
(see ``generate_mock_data.py --help``).

Target schema: ``virginia_dev_saayam_rdbms`` as documented in the database wiki
"Changes to the Database, Waiting for Microservice" (post-pluralization).
"""

from __future__ import annotations

import reference_data as ref
from utils import ConfigError

# Deterministic output: same seed => byte-identical CSVs.
SEED = 42

# Directory (relative to this file) where CSVs are written.
OUTPUT_DIR = "output_csv_files"

# ---------------------------------------------------------------------------
# Row-count knobs
# ---------------------------------------------------------------------------
# Reference/geo tables are sized from curated real-world data in
# ``reference_data.py`` and are intentionally not padded to 400 rows, because
# padding them would break geographic consistency. The transactional tables
# below default to ~400 rows as required by the issue acceptance criteria.

USERS = 400
ORGANIZATIONS = 400
CITIES_PER_STATE = 4

VOLUNTEER_RATIO = 0.45          # fraction of users that are volunteers
USER_LOCATION_RATIO = 0.70      # fraction of users with a location row

SKILLS_PER_USER_MIN = 1
SKILLS_PER_USER_MAX = 5

# ---------------------------------------------------------------------------
# External lookup ids -- default to the VERIFIED sets from the committed repo
# lookup CSVs (supporting_languages 1..12, user_status only 1=ACTIVE). Override
# only after the corresponding lookup rows are actually seeded. An empty list
# means "emit NULL for that column".
# ---------------------------------------------------------------------------
USER_STATUS_IDS = list(ref.VERIFIED_USER_STATUS_IDS)
LANGUAGE_IDS = list(ref.VERIFIED_LANGUAGE_IDS)


def validate(users: int, orgs: int, cities_per_state: int,
             volunteer_ratio: float, user_location_ratio: float,
             skills_min: int, skills_max: int) -> None:
    """Reject invalid configuration/CLI inputs with a clear ConfigError.

    Zero-row datasets are allowed (users=0 / orgs=0) where relationships still
    hold; negative counts and out-of-range ratios are not.
    """
    for name, value in (("users", users), ("orgs", orgs),
                        ("cities_per_state", cities_per_state),
                        ("skills_min", skills_min), ("skills_max", skills_max)):
        if type(value) is not int:
            raise ConfigError(f"{name} must be an integer")
    for name, value in (("volunteer_ratio", volunteer_ratio),
                        ("user_location_ratio", user_location_ratio)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{name} must be a number in [0,1]")
    for name, values, bits in (("LANGUAGE_IDS", LANGUAGE_IDS, 64),
                               ("USER_STATUS_IDS", USER_STATUS_IDS, 32)):
        if any(type(v) is not int or not 0 < v < 2 ** (bits - 1) for v in values):
            raise ConfigError(f"{name} must contain positive signed {bits}-bit integers")
        if len(values) != len(set(values)):
            raise ConfigError(f"{name} must not contain duplicate ids")
    if users < 0:
        raise ConfigError(f"--users must be >= 0 (got {users})")
    if orgs < 0:
        raise ConfigError(f"--orgs must be >= 0 (got {orgs})")
    if cities_per_state < 0:
        raise ConfigError(f"CITIES_PER_STATE must be >= 0 (got {cities_per_state})")
    if not (0.0 <= volunteer_ratio <= 1.0):
        raise ConfigError(f"VOLUNTEER_RATIO must be in [0,1] (got {volunteer_ratio})")
    if not (0.0 <= user_location_ratio <= 1.0):
        raise ConfigError(f"USER_LOCATION_RATIO must be in [0,1] (got {user_location_ratio})")
    if skills_min < 0:
        raise ConfigError(f"SKILLS_PER_USER_MIN must be >= 0 (got {skills_min})")
    if skills_max < skills_min:
        raise ConfigError(
            f"SKILLS_PER_USER_MAX ({skills_max}) must be >= SKILLS_PER_USER_MIN ({skills_min})")
    if skills_max > len(ref.HELP_CATEGORIES):
        raise ConfigError("SKILLS_PER_USER_MAX cannot exceed the available help categories")
