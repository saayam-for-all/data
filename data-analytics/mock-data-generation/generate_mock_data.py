"""Generate mock CSV data for the required tables.

This is for local dev, API testing, dashboards, and demos -- it writes plain
CSVs and never touches a database. One CSV per table (countries, states,
cities, help_categories, users, volunteer_details, user_skills,
user_locations, volunteer_locations, organizations) is written to this
script's directory.

Rows are built in dependency order, so a child table only ever references
ids that already exist in its parent table -- states come from countries,
cities from states, users get their city/state/zip/lat-long from the same
sampled city row, and so on. assert_unique_pk / assert_fk_valid then double
check that in main() after every table is built, so if a future change
breaks that ordering, the script fails with a clear error instead of
quietly writing bad data.

Row counts, volunteer fraction, random seed, and the date range used for
generated timestamps are all configurable from the command line -- run with
-h to see the options (--rows, --volunteer-fraction, --seed, --today,
--earliest-date).
"""

import argparse
import random
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import utils as u

OUTPUT_PATH = Path(__file__).resolve().parent


def _parse_date_arg(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}', expected format YYYY-MM-DD"
        )


def assert_unique_pk(df, pk_cols, table_name):
    """Fail loudly if a table's primary key column(s) contain duplicates."""
    if isinstance(pk_cols, str):
        pk_cols = [pk_cols]
    dupes = df[df.duplicated(subset=pk_cols, keep=False)]
    assert dupes.empty, (
        f"{table_name}: primary key {pk_cols} has "
        f"{df.duplicated(subset=pk_cols).sum()} duplicate value(s), "
        f"e.g. {dupes[pk_cols].iloc[0].to_dict()}"
    )


def assert_fk_valid(df, fk_col, parent_df, parent_col, table_name, nullable=False):
    """Fail loudly if a foreign key column references a value missing from its parent table."""
    values = df[fk_col].dropna() if nullable else df[fk_col]
    missing = ~values.isin(parent_df[parent_col])
    assert not missing.any(), (
        f"{table_name}.{fk_col}: {missing.sum()} value(s) not found in "
        f"parent_col={parent_col}, e.g. {values[missing].iloc[0]!r}"
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate mock data CSVs for Saayam tables."
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=u.DEFAULT_N_ROWS,
        help="Target row count for non-reference-bounded tables (default: %(default)s).",
    )
    parser.add_argument(
        "--volunteer-fraction",
        type=float,
        default=u.DEFAULT_VOLUNTEER_FRACTION,
        help="Fraction of users who are volunteers (default: %(default)s).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=u.DEFAULT_SEED,
        help="Random seed for reproducibility (default: %(default)s).",
    )
    parser.add_argument(
        "--today",
        type=_parse_date_arg,
        default=u.DEFAULT_TODAY,
        help="Reference 'today' date (YYYY-MM-DD) that generated timestamps/dates "
        "will not exceed (default: %(default)s).",
    )
    parser.add_argument(
        "--earliest-date",
        type=_parse_date_arg,
        default=u.DEFAULT_EARLIEST_DATE,
        help="Earliest date (YYYY-MM-DD) generated timestamps/dates may fall on "
        "(default: %(default)s).",
    )
    return parser.parse_args()


def generate_countries(earliest_date, today):
    rows = []
    for i, c in enumerate(u.COUNTRIES, start=1):
        rows.append(
            {
                "country_id": i,
                "country_name": c["country_name"],
                "phone_code": c["phone_code"],
                "country_code": c["country_code"],
                "last_updated_at": u.pg_timestamp(
                    u.random_datetime(earliest_date, today)
                ),
                "is_eu_member": c["is_eu_member"],
            }
        )
    return pd.DataFrame(rows)


def generate_states(countries_df, earliest_date, today):
    us_country_id = int(
        countries_df.loc[
            countries_df["country_name"] == "UNITED_STATES", "country_id"
        ].iloc[0]
    )
    rows = []
    for s in u.US_STATES:
        rows.append(
            {
                "state_id": s["state_id"],
                "country_id": us_country_id,
                "state_name": s["state_name"],
                "state_code": s["state_code"],
                "last_updated_at": u.pg_timestamp(
                    u.random_datetime(earliest_date, today)
                ),
            }
        )
    return pd.DataFrame(rows)


