"""Generate mock-data CSVs for the ten Virginia tables in issue #301.

Tables are generated in foreign-key order so that every reference resolves:

    countries -> states -> cities
    help_categories
    users -> volunteer_details -> volunteer_locations
          -> user_locations
          -> user_skills (also -> help_categories)
    states -> organizations

Run:  python generate_mock_data.py
Row counts and geographic scope are configured in config.py.
"""

import sys

import config
import reference_data
from generators import organizations as organizations_gen
from generators import reference_tables
from generators import users as users_gen
from generators import volunteers as volunteers_gen
from utils import parse_window, set_seed, write_csv


def main() -> int:
    set_seed(config.RANDOM_SEED)
    window = parse_window(config.WINDOW_START, config.WINDOW_END)
    reference = reference_data.load()

    outputs = []

    # --- Reference tables (no dependencies) -------------------------------
    outputs.append(
        (
            "countries.csv",
            reference_tables.COUNTRY_FIELDS,
            reference_tables.generate_countries(reference, window),
        )
    )
    outputs.append(
        (
            "states.csv",
            reference_tables.STATE_FIELDS,
            reference_tables.generate_states(reference, window),
        )
    )
    outputs.append(
        (
            "cities.csv",
            reference_tables.CITY_FIELDS,
            reference_tables.generate_cities(reference, window),
        )
    )
    outputs.append(
        (
            "help_categories.csv",
            reference_tables.HELP_CATEGORY_FIELDS,
            reference_tables.generate_help_categories(reference, window),
        )
    )

    # --- users and everything hanging off it ------------------------------
    user_rows, profiles = users_gen.generate_users(
        reference, window, config.USER_ROWS
    )
    outputs.append(("users.csv", users_gen.USER_FIELDS, user_rows))

    volunteers = volunteers_gen.select_volunteers(profiles, config.VOLUNTEER_RATIO)
    volunteer_ids = {profile.user_id for profile in volunteers}
    outputs.append(
        (
            "volunteer_details.csv",
            volunteers_gen.VOLUNTEER_DETAIL_FIELDS,
            volunteers_gen.generate_volunteer_details(volunteers, window),
        )
    )

    outputs.append(
        (
            "user_skills.csv",
            volunteers_gen.USER_SKILL_FIELDS,
            volunteers_gen.generate_user_skills(
                profiles, volunteer_ids, reference.help_categories, window
            ),
        )
    )

    outputs.append(
        (
            "user_locations.csv",
            volunteers_gen.LOCATION_FIELDS,
            volunteers_gen.generate_locations(
                profiles, window, config.USER_LOCATION_RATIO
            ),
        )
    )

    # Drawn from `volunteers`, never from all users: the FK points at
    # volunteer_details, so a row here needs a volunteer_details row first.
    outputs.append(
        (
            "volunteer_locations.csv",
            volunteers_gen.LOCATION_FIELDS,
            volunteers_gen.generate_locations(
                volunteers, window, config.VOLUNTEER_LOCATION_RATIO
            ),
        )
    )

    # --- organizations ----------------------------------------------------
    outputs.append(
        (
            "organizations.csv",
            organizations_gen.ORGANIZATION_FIELDS,
            organizations_gen.generate_organizations(
                reference, window, config.ORGANIZATION_ROWS
            ),
        )
    )

    for filename, fields, rows in outputs:
        written = write_csv(config.OUTPUT_DIR / filename, fields, rows)
        print(f"{filename:<26} {written:>5} rows")

    return 0


if __name__ == "__main__":
    sys.exit(main())
