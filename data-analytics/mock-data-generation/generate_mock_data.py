#!/usr/bin/env python3
"""Generate synthetic mock data for the Virginia analytics tables (issue #301).

Writes one CSV per table, in the column order of the current Virginia schema,
with valid primary keys, valid foreign keys and geographically consistent
country / state / city / ZIP / coordinate values.

    python generate_mock_data.py                  # 400 rows, seed 301
    python generate_mock_data.py --rows 100       # smaller dataset
    python generate_mock_data.py --rows 5000      # larger dataset
    python generate_mock_data.py --validate-only  # re-check existing CSVs

Standard library only - no third-party dependencies.
"""

import argparse
import os
import random
import sys
from datetime import datetime, timedelta

import utils as u

# Column order per table, taken from the current Virginia schema. This is the
# single source of truth used for both writing and validating the CSVs.
SCHEMA = {
    "countries": ["country_id", "country_name", "phone_code", "country_code",
                  "last_updated_at", "is_eu_member"],
    "states": ["state_id", "country_id", "state_name", "state_code",
               "last_updated_at"],
    # "lattitude" is spelled that way in the cities DDL; kept verbatim.
    "cities": ["city_id", "state_id", "city_name", "lattitude", "longitude",
               "last_updated_at"],
    "help_categories": ["cat_id", "cat_name", "cat_desc", "last_updated_at"],
    "users": ["user_id", "state_id", "country_id", "user_status_id",
              "full_name", "first_name", "middle_name", "last_name",
              "primary_email_address", "primary_phone_number", "addr_ln1",
              "addr_ln2", "addr_ln3", "city_name", "zip_code", "last_location",
              "last_updated_at", "time_zone", "profile_picture_path", "gender",
              "language_1", "language_2", "language_3",
              "promotion_wizard_stage", "promotion_wizard_last_updated_at",
              "external_auth_provider", "dob", "is_eu"],
    "volunteer_details": ["user_id", "terms_and_conditions",
                          "terms_accepted_at", "govt_id_path1",
                          "govt_id_path2", "path1_updated_at",
                          "path2_updated_at", "availability_days",
                          "availability_times", "created_at",
                          "last_updated_at"],
    "user_skills": ["user_id", "cat_id", "skill_level", "created_at",
                    "last_updated_at"],
    "user_locations": ["user_id", "prev_loc", "curr_loc", "last_updated_at"],
    "volunteer_locations": ["user_id", "prev_loc", "curr_loc",
                            "last_updated_at"],
    "organizations": ["org_id", "org_name", "street", "city_name", "state_id",
                      "zip_code", "mission", "web_url", "phone", "email",
                      "org_type", "org_size", "org_rating", "is_collaborator",
                      "is_contributor", "created_at", "last_updated_at"],
}

TABLES = list(SCHEMA)

# Every row lands somewhere in this window, so created_at <= last_updated_at
# always holds and no timestamp sits in the future.
WINDOW_START = datetime(2024, 1, 1)
WINDOW_END = datetime(2026, 9, 1)

# user_status_id is a FK into user_status, which is out of scope for this
# issue. 1 ("active") is the only value present in the existing Virginia data,
# so every mock user uses it rather than inventing ids that may not exist.
USER_STATUS_ID = 1

# Share of users that are also volunteers.
VOLUNTEER_RATIO = 0.6


# ---------------------------------------------------------------------------
# Generators - one per table, each returning a list of rows
# ---------------------------------------------------------------------------

def gen_countries(rng):
    rows = []
    for country_id, name, phone_code, code, is_eu in u.COUNTRIES:
        updated = u.random_datetime(rng, WINDOW_START, WINDOW_END)
        rows.append([country_id, name, phone_code, code, u.ts(updated), is_eu])
    return rows


def gen_states(rng):
    rows = []
    for state_id, name, _lat, _lon, _zip3, _tz in u.US_STATES:
        updated = u.random_datetime(rng, WINDOW_START, WINDOW_END)
        rows.append([state_id, u.US_COUNTRY_ID, name, "US-" + state_id,
                     u.ts(updated)])
    return rows