def generate_cities(states_df, n_rows, earliest_date, today):
    state_ids = states_df["state_id"].tolist()
    rows = []
    city_id = 1
    # Ensure every state gets at least one city, then top up randomly to n_rows.
    seeded = []
    for state_id in state_ids:
        city_name, lat, lon, zip_code = random.choice(u.US_CITIES[state_id])
        seeded.append((state_id, city_name, lat, lon, zip_code))

    pool = []
    for state_id, cities in u.US_CITIES.items():
        for city_name, lat, lon, zip_code in cities:
            pool.append((state_id, city_name, lat, lon, zip_code))

    selected = list(seeded)
    remaining_slots = max(0, n_rows - len(selected))
    extra_candidates = [c for c in pool if c not in selected]
    random.shuffle(extra_candidates)
    selected.extend(extra_candidates[:remaining_slots])

    for state_id, city_name, lat, lon, zip_code in selected[: max(n_rows, len(seeded))]:
        rows.append(
            {
                "city_id": city_id,
                "state_id": state_id,
                "city_name": city_name,
                "lattitude": lat,
                "longitude": lon,
                "last_updated_at": u.pg_timestamp(
                    u.random_datetime(earliest_date, today)
                ),
                "_zip_code": zip_code,
            }
        )
        city_id += 1
    return pd.DataFrame(rows)


def generate_help_categories(earliest_date, today):
    rows = []
    for cat_id, cat_name, cat_desc in u.HELP_CATEGORIES:
        rows.append(
            {
                "cat_id": cat_id,
                "cat_name": cat_name,
                "cat_desc": cat_desc,
                "last_updated_at": u.pg_timestamp(
                    u.random_datetime(earliest_date, today)
                ),
            }
        )
    return pd.DataFrame(rows)


def generate_users(countries_df, cities_df, n_rows, earliest_date, today):
    us_country_id = int(
        countries_df.loc[
            countries_df["country_name"] == "UNITED_STATES", "country_id"
        ].iloc[0]
    )
    other_countries = countries_df[countries_df["country_id"] != us_country_id][
        "country_id"
    ].tolist()

    rows = []
    for i in range(1, n_rows + 1):
        first, middle, last, full = u.random_name_parts()

        # 85% of users are US-based (so they have a real state/city); rest are
        # international with no state/city on file, matching the nullable FK columns.
        is_us = random.random() < 0.85
        if is_us:
            country_id = us_country_id
            city_row = cities_df.sample(1).iloc[0]
            state_id = city_row["state_id"]
            city_name = city_row["city_name"]
            lat, lon = float(city_row["lattitude"]), float(city_row["longitude"])
            zip_code = city_row["_zip_code"]
        else:
            country_id = (
                random.choice(other_countries) if other_countries else us_country_id
            )
            state_id = None
            city_name = None
            lat, lon = None, None
            zip_code = None

        _, last_updated_at = u.created_then_updated(earliest_date, today)
        dob = u.random_dob(today, 18, 60)

        rows.append(
            {
                "user_id": u.generate_sid(i),
                "state_id": state_id,
                "country_id": country_id,
                "user_status_id": random.randint(1, 5),
                "full_name": full,
                "first_name": first,
                "middle_name": middle if middle else None,
                "last_name": last,
                "primary_email_address": f"{first.lower()}.{last.lower()}{i}@example.com",
                "primary_phone_number": f"+1{random.randint(2000000000, 9999999999)}",
                "addr_ln1": f"{random.randint(100, 9999)} Main St",
                "addr_ln2": None,
                "addr_ln3": None,
                "city_name": city_name,
                "zip_code": zip_code,
                "last_location": f"({lon},{lat})" if lat is not None else None,
                "last_updated_at": u.pg_timestamp(last_updated_at),
                "time_zone": random.choice(u.TIME_ZONES) if is_us else None,
                "profile_picture_path": None,
                "gender": random.choice(u.GENDERS),
                "language_1": random.randint(1, 20),
                "language_2": random.randint(1, 20) if random.random() < 0.5 else None,
                "language_3": None,
                "promotion_wizard_stage": random.randint(0, 5),
                "promotion_wizard_last_updated_at": u.pg_timestamp(
                    u.random_datetime(last_updated_at, today)
                ),
                "external_auth_provider": random.choice(u.AUTH_PROVIDERS),
                "dob": u.pg_date(dob),
                "is_eu": bool(
                    countries_df.loc[
                        countries_df["country_id"] == country_id, "is_eu_member"
                    ].iloc[0]
                ),
                "_state_id": state_id,
                "_city_name": city_name,
                "_lat": lat,
                "_lon": lon,
            }
        )
    return pd.DataFrame(rows)


