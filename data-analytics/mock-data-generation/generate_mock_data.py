"""
Main entry point: generates synthetic, schema-compliant CSV mock data for
the 10 Virginia analytics tables listed in issue #301
(countries, states, cities, help_categories, users, volunteer_details,
user_skills, volunteer_locations, user_locations, organizations).

Usage:
    python generate_mock_data.py
    python generate_mock_data.py --num-users 400 --num-orgs 150 --seed 7

Run `python validate_mock_data.py` afterwards to check the output.
"""

import argparse
import os

from cities import cities_by_state, generate_cities
from countries import country_lookup, generate_countries
from help_categories import generate_help_categories
from organizations import generate_organizations
from states import generate_states, state_lookup
from user_locations import generate_user_locations
from user_skills import generate_user_skills
from users import generate_users
from utils import set_seed, write_csv
from volunteer_details import generate_volunteer_details
from volunteer_locations import generate_volunteer_locations

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate mock data CSVs for the Virginia analytics tables.")
    parser.add_argument("--num-users", type=int, default=100, help="Number of users.csv rows (default: 100).")
    parser.add_argument("--num-orgs", type=int, default=100, help="Number of organizations.csv rows (default: 100).")
    parser.add_argument("--volunteer-ratio", type=float, default=0.6,
                         help="Fraction of users who also get a volunteer_details row (default: 0.6).")
    parser.add_argument("--user-location-ratio", type=float, default=0.85,
                         help="Fraction of users who also get a user_locations row (default: 0.85).")
    parser.add_argument("--seed", type=int, default=42, help="Random seed, for reproducible output (default: 42).")
    parser.add_argument("--output-dir", type=str, default=SCRIPT_DIR,
                         help="Directory to write the CSV files into (default: this script's directory).")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    set_seed(args.seed)
    os.makedirs(args.output_dir, exist_ok=True)

    def out(name: str) -> str:
        return os.path.join(args.output_dir, name)

    # --- Reference / lookup tables (dependency order matters) -------------
    country_rows = generate_countries()
    countries_by_code = country_lookup(country_rows)
    countries_by_id = {row["country_id"]: row for row in country_rows}

    state_rows = generate_states(countries_by_code)
    states_by_id = state_lookup(state_rows)

    city_rows = generate_cities(states_by_id)
    cities_grouped = cities_by_state(city_rows)

    category_rows = generate_help_categories()

    # --- Core entity tables --------------------------------------------
    user_rows, user_contexts = generate_users(
        count=args.num_users,
        state_rows=state_rows,
        cities_by_state=cities_grouped,
        country_by_id=countries_by_id,
    )

    volunteer_rows, volunteer_contexts = generate_volunteer_details(
        user_contexts, volunteer_ratio=args.volunteer_ratio,
    )

    skill_rows = generate_user_skills(volunteer_contexts)
    volunteer_location_rows = generate_volunteer_locations(volunteer_contexts)
    user_location_rows = generate_user_locations(user_contexts, coverage_ratio=args.user_location_ratio)

    org_rows = generate_organizations(
        count=args.num_orgs, state_rows=state_rows, cities_by_state=cities_grouped,
        country_by_id=countries_by_id,
    )

    # --- Write CSVs -------------------------------------------------------
    write_csv(out("countries.csv"), country_rows)
    write_csv(out("states.csv"), state_rows)
    write_csv(out("cities.csv"), city_rows)
    write_csv(out("help_categories.csv"), category_rows)
    write_csv(out("users.csv"), user_rows)
    write_csv(out("volunteer_details.csv"), volunteer_rows)
    write_csv(out("user_skills.csv"), skill_rows)
    write_csv(out("volunteer_locations.csv"), volunteer_location_rows)
    write_csv(out("user_locations.csv"), user_location_rows)
    write_csv(out("organizations.csv"), org_rows)

    counts = {
        "countries.csv": len(country_rows),
        "states.csv": len(state_rows),
        "cities.csv": len(city_rows),
        "help_categories.csv": len(category_rows),
        "users.csv": len(user_rows),
        "volunteer_details.csv": len(volunteer_rows),
        "user_skills.csv": len(skill_rows),
        "volunteer_locations.csv": len(volunteer_location_rows),
        "user_locations.csv": len(user_location_rows),
        "organizations.csv": len(org_rows),
    }
    total = sum(counts.values())
    for name, count in counts.items():
        print(f"  {name:<26} {count:>5} rows")
    print(f"Total: {total} rows across {len(counts)} files (output: {args.output_dir})")


if __name__ == "__main__":
    main()