def gen_cities(rng, n_rows):
    """Spread n_rows cities across the states, near each state's centroid."""
    rows = []
    used = set()
    city_id = 1
    for i in range(n_rows):
        state_id, _name, lat, lon, _zip3, _tz = u.US_STATES[i % len(u.US_STATES)]
        # Retry until this state gets a city name it does not already have.
        for _ in range(100):
            city_name = rng.choice(u.CITY_PREFIXES) + rng.choice(u.CITY_SUFFIXES)
            if (state_id, city_name) not in used:
                break
        else:
            continue
        used.add((state_id, city_name))
        c_lat, c_lon = u.jitter_point(rng, lat, lon)
        updated = u.random_datetime(rng, WINDOW_START, WINDOW_END)
        rows.append([city_id, state_id, city_name, c_lat, c_lon, u.ts(updated)])
        city_id += 1
    return rows


def gen_help_categories(rng):
    rows = []
    for cat_id, cat_name in u.HELP_CATEGORIES:
        updated = u.random_datetime(rng, WINDOW_START, WINDOW_END)
        rows.append([cat_id, cat_name, cat_name + "_DESC", u.ts(updated)])
    return rows


def gen_users(rng, n_rows, cities):
    """One user per row, each anchored to a real city in a real state."""
    rows = []
    profiles = []
    by_state = {}
    for c in cities:
        by_state.setdefault(c["state_id"], []).append(c)
    state_meta = {s[0]: s for s in u.US_STATES}

    for seq in range(1, n_rows + 1):
        user_id = u.make_user_id(seq)
        state_id = rng.choice(sorted(by_state))
        city = rng.choice(by_state[state_id])
        _sid, _sname, _lat, _lon, zip3, tz = state_meta[state_id]

        first = rng.choice(u.FIRST_NAMES)
        last = rng.choice(u.LAST_NAMES)
        middle = rng.choice(u.MIDDLE_NAMES) if rng.random() < 0.3 else ""
        full_name = " ".join(p for p in (first, middle, last) if p)
        # example.com is reserved by RFC 2606 and can never route real mail.
        email = "{}.{}{}@example.com".format(first.lower(), last.lower(), seq)

        addr1 = "{} {} {}".format(rng.randrange(100, 9999),
                                  rng.choice(u.STREET_NAMES),
                                  rng.choice(u.STREET_TYPES))
        addr2 = "{} {}".format(rng.choice(u.UNIT_TYPES),
                               rng.randrange(1, 400)) if rng.random() < 0.35 else ""
        zip_code = "{}{:02d}".format(zip3, rng.randrange(100))
        lat, lon = u.jitter_point(rng, float(city["lattitude"]),
                                  float(city["longitude"]), 0.05)

        updated = u.random_datetime(rng, WINDOW_START, WINDOW_END)
        wizard_stage = rng.randrange(1, 6)
        # The wizard timestamp is a later touch on the same profile.
        wizard_updated = u.random_datetime(rng, updated, WINDOW_END)
        dob = (datetime(2008, 12, 31)
               - timedelta(days=rng.randrange(0, 60 * 365))).strftime("%Y-%m-%d")

        rows.append([
            user_id, state_id, u.US_COUNTRY_ID, USER_STATUS_ID,
            full_name, first, middle, last, email, u.fictional_phone(rng),
            addr1, addr2, "", city["city_name"], zip_code,
            u.pg_point(lat, lon), u.ts(updated), tz,
            "profiles/{}/avatar.png".format(user_id), rng.choice(u.GENDERS),
            # language_1..3 are FKs into supporting_languages, which is out of
            # scope here; left NULL so no orphan language ids are created.
            "", "", "",
            wizard_stage, u.ts(wizard_updated),
            rng.choice(u.AUTH_PROVIDERS), dob, False,
        ])
        profiles.append({"user_id": user_id, "lat": lat, "lon": lon,
                         "updated": updated})
    return rows, profiles