def generate_volunteer_details(
    users_df, volunteer_fraction, seed, earliest_date, today
):
    volunteer_users = users_df.sample(frac=volunteer_fraction, random_state=seed)
    rows = []
    for _, user in volunteer_users.iterrows():
        created_at, last_updated_at = u.created_then_updated(earliest_date, today)
        terms_accepted_at = u.random_datetime(created_at, last_updated_at)
        path1_updated_at = u.random_datetime(created_at, last_updated_at)
        path2_updated_at = u.random_datetime(created_at, last_updated_at)

        days = sorted(
            random.sample(
                ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                k=random.randint(1, 5),
            )
        )
        times = {
            day: [random.choice(["09:00-12:00", "13:00-17:00", "18:00-20:00"])]
            for day in days
        }

        rows.append(
            {
                "user_id": user["user_id"],
                "terms_and_conditions": True,
                "terms_accepted_at": u.pg_timestamp(terms_accepted_at),
                "govt_id_path1": f"/govt_ids/{user['user_id']}_1.jpg",
                "govt_id_path2": f"/govt_ids/{user['user_id']}_2.jpg",
                "path1_updated_at": u.pg_timestamp(path1_updated_at),
                "path2_updated_at": u.pg_timestamp(path2_updated_at),
                "availability_days": str(days),
                "availability_times": str(times),
                "created_at": u.pg_timestamp(created_at),
                "last_updated_at": u.pg_timestamp(last_updated_at),
            }
        )
    return pd.DataFrame(rows), volunteer_users


def generate_user_skills(users_df, help_categories_df, earliest_date, today):
    cat_ids = help_categories_df["cat_id"].tolist()
    rows = []
    # Skewed so most users have exactly one skill, with a shrinking tail up to 5.
    skill_counts = [1, 2, 3, 4, 5]
    skill_weights = [60, 20, 10, 6, 4]
    for _, user in users_df.iterrows():
        n_skills = random.choices(skill_counts, weights=skill_weights, k=1)[0]
        chosen_cats = random.sample(cat_ids, k=min(n_skills, len(cat_ids)))
        for cat_id in chosen_cats:
            created_at, last_updated_at = u.created_then_updated(earliest_date, today)
            rows.append(
                {
                    "user_id": user["user_id"],
                    "cat_id": cat_id,
                    "skill_level": random.choice(u.SKILL_LEVELS),
                    "created_at": u.pg_timestamp(created_at),
                    "last_updated_at": u.pg_timestamp(last_updated_at),
                }
            )
    return pd.DataFrame(rows)


def _location_row(user):
    lat, lon = user["_lat"], user["_lon"]
    if pd.isna(lat) or lat is None:
        # No known location: keep prev/curr near a default reference point (0,0 offset skipped -> None).
        return None, None
    curr_lat, curr_lon = u.jitter_point(lat, lon, max_delta=0.02)
    prev_lat, prev_lon = u.jitter_point(lat, lon, max_delta=0.05)
    return f"POINT({prev_lon} {prev_lat})", f"POINT({curr_lon} {curr_lat})"


def generate_user_locations(users_df, earliest_date, today):
    rows = []
    for _, user in users_df.iterrows():
        prev_loc, curr_loc = _location_row(user)
        rows.append(
            {
                "user_id": user["user_id"],
                "prev_loc": prev_loc,
                "curr_loc": curr_loc,
                "last_updated_at": u.pg_timestamp(
                    u.random_datetime(earliest_date, today)
                ),
            }
        )
    return pd.DataFrame(rows)


def generate_volunteer_locations(volunteer_users_df, earliest_date, today):
    rows = []
    for _, user in volunteer_users_df.iterrows():
        prev_loc, curr_loc = _location_row(user)
        rows.append(
            {
                "user_id": user["user_id"],
                "prev_loc": prev_loc,
                "curr_loc": curr_loc,
                "last_updated_at": u.pg_timestamp(
                    u.random_datetime(earliest_date, today)
                ),
            }
        )
    return pd.DataFrame(rows)


