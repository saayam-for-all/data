"""Entry point: generate mock CSVs for the ten in-scope Saayam tables.

Usage
-----
    python generate_mock_data.py                       # defaults from config.py
    python generate_mock_data.py --users 1000 --orgs 500
    python generate_mock_data.py --seed 7 --out ./csv  # reproducible, custom dir
    python generate_mock_data.py --no-validate         # skip validation

Validation runs in-memory before anything is written and raises an explicit
ValidationError (never a bare ``assert`` -- asserts can be optimized away with
``python -O``) on any schema, type, range, timestamp-ordering, geographic or
referential-integrity problem. Invalid CLI/config inputs raise ConfigError.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from decimal import Decimal

import config
import generators as gen
import reference_data as ref
from utils import ConfigError, ValidationError, set_seed, write_csv


# ===========================================================================
# Build
# ===========================================================================
def build_dataset(users_count: int, orgs_count: int):
    """Build every table's (fieldnames, rows) in dependency order, plus the
    ``aux`` verified-reference maps used by validation."""
    config.validate(users_count, orgs_count, config.CITIES_PER_STATE,
                    config.VOLUNTEER_RATIO, config.USER_LOCATION_RATIO,
                    config.SKILLS_PER_USER_MIN, config.SKILLS_PER_USER_MAX)
    (countries, states, cities, locations, aux) = gen.build_geo()
    help_cats, cat_ids = gen.build_help_categories()
    users, user_objs = gen.build_users(locations, users_count)
    user_skills = gen.build_user_skills(user_objs, cat_ids)
    user_locations = gen.build_user_locations(user_objs)
    volunteers = gen.select_volunteers(user_objs)
    volunteer_details, details_ts = gen.build_volunteer_details(volunteers)
    volunteer_locations = gen.build_volunteer_locations(volunteers, details_ts)
    organizations = gen.build_organizations(locations, orgs_count)

    dataset = {
        "countries": countries,
        "states": states,
        "cities": cities,
        "help_categories": help_cats,
        "users": users,
        "user_skills": user_skills,
        "user_locations": user_locations,
        "volunteer_details": volunteer_details,
        "volunteer_locations": volunteer_locations,
        "organizations": organizations,
    }
    return dataset, aux


# ===========================================================================
# Validation primitives
# ===========================================================================
def _fail(msg: str) -> None:
    raise ValidationError(msg)


_TS_FMT = "%Y-%m-%d %H:%M:%S"
_DATE_FMT = "%Y-%m-%d"
_POINT_RE = re.compile(r"^\((-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)\)$")
_GEO_RE = re.compile(r"^SRID=4326;POINT\((-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)\)$")

_POSTAL_RE = {
    "USA": re.compile(r"^\d{5}$"),
    "DEU": re.compile(r"^\d{5}$"),
    "AUS": re.compile(r"^\d{4}$"),
    "IND": re.compile(r"^\d{6}$"),
    "CAN": re.compile(r"^[A-Za-z]\d[A-Za-z] \d[A-Za-z]\d$"),
    "GBR": re.compile(r"^[A-Za-z]{1,2}\d[A-Za-z\d]? \d[A-Za-z]{2}$"),
}


def _parse_ts(table, i, col, v):
    try:
        return datetime.strptime(v, _TS_FMT)
    except ValueError:
        _fail(f"{table}[{i}].{col}='{v}' is not a valid timestamp ({_TS_FMT})")


def _parse_date(table, i, col, v):
    try:
        return datetime.strptime(v, _DATE_FMT)
    except ValueError:
        _fail(f"{table}[{i}].{col}='{v}' is not a valid date ({_DATE_FMT})")


def _parse_lonlat(table, i, col, lon_s, lat_s):
    lon, lat = float(lon_s), float(lat_s)
    if not (-180.0 <= lon <= 180.0):
        _fail(f"{table}[{i}].{col}: longitude {lon} out of [-180,180]")
    if not (-90.0 <= lat <= 90.0):
        _fail(f"{table}[{i}].{col}: latitude {lat} out of [-90,90]")
    return lon, lat


# (type_tag, required) per column.
TYPE_TAGS = {
    "countries": {"country_id": ("int", True), "country_name": ("str", True),
                  "phone_code": ("str", True), "country_code": ("str", True),
                  "last_updated_at": ("ts", False), "is_eu_member": ("bool", False)},
    "states": {"state_id": ("str", True), "country_id": ("int", True),
               "state_name": ("str", True), "state_code": ("str", False),
               "last_updated_at": ("ts", False)},
    "cities": {"city_id": ("int", True), "state_id": ("str", True),
               "city_name": ("str", True), "lattitude": ("decimal", False),
               "longitude": ("decimal", False), "last_updated_at": ("ts", False)},
    "help_categories": {"cat_id": ("str", True), "cat_name": ("str", True),
                        "cat_desc": ("str", True), "last_updated_at": ("ts", False)},
    "users": {"user_id": ("str", True), "state_id": ("str", False),
              "country_id": ("int", False), "user_status_id": ("int", False),
              "full_name": ("str", False), "first_name": ("str", False),
              "middle_name": ("str", False), "last_name": ("str", False),
              "primary_email_address": ("str", False), "primary_phone_number": ("str", False),
              "addr_ln1": ("str", False), "addr_ln2": ("str", False), "addr_ln3": ("str", False),
              "city_name": ("str", False), "zip_code": ("str", False),
              "last_location": ("point", False), "last_updated_at": ("ts", False),
              "time_zone": ("str", False), "profile_picture_path": ("str", False),
              "gender": ("str", False), "language_1": ("int", False),
              "language_2": ("int", False), "language_3": ("int", False),
              "promotion_wizard_stage": ("int", False),
              "promotion_wizard_last_updated_at": ("ts", False),
              "external_auth_provider": ("str", False), "dob": ("date", False),
              "is_eu": ("bool", False)},
    "user_skills": {"user_id": ("str", True), "cat_id": ("str", True),
                    "skill_level": ("str", False), "created_at": ("ts", False),
                    "last_updated_at": ("ts", False)},
    "user_locations": {"user_id": ("str", True), "prev_loc": ("geo", False),
                       "curr_loc": ("geo", False), "last_updated_at": ("ts", False)},
    "volunteer_details": {"user_id": ("str", True), "terms_and_conditions": ("bool", False),
                          "terms_accepted_at": ("ts", False), "govt_id_path1": ("str", False),
                          "govt_id_path2": ("str", False), "path1_updated_at": ("ts", False),
                          "path2_updated_at": ("ts", False), "availability_days": ("json", False),
                          "availability_times": ("json", False), "created_at": ("ts", False),
                          "last_updated_at": ("ts", False)},
    "volunteer_locations": {"user_id": ("str", True), "prev_loc": ("geo", False),
                            "curr_loc": ("geo", False), "last_updated_at": ("ts", False)},
    "organizations": {"org_id": ("str", True), "org_name": ("str", True),
                      "street": ("str", False), "city_name": ("str", False),
                      "state_id": ("str", False), "zip_code": ("str", False),
                      "mission": ("str", False), "web_url": ("str", False),
                      "phone": ("str", False), "email": ("str", False),
                      "org_type": ("str", False), "org_size": ("str", False),
                      "org_rating": ("int", False), "is_collaborator": ("bool", False),
                      "is_contributor": ("bool", False), "created_at": ("ts", False),
                      "last_updated_at": ("ts", False)},
}

# varchar max lengths (from schema) worth enforcing.
MAXLEN = {
    "countries": {"country_name": 100, "phone_code": 5, "country_code": 6},
    "states": {"state_id": 50, "state_name": 100, "state_code": 6},
    "cities": {"state_id": 50, "city_name": 30},
    "help_categories": {"cat_id": 50, "cat_name": 100, "cat_desc": 150},
    "users": {"user_id": 255, "state_id": 30, "full_name": 255, "first_name": 255,
              "middle_name": 255, "last_name": 255, "primary_email_address": 255,
              "primary_phone_number": 255, "city_name": 255, "zip_code": 255,
              "addr_ln1": 255, "addr_ln2": 255, "addr_ln3": 255,
              "time_zone": 255, "profile_picture_path": 255, "gender": 255,
              "external_auth_provider": 20},
    "user_skills": {"user_id": 255, "cat_id": 50},
    "user_locations": {"user_id": 255},
    "volunteer_details": {"user_id": 255},
    "volunteer_locations": {"user_id": 255},
    "organizations": {"org_id": 255, "org_name": 125, "street": 255, "city_name": 100, "state_id": 50,
                      "zip_code": 10, "web_url": 255, "phone": 20, "email": 255},
}

# enum membership.
ENUMS = {
    "users": {"gender": set(ref.GENDERS), "external_auth_provider": set(ref.AUTH_PROVIDERS)},
    "user_skills": {"skill_level": set(ref.SKILL_LEVELS)},
    "organizations": {"org_type": set(ref.ORG_TYPES), "org_size": set(ref.ORG_SIZES)},
}

# integer ranges (inclusive); None = unbounded.
INT_RANGES = {
    "countries": {"country_id": (1, None)},
    "states": {"country_id": (1, None)},
    "users": {"country_id": (1, None), "promotion_wizard_stage": (0, 100)},
    "organizations": {"org_rating": (1, 5)},
}


def _check_scalar(table, i, col, tag, v):
    """Parse/validate one non-empty scalar; returns parsed value where useful."""
    if "\x00" in v or any(0xD800 <= ord(c) <= 0xDFFF for c in v):
        _fail(f"{table}[{i}].{col}: text contains NUL or an unpaired surrogate")
    if tag == "str":
        return v
    if tag == "bool":
        if v not in ("True", "False"):
            _fail(f"{table}[{i}].{col}='{v}' is not a boolean")
        return v == "True"
    if tag == "int":
        if not re.fullmatch(r"-?[0-9]+", v):
            _fail(f"{table}[{i}].{col}='{v}' is not an integer")
        val = int(v)
        bits = 64 if table == "users" and col in ("language_1", "language_2", "language_3") else 32
        if not -(2 ** (bits - 1)) <= val < 2 ** (bits - 1):
            _fail(f"{table}[{i}].{col}: exceeds signed {bits}-bit integer range")
        return val
    if tag == "decimal":
        m = re.fullmatch(r"-?([0-9]+)(?:\.([0-9]+))?", v)
        if not m:
            _fail(f"{table}[{i}].{col}='{v}' is not a decimal")
        intd, frac = m.group(1), (m.group(2) or "")
        if len(intd) > 3 or len(frac) > 6:      # DECIMAL(9,6)
            _fail(f"{table}[{i}].{col}='{v}' exceeds DECIMAL(9,6) precision")
        return float(v)
    if tag == "ts":
        return _parse_ts(table, i, col, v)
    if tag == "date":
        return _parse_date(table, i, col, v)
    if tag == "point":
        m = _POINT_RE.fullmatch(v)
        if not m:
            _fail(f"{table}[{i}].{col}='{v}' is not a point (lon,lat)")
        return _parse_lonlat(table, i, col, m.group(1), m.group(2))
    if tag == "geo":
        m = _GEO_RE.fullmatch(v)
        if not m:
            _fail(f"{table}[{i}].{col}='{v}' is not EWKT SRID=4326;POINT(lon lat)")
        return _parse_lonlat(table, i, col, m.group(1), m.group(2))
    if tag == "json":
        try:
            def reject_constant(value):
                raise ValueError(f"non-finite JSON number {value}")

            decoded = json.loads(v, parse_constant=reject_constant,
                                 parse_float=Decimal, parse_int=Decimal)
            pending = [decoded]
            while pending:
                item = pending.pop()
                if isinstance(item, dict):
                    pending.extend(item.keys())
                    pending.extend(item.values())
                elif isinstance(item, list):
                    pending.extend(item)
                elif isinstance(item, str):
                    if "\x00" in item or any(0xD800 <= ord(c) <= 0xDFFF for c in item):
                        raise ValueError("JSONB cannot store NUL or unpaired surrogates")
                elif isinstance(item, Decimal):
                    if item.adjusted() >= 131072 or item.as_tuple().exponent < -16383:
                        raise ValueError("JSONB number exceeds PostgreSQL numeric range")
        except ValueError:
            _fail(f"{table}[{i}].{col}='{v}' is not valid JSON")
        return v
    _fail(f"{table}.{col}: unknown type tag {tag}")


# ===========================================================================
# Validation passes
# ===========================================================================
def validate_schema_types_ranges(dataset):
    """Headers, required fields, types, lengths, enums, int ranges.
    Returns a dict of parsed timestamps per table for ordering checks."""
    for table in TYPE_TAGS:
        if table not in dataset:
            _fail(f"missing required table '{table}'")

    extra_tables = set(dataset) - set(TYPE_TAGS)
    if extra_tables:
        _fail(f"unexpected tables: {sorted(extra_tables)}")
    parsed = {}
    for table, (fieldnames, rows) in dataset.items():
        spec = TYPE_TAGS[table]
        if list(fieldnames) != list(spec.keys()):
            _fail(f"{table}: header/column order does not match schema")
        parsed[table] = []
        for i, r in enumerate(rows):
            missing = set(fieldnames) - set(r.keys())
            if missing:
                _fail(f"{table}[{i}]: missing fields {missing}")
            extra = set(r.keys()) - set(fieldnames)
            if extra:
                _fail(f"{table}[{i}]: extra fields {extra}")
            prow = {}
            for col, (tag, required) in spec.items():
                v = r.get(col)
                s = "" if v is None else str(v)
                if s == "":
                    if required:
                        _fail(f"{table}[{i}].{col} is required but empty")
                    prow[col] = None
                    continue
                val = _check_scalar(table, i, col, tag, s)
                prow[col] = val
                mx = MAXLEN.get(table, {}).get(col)
                if mx is not None and len(s) > mx:
                    _fail(f"{table}[{i}].{col} length {len(s)} exceeds varchar({mx})")
                en = ENUMS.get(table, {}).get(col)
                if en is not None and s not in en:
                    _fail(f"{table}[{i}].{col}='{s}' not in enum {sorted(en)}")
                rng = INT_RANGES.get(table, {}).get(col)
                if rng is not None:
                    lo, hi = rng
                    if (lo is not None and val < lo) or (hi is not None and val > hi):
                        _fail(f"{table}[{i}].{col}={val} out of range [{lo},{hi}]")
                if table == "cities" and col in ("lattitude", "longitude"):
                    bound = 90 if col == "lattitude" else 180
                    if not -bound <= val <= bound:
                        _fail(f"cities[{i}].{col}: outside geographic bounds")
                if table == "organizations":
                    if col == "web_url" and not s.startswith("http"):
                        _fail(f"organizations[{i}].web_url violates schema CHECK")
                    if col == "email" and "@" not in s:
                        _fail(f"organizations[{i}].email violates schema CHECK")
            parsed[table].append(prow)
    return parsed


def validate_timestamp_ordering(parsed):
    for i, r in enumerate(parsed["user_skills"]):
        if r["created_at"] and r["last_updated_at"] and r["created_at"] > r["last_updated_at"]:
            _fail(f"user_skills[{i}]: created_at > last_updated_at")

    for i, r in enumerate(parsed["organizations"]):
        if r["created_at"] and r["last_updated_at"] and r["created_at"] > r["last_updated_at"]:
            _fail(f"organizations[{i}]: created_at > last_updated_at")

    vd_created = {}
    for i, r in enumerate(parsed["volunteer_details"]):
        c, lu = r["created_at"], r["last_updated_at"]
        if c and lu and c > lu:
            _fail(f"volunteer_details[{i}]: created_at > last_updated_at")
        for col in ("terms_accepted_at", "path1_updated_at", "path2_updated_at"):
            v = r[col]
            if v and lu and v > lu:
                _fail(f"volunteer_details[{i}].{col} after last_updated_at")
            if v and c and v < c:
                _fail(f"volunteer_details[{i}].{col} before created_at")
        vd_created[r["user_id"]] = c

    for i, r in enumerate(parsed["volunteer_locations"]):
        uid, lu = r["user_id"], r["last_updated_at"]
        created = vd_created.get(uid)
        if lu and created and lu < created:
            _fail(f"volunteer_locations[{i}]: last_updated_at precedes volunteer_details.created_at")


def validate_geo_postal_tz(dataset, parsed, aux):
    max_deg = ref.POINT_JITTER_DEG + 0.000001

    for i, row in enumerate(parsed["cities"]):
        key = (row["city_name"], row["state_id"])
        expected = aux["city_coord"].get(key)
        if expected is None:
            _fail(f"cities[{i}]: unknown city/state pair")
        if row["lattitude"] is not None and abs(row["lattitude"] - expected[0]) > 0.000001:
            _fail(f"cities[{i}]: latitude differs from reference")
        if row["longitude"] is not None and abs(row["longitude"] - expected[1]) > 0.000001:
            _fail(f"cities[{i}]: longitude differs from reference")

    # verify the reference postal codes themselves are country-well-formed
    for (city, state_id), postal in aux["postal_by_city"].items():
        cc = aux["country_code"][aux["state_country"][state_id]]
        rx = _POSTAL_RE.get(cc)
        if rx and not rx.fullmatch(postal):
            _fail(f"reference postal '{postal}' malformed for {cc}")

    def check_loc(table, rows_parsed, city_of):
        for i, r in enumerate(rows_parsed):
            key = city_of(r, i)
            if key is None:
                continue
            coord = aux["city_coord"].get(key)
            if coord is None:
                _fail(f"{table}[{i}]: city {key} not in geo reference")
            clat, clon = coord[0], coord[1]
            for col in ("last_location", "prev_loc", "curr_loc"):
                if col in r and r[col] is not None:
                    lon, lat = r[col]
                    if abs(lat - clat) > max_deg or abs(lon - clon) > max_deg:
                        _fail(f"{table}[{i}].{col} too far from city {key}")

    users_p = parsed["users"]
    user_city = {r["user_id"]: (dataset["users"][1][i]["city_name"],
                                str(dataset["users"][1][i]["state_id"]))
                 for i, r in enumerate(users_p)}

    # users: postal + tz + language/status lookups + point proximity
    for i, r in enumerate(users_p):
        raw = dataset["users"][1][i]
        key = (raw["city_name"], str(raw["state_id"]))
        expected_postal = aux["postal_by_city"].get(key)
        if expected_postal is None:
            _fail(f"users[{i}]: city {key} not in geo reference")
        if raw["zip_code"] != expected_postal:
            _fail(f"users[{i}].zip_code '{raw['zip_code']}' != city postal '{expected_postal}'")
        if raw["time_zone"] != aux["state_tz"][str(raw["state_id"])]:
            _fail(f"users[{i}].time_zone '{raw['time_zone']}' != state tz "
                  f"'{aux['state_tz'][str(raw['state_id'])]}'")
        if r["user_status_id"] is not None and r["user_status_id"] not in aux["status_ids"]:
            _fail(f"users[{i}].user_status_id {r['user_status_id']} not a verified lookup id")
        for lc in ("language_1", "language_2", "language_3"):
            if r[lc] is not None and r[lc] not in aux["language_ids"]:
                _fail(f"users[{i}].{lc} {r[lc]} not a verified supporting_languages id")
    check_loc("users", users_p, lambda r, i: (dataset["users"][1][i]["city_name"],
                                              str(dataset["users"][1][i]["state_id"])))

    check_loc("user_locations", parsed["user_locations"],
              lambda r, i: user_city.get(r["user_id"]))
    check_loc("volunteer_locations", parsed["volunteer_locations"],
              lambda r, i: user_city.get(r["user_id"]))

    # organizations: postal must match its city
    for i, r in enumerate(dataset["organizations"][1]):
        key = (r["city_name"], str(r["state_id"]))
        expected_postal = aux["postal_by_city"].get(key)
        if expected_postal is None:
            _fail(f"organizations[{i}]: city {key} not in geo reference")
        if r["zip_code"] != expected_postal:
            _fail(f"organizations[{i}].zip_code '{r['zip_code']}' != city postal '{expected_postal}'")


def validate_integrity(dataset):
    def col(table, name):
        return [r[name] for r in dataset[table][1]]

    def col_set(table, name):
        return {str(v) for v in col(table, name)}

    def unique(table, keys):
        seen = set()
        for r in dataset[table][1]:
            k = tuple(r[key] for key in keys)
            if k in seen:
                _fail(f"{table}: duplicate PK {k}")
            seen.add(k)

    for table, keys in [("countries", ["country_id"]), ("states", ["state_id"]),
                        ("cities", ["city_id"]), ("help_categories", ["cat_id"]),
                        ("users", ["user_id"]), ("user_skills", ["user_id", "cat_id"]),
                        ("user_locations", ["user_id"]), ("volunteer_details", ["user_id"]),
                        ("volunteer_locations", ["user_id"]), ("organizations", ["org_id"])]:
        unique(table, keys)

    country_ids = col_set("countries", "country_id")
    state_ids = col_set("states", "state_id")
    city_names = col_set("cities", "city_name")
    user_ids = col_set("users", "user_id")
    cat_ids = col_set("help_categories", "cat_id")
    volunteer_ids = col_set("volunteer_details", "user_id")

    def check_fk(table, column, valid, label):
        for v in col(table, column):
            if v is None or v == "":
                continue
            if str(v) not in valid:
                _fail(f"{table}.{column} orphan '{v}' (not a {label})")

    check_fk("states", "country_id", country_ids, "country_id")
    check_fk("cities", "state_id", state_ids, "state_id")
    check_fk("users", "country_id", country_ids, "country_id")
    check_fk("users", "state_id", state_ids, "state_id")
    check_fk("users", "city_name", city_names, "city_name")
    check_fk("user_skills", "user_id", user_ids, "user_id")
    check_fk("user_skills", "cat_id", cat_ids, "cat_id")
    check_fk("user_locations", "user_id", user_ids, "user_id")
    check_fk("volunteer_details", "user_id", user_ids, "user_id")
    # critical: volunteer_locations.user_id -> volunteer_details.user_id
    check_fk("volunteer_locations", "user_id", volunteer_ids, "volunteer_details.user_id")
    check_fk("organizations", "state_id", state_ids, "state_id")
    check_fk("organizations", "city_name", city_names, "city_name")

    city_to_state = {(r["city_name"], str(r["state_id"])) for r in dataset["cities"][1]}
    state_to_country = {(str(r["state_id"]), str(r["country_id"])) for r in dataset["states"][1]}
    for i, r in enumerate(dataset["users"][1]):
        if (r["city_name"], str(r["state_id"])) not in city_to_state:
            _fail(f"users[{i}]: city '{r['city_name']}' not in state {r['state_id']}")
        if (str(r["state_id"]), str(r["country_id"])) not in state_to_country:
            _fail(f"users[{i}]: state {r['state_id']} not in country {r['country_id']}")
    for i, r in enumerate(dataset["organizations"][1]):
        if (r["city_name"], str(r["state_id"])) not in city_to_state:
            _fail(f"organizations[{i}]: city '{r['city_name']}' not in state {r['state_id']}")


def validate(dataset, aux):
    parsed = validate_schema_types_ranges(dataset)
    validate_integrity(dataset)
    validate_timestamp_ordering(parsed)
    validate_geo_postal_tz(dataset, parsed, aux)


# ===========================================================================
# CLI
# ===========================================================================
def _parse_args(argv):
    p = argparse.ArgumentParser(description="Generate Saayam mock data CSVs.")
    p.add_argument("--users", type=int, default=config.USERS,
                   help=f"number of users, >= 0 (default {config.USERS})")
    p.add_argument("--orgs", type=int, default=config.ORGANIZATIONS,
                   help=f"number of organizations, >= 0 (default {config.ORGANIZATIONS})")
    p.add_argument("--seed", type=int, default=config.SEED,
                   help=f"RNG seed (default {config.SEED})")
    p.add_argument("--out", default=None,
                   help=f"output directory (default {config.OUTPUT_DIR})")
    p.add_argument("--no-validate", action="store_true", help="skip validation")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    # Reject invalid CLI / configuration inputs up front.
    config.validate(args.users, args.orgs, config.CITIES_PER_STATE,
                    config.VOLUNTEER_RATIO, config.USER_LOCATION_RATIO,
                    config.SKILLS_PER_USER_MIN, config.SKILLS_PER_USER_MAX)

    set_seed(args.seed)
    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       config.OUTPUT_DIR)

    dataset, aux = build_dataset(args.users, args.orgs)

    if not args.no_validate:
        validate(dataset, aux)
        print("Validation passed (schema, types, ranges, timestamps, geo, postal, "
              "tz, lookups, PK/FK).")

    print(f"\nWriting CSVs to: {out_dir}\n")
    total = 0
    for table, (fieldnames, rows) in dataset.items():
        path = os.path.join(out_dir, f"{table}.csv")
        n = write_csv(path, fieldnames, rows)
        total += n
        print(f"  {table:<22} {n:>6} rows")
    print(f"\nDone. {len(dataset)} files, {total} total rows.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ConfigError, ValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