def gen_volunteer_details(rng, profiles):
    """A subset of users become volunteers; returns rows and that subset."""
    n = int(len(profiles) * VOLUNTEER_RATIO)
    volunteers = rng.sample(profiles, n)
    volunteers.sort(key=lambda p: p["user_id"])
    rows = []
    for p in volunteers:
        created = u.random_datetime(rng, WINDOW_START, WINDOW_END)
        updated = u.random_datetime(rng, created, WINDOW_END)
        accepted = u.random_datetime(rng, created, updated)
        days = rng.sample(u.WEEKDAYS, rng.randrange(1, 5))
        times = rng.sample(u.TIME_SLOTS, rng.randrange(1, 4))
        uid = p["user_id"]
        rows.append([
            uid, True, u.ts(accepted),
            "govt-ids/{}/front.pdf".format(uid),
            "govt-ids/{}/back.pdf".format(uid) if rng.random() < 0.7 else "",
            u.ts(accepted), u.ts(accepted),
            u.json_field(days), u.json_field(times),
            u.ts(created), u.ts(updated),
        ])
    return rows, volunteers


def gen_user_skills(rng, profiles, categories):
    """1-4 distinct skills per user; (user_id, cat_id) is the primary key."""
    cat_ids = [c[0] for c in categories]
    rows = []
    for p in profiles:
        for cat_id in rng.sample(cat_ids, rng.randrange(1, 5)):
            created = u.random_datetime(rng, WINDOW_START, WINDOW_END)
            updated = u.random_datetime(rng, created, WINDOW_END)
            rows.append([p["user_id"], cat_id, rng.choice(u.SKILL_LEVELS),
                         u.ts(created), u.ts(updated)])
    return rows


def gen_locations(rng, profiles):
    """curr_loc/prev_loc near the user's own city, so the geography lines up."""
    rows = []
    for p in profiles:
        curr = u.jitter_point(rng, p["lat"], p["lon"], 0.03)
        prev = u.jitter_point(rng, p["lat"], p["lon"], 0.08)
        updated = u.random_datetime(rng, p["updated"], WINDOW_END)
        rows.append([p["user_id"], u.wkt_point(*prev), u.wkt_point(*curr),
                     u.ts(updated)])
    return rows


def gen_organizations(rng, n_rows, cities):
    rows = []
    state_meta = {s[0]: s for s in u.US_STATES}
    used_names = set()
    for seq in range(1, n_rows + 1):
        city = rng.choice(cities)
        state_id = city["state_id"]
        zip3 = state_meta[state_id][4]

        for _ in range(100):
            name = "{} {}".format(rng.choice(u.ORG_PREFIXES),
                                  rng.choice(u.ORG_SUFFIXES))
            if name not in used_names:
                break
        used_names.add(name)
        slug = name.lower().replace(" ", "-")

        created = u.random_datetime(rng, WINDOW_START, WINDOW_END)
        updated = u.random_datetime(rng, created, WINDOW_END)
        rows.append([
            u.make_org_id(seq), name,
            "{} {} {}".format(rng.randrange(100, 9999),
                              rng.choice(u.STREET_NAMES),
                              rng.choice(u.STREET_TYPES)),
            city["city_name"], state_id,
            "{}{:02d}".format(zip3, rng.randrange(100)),
            rng.choice(u.ORG_MISSIONS),
            "https://www.{}.example.org".format(slug),
            u.fictional_phone(rng),
            "contact{}@{}.example.org".format(seq, slug),
            rng.choice(u.ORG_TYPES), rng.choice(u.ORG_SIZES),
            rng.randrange(1, 6),
            rng.random() < 0.5, rng.random() < 0.4,
            u.ts(created), u.ts(updated),
        ])
    return rows


# ---------------------------------------------------------------------------
# Generation + validation
# ---------------------------------------------------------------------------

def generate(out_dir, n_rows, seed):
    rng = random.Random(seed)
    os.makedirs(out_dir, exist_ok=True)

    tables = {}
    tables["countries"] = gen_countries(rng)
    tables["states"] = gen_states(rng)
    tables["cities"] = gen_cities(rng, n_rows)
    tables["help_categories"] = gen_help_categories(rng)

    # Cities are needed as dicts to anchor users and organizations.
    city_dicts = [dict(zip(SCHEMA["cities"], row)) for row in tables["cities"]]

    tables["users"], profiles = gen_users(rng, n_rows, city_dicts)
    tables["volunteer_details"], volunteers = gen_volunteer_details(rng, profiles)
    tables["user_skills"] = gen_user_skills(rng, profiles, u.HELP_CATEGORIES)
    tables["user_locations"] = gen_locations(rng, profiles)
    tables["volunteer_locations"] = gen_locations(rng, volunteers)
    tables["organizations"] = gen_organizations(rng, n_rows, city_dicts)

    for table in TABLES:
        u.write_csv(out_dir, table, SCHEMA[table], tables[table])
    return tables