def generate_organizations(cities_df, n_rows, earliest_date, today):
    rows = []
    for i in range(1, n_rows + 1):
        city_row = cities_df.sample(1).iloc[0]
        state_id = city_row["state_id"]
        city_name = city_row["city_name"]
        zip_code = city_row["_zip_code"]
        created_at, last_updated_at = u.created_then_updated(earliest_date, today)
        org_name = u.random_org_name()
        domain = org_name.lower().replace(" ", "")

        rows.append(
            {
                "org_id": u.generate_org_id(i),
                "org_name": org_name,
                "street": f"{random.randint(100, 9999)} Main St",
                "city_name": city_name,
                "state_id": state_id,
                "zip_code": zip_code,
                "mission": f"{org_name} is dedicated to community support and outreach.",
                "web_url": f"http://www.{domain}.org",
                "phone": f"+1{random.randint(2000000000, 9999999999)}",
                "email": f"contact@{domain}.org",
                "org_type": random.choice(u.ORG_TYPES),
                "org_size": random.choice(u.ORG_SIZES),
                "org_rating": random.randint(1, 5),
                "is_collaborator": random.choice([True, False]),
                "is_contributor": random.choice([True, False]),
                "created_at": u.pg_timestamp(created_at),
                "last_updated_at": u.pg_timestamp(last_updated_at),
            }
        )
    return pd.DataFrame(rows)


def main():
    args = parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)

    if args.earliest_date > args.today:
        raise ValueError("--earliest-date must not be after --today")

    earliest_date, today = args.earliest_date, args.today

    countries_df = generate_countries(earliest_date, today)
    assert_unique_pk(countries_df, "country_id", "countries")

    states_df = generate_states(countries_df, earliest_date, today)
    assert_unique_pk(states_df, "state_id", "states")
    assert_fk_valid(states_df, "country_id", countries_df, "country_id", "states")

    cities_df = generate_cities(states_df, args.rows, earliest_date, today)
    assert_unique_pk(cities_df, "city_id", "cities")
    assert_fk_valid(cities_df, "state_id", states_df, "state_id", "cities")

    help_categories_df = generate_help_categories(earliest_date, today)
    assert_unique_pk(help_categories_df, "cat_id", "help_categories")

    users_df = generate_users(countries_df, cities_df, args.rows, earliest_date, today)
    assert_unique_pk(users_df, "user_id", "users")
    assert_fk_valid(
        users_df, "country_id", countries_df, "country_id", "users", nullable=True
    )
    assert_fk_valid(users_df, "state_id", states_df, "state_id", "users", nullable=True)

    volunteer_details_df, volunteer_users_df = generate_volunteer_details(
        users_df, args.volunteer_fraction, args.seed, earliest_date, today
    )
    assert_unique_pk(volunteer_details_df, "user_id", "volunteer_details")
    assert_fk_valid(
        volunteer_details_df, "user_id", users_df, "user_id", "volunteer_details"
    )

    user_skills_df = generate_user_skills(
        users_df, help_categories_df, earliest_date, today
    )
    assert_unique_pk(user_skills_df, ["user_id", "cat_id"], "user_skills")
    assert_fk_valid(user_skills_df, "user_id", users_df, "user_id", "user_skills")
    assert_fk_valid(
        user_skills_df, "cat_id", help_categories_df, "cat_id", "user_skills"
    )

    user_locations_df = generate_user_locations(users_df, earliest_date, today)
    assert_unique_pk(user_locations_df, "user_id", "user_locations")
    assert_fk_valid(user_locations_df, "user_id", users_df, "user_id", "user_locations")

    volunteer_locations_df = generate_volunteer_locations(
        volunteer_users_df, earliest_date, today
    )
    assert_unique_pk(volunteer_locations_df, "user_id", "volunteer_locations")
    assert_fk_valid(
        volunteer_locations_df,
        "user_id",
        volunteer_details_df,
        "user_id",
        "volunteer_locations",
    )

    organizations_df = generate_organizations(
        cities_df, args.rows, earliest_date, today
    )
    assert_unique_pk(organizations_df, "org_id", "organizations")
    assert_fk_valid(
        organizations_df,
        "state_id",
        states_df,
        "state_id",
        "organizations",
        nullable=True,
    )

    # Drop internal helper columns not present in the respective table schemas.
    users_out_df = users_df.drop(columns=["_state_id", "_city_name", "_lat", "_lon"])
    cities_out_df = cities_df.drop(columns=["_zip_code"])

    tables = {
        "countries": countries_df,
        "states": states_df,
        "cities": cities_out_df,
        "help_categories": help_categories_df,
        "users": users_out_df,
        "volunteer_details": volunteer_details_df,
        "user_skills": user_skills_df,
        "user_locations": user_locations_df,
        "volunteer_locations": volunteer_locations_df,
        "organizations": organizations_df,
    }

    for name, df in tables.items():
        out_file = OUTPUT_PATH / f"{name}.csv"
        df.to_csv(out_file, index=False)
        print(f"Wrote {len(df)} rows to {out_file.name}")

    print("Done")


if __name__ == "__main__":
    main()