def validate(out_dir):
    """Re-read the written CSVs and check every acceptance criterion.

    Returns a list of failure messages; empty means the dataset is clean.
    """
    data = {t: u.read_csv(out_dir, t) for t in TABLES}
    errors = []

    def check(condition, message):
        if not condition:
            errors.append(message)

    # Headers match the schema, in order.
    for table in TABLES:
        header = list(data[table][0].keys()) if data[table] else []
        check(header == SCHEMA[table],
              "{}: header {} does not match schema {}".format(
                  table, header, SCHEMA[table]))

    # Primary keys are unique.
    single_pk = {"countries": "country_id", "states": "state_id",
                 "cities": "city_id", "help_categories": "cat_id",
                 "users": "user_id", "volunteer_details": "user_id",
                 "user_locations": "user_id", "volunteer_locations": "user_id",
                 "organizations": "org_id"}
    for table, pk in single_pk.items():
        keys = [r[pk] for r in data[table]]
        check(len(keys) == len(set(keys)),
              "{}: duplicate {} values".format(table, pk))
        check(all(k != "" for k in keys),
              "{}: empty {} values".format(table, pk))
    composite = [(r["user_id"], r["cat_id"]) for r in data["user_skills"]]
    check(len(composite) == len(set(composite)),
          "user_skills: duplicate (user_id, cat_id) pairs")

    # Foreign keys resolve - no orphans.
    country_ids = {r["country_id"] for r in data["countries"]}
    state_ids = {r["state_id"] for r in data["states"]}
    user_ids = {r["user_id"] for r in data["users"]}
    volunteer_ids = {r["user_id"] for r in data["volunteer_details"]}
    cat_ids = {r["cat_id"] for r in data["help_categories"]}

    fks = [
        ("states", "country_id", country_ids, False),
        ("cities", "state_id", state_ids, False),
        ("users", "country_id", country_ids, True),
        ("users", "state_id", state_ids, True),
        ("volunteer_details", "user_id", user_ids, False),
        ("user_skills", "user_id", user_ids, False),
        ("user_skills", "cat_id", cat_ids, False),
        ("user_locations", "user_id", user_ids, False),
        ("volunteer_locations", "user_id", volunteer_ids, False),
        ("organizations", "state_id", state_ids, True),
    ]
    for table, column, valid, nullable in fks:
        orphans = {r[column] for r in data[table]
                   if r[column] not in valid and not (nullable and r[column] == "")}
        check(not orphans,
              "{}.{}: orphan values {}".format(table, column,
                                               sorted(orphans)[:5]))

    # states.country_id is NOT NULL in the schema.
    check(all(r["country_id"] != "" for r in data["states"]),
          "states: country_id must be NOT NULL")

    # Geography: a user's city must exist in the user's state, and the ZIP
    # must carry that state's prefix.
    state_meta = {s[0]: s for s in u.US_STATES}
    city_index = {(r["state_id"], r["city_name"]) for r in data["cities"]}
    city_coords = {(r["state_id"], r["city_name"]):
                   (float(r["lattitude"]), float(r["longitude"]))
                   for r in data["cities"]}
    for table in ("users", "organizations"):
        for r in data[table]:
            if not r["state_id"] or not r["city_name"]:
                continue
            check((r["state_id"], r["city_name"]) in city_index,
                  "{}: city {} is not in state {}".format(
                      table, r["city_name"], r["state_id"]))
            check(r["zip_code"].startswith(state_meta[r["state_id"]][4]),
                  "{}: zip {} does not belong to state {}".format(
                      table, r["zip_code"], r["state_id"]))

    # cities sit near their own state's centroid.
    for r in data["cities"]:
        lat, lon = float(r["lattitude"]), float(r["longitude"])
        s_lat, s_lon = state_meta[r["state_id"]][2], state_meta[r["state_id"]][3]
        check(abs(lat - s_lat) <= 1.0 and abs(lon - s_lon) <= 1.0,
              "cities: {} is not near state {}".format(r["city_name"],
                                                       r["state_id"]))

    # Location points sit near the user's own city.
    user_city = {r["user_id"]: (r["state_id"], r["city_name"])
                 for r in data["users"]}
    for table in ("user_locations", "volunteer_locations"):
        for r in data[table]:
            # A user whose city/state pair is already broken is reported above;
            # skip it here rather than crashing on the lookup.
            coords = city_coords.get(user_city.get(r["user_id"]))
            if coords is None:
                continue
            c_lat, c_lon = coords
            for column in ("curr_loc", "prev_loc"):
                lon, lat = _parse_wkt(r[column])
                check(abs(lat - c_lat) <= 0.5 and abs(lon - c_lon) <= 0.5,
                      "{}: {} for {} is far from their city".format(
                          table, column, r["user_id"]))

    # Timestamps parse and stay ordered.
    pairs = [("volunteer_details", "created_at", "last_updated_at"),
             ("user_skills", "created_at", "last_updated_at"),
             ("organizations", "created_at", "last_updated_at"),
             ("users", "last_updated_at", "promotion_wizard_last_updated_at")]
    for table, earlier, later in pairs:
        for r in data[table]:
            a = datetime.strptime(r[earlier], "%Y-%m-%d %H:%M:%S")
            b = datetime.strptime(r[later], "%Y-%m-%d %H:%M:%S")
            check(a <= b, "{}: {} > {} on row {}".format(
                table, earlier, later, r))

    for r in data["users"]:
        datetime.strptime(r["dob"], "%Y-%m-%d")

    # Enumerated columns only carry values the DB types allow.
    check(all(r["skill_level"] in u.SKILL_LEVELS for r in data["user_skills"]),
          "user_skills: skill_level outside the skill_levels enum")
    check(all(r["org_type"] in u.ORG_TYPES for r in data["organizations"]),
          "organizations: org_type outside the org_type_enum")
    check(all(r["org_size"] in u.ORG_SIZES for r in data["organizations"]),
          "organizations: org_size outside the org_size_enum")
    check(all(1 <= int(r["org_rating"]) <= 5 for r in data["organizations"]),
          "organizations: org_rating outside 1..5")
    # CHECK constraints on the organizations table.
    check(all(r["web_url"].startswith("http") for r in data["organizations"]),
          "organizations: web_url must start with http")
    check(all("@" in r["email"] for r in data["organizations"]),
          "organizations: email must contain @")

    # Nothing that could be mistaken for a real contact detail.
    for r in data["users"]:
        check(r["primary_email_address"].endswith("@example.com"),
              "users: email is not in the reserved example.com domain")
        check("555-01" in r["primary_phone_number"],
              "users: phone is outside the fictional 555-01xx range")

    return errors


def _parse_wkt(value):
    """SRID=4326;POINT(lon lat) -> (lon, lat)."""
    inner = value.split("(", 1)[1].rstrip(")")
    lon, lat = inner.split()
    return float(lon), float(lat)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=400,
                        help="rows for the user-scale tables (default: 400). "
                             "Reference tables keep their natural size.")
    parser.add_argument("--seed", type=int, default=301,
                        help="RNG seed, for reproducible output (default: 301)")
    parser.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)),
                        help="output directory (default: this directory)")
    parser.add_argument("--validate-only", action="store_true",
                        help="validate the CSVs already in --out, generate nothing")
    args = parser.parse_args(argv)

    if not args.validate_only:
        tables = generate(args.out, args.rows, args.seed)
        for table in TABLES:
            print("{:<22} {:>6} rows".format(table + ".csv", len(tables[table])))

    errors = validate(args.out)
    if errors:
        print("\nVALIDATION FAILED:", file=sys.stderr)
        for message in errors:
            print("  - " + message, file=sys.stderr)
        return 1
    print("\nValidation passed: primary keys unique, no orphan foreign keys, "
          "geography and timestamps consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
