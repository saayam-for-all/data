"""Row generators for all ten in-scope tables.

Generation order enforces referential integrity:

    countries -> states -> cities -> help_categories -> users
    -> user_skills / user_locations / volunteer_details -> volunteer_locations
    -> organizations

Each ``build_*`` function returns ``(fieldnames, rows)`` where ``fieldnames`` is
the exact column order from the ``virginia_dev_saayam_rdbms`` schema (per the
database wiki "Table after changes"). The orchestrator threads the shared
context (locations, users, volunteer timestamps) between them so no foreign key
is orphaned and related timestamps stay ordered.

Notes:
  * ``volunteer_locations.user_id`` references ``volunteer_details.user_id``, so
    it is built only for users that already have a volunteer_details row, and
    its ``last_updated_at`` is generated at/after that row's ``created_at``.
  * Postal codes and time zones are properties of the city/state, never chosen
    independently of location.
"""

from __future__ import annotations

import random
from datetime import date
from typing import Any, Dict, List, Tuple

import config
import reference_data as ref
from utils import (
    between,
    format_date,
    format_ts,
    geography_point,
    json_text,
    later_than,
    maybe,
    native_point,
    pick,
    random_datetime,
    synth_postal,
    synthetic_user_id,
)

Rows = List[Dict[str, Any]]
Built = Tuple[List[str], Rows]

# ---------------------------------------------------------------------------
# Exact schema column orders (virginia_dev_saayam_rdbms, post-pluralization)
# ---------------------------------------------------------------------------
COLUMNS: Dict[str, List[str]] = {
    "countries": ["country_id", "country_name", "phone_code", "country_code",
                  "last_updated_at", "is_eu_member"],
    "states": ["state_id", "country_id", "state_name", "state_code", "last_updated_at"],
    "cities": ["city_id", "state_id", "city_name", "lattitude", "longitude", "last_updated_at"],
    "help_categories": ["cat_id", "cat_name", "cat_desc", "last_updated_at"],
    "users": ["user_id", "state_id", "country_id", "user_status_id",
              "full_name", "first_name", "middle_name", "last_name",
              "primary_email_address", "primary_phone_number",
              "addr_ln1", "addr_ln2", "addr_ln3", "city_name", "zip_code", "last_location",
              "last_updated_at", "time_zone", "profile_picture_path", "gender",
              "language_1", "language_2", "language_3",
              "promotion_wizard_stage", "promotion_wizard_last_updated_at",
              "external_auth_provider", "dob", "is_eu"],
    "user_skills": ["user_id", "cat_id", "skill_level", "created_at", "last_updated_at"],
    "user_locations": ["user_id", "prev_loc", "curr_loc", "last_updated_at"],
    "volunteer_details": ["user_id", "terms_and_conditions", "terms_accepted_at",
                          "govt_id_path1", "govt_id_path2", "path1_updated_at",
                          "path2_updated_at", "availability_days", "availability_times",
                          "created_at", "last_updated_at"],
    "volunteer_locations": ["user_id", "prev_loc", "curr_loc", "last_updated_at"],
    "organizations": ["org_id", "org_name", "street", "city_name", "state_id", "zip_code",
                      "mission", "web_url", "phone", "email", "org_type", "org_size",
                      "org_rating", "is_collaborator", "is_contributor",
                      "created_at", "last_updated_at"],
}


# ---------------------------------------------------------------------------
# Geography: countries -> states -> cities + a flat location index + aux
# ---------------------------------------------------------------------------
class Location:
    """A geographically consistent (country, state, city) tuple."""

    __slots__ = ("country_id", "country_code", "is_eu", "state_id", "state_code",
                 "state_name", "tz", "city_name", "lat", "lon", "postal")

    def __init__(self, country_id, country_code, is_eu, state_id, state_code,
                 state_name, tz, city_name, lat, lon, postal):
        self.country_id = country_id
        self.country_code = country_code
        self.is_eu = is_eu
        self.state_id = state_id
        self.state_code = state_code
        self.state_name = state_name
        self.tz = tz
        self.city_name = city_name
        self.lat = lat
        self.lon = lon
        self.postal = postal


def build_geo():
    """Build countries/states/cities rows, a flat Location list, and an ``aux``
    dict of verified reference maps used by validation."""
    country_rows: Rows = []
    state_rows: Rows = []
    city_rows: Rows = []
    locations: List[Location] = []

    aux = {
        "state_tz": {},
        "state_country": {},
        "country_code": {},
        "city_coord": {},
        "postal_by_city": {},
        "language_ids": set(config.LANGUAGE_IDS),
        "status_ids": set(config.USER_STATUS_IDS),
    }

    code_to_country = {}
    for cid, name, phone, code, is_eu in ref.COUNTRIES:
        code_to_country[code] = (cid, is_eu)
        aux["country_code"][cid] = code
        country_rows.append({
            "country_id": cid,
            "country_name": name,
            "phone_code": phone,
            "country_code": code,
            "last_updated_at": format_ts(random_datetime()),
            "is_eu_member": str(is_eu),
        })

    next_state_id = 1
    next_city_id = 1
    for country_code, states in ref.GEO.items():
        country_id, country_is_eu = code_to_country[country_code]
        for state_name, state_code, tz, seed_cities in states:
            state_id = str(next_state_id)   # varchar in schema; integer-valued string
            next_state_id += 1
            aux["state_tz"][state_id] = tz
            aux["state_country"][state_id] = country_id
            state_rows.append({
                "state_id": state_id,
                "country_id": country_id,
                "state_name": state_name,
                "state_code": state_code,
                "last_updated_at": format_ts(random_datetime()),
            })

            all_cities: List[Tuple[str, float, float, str]] = list(seed_cities)
            used_names = {c[0] for c in seed_cities}
            for _ in range(config.CITIES_PER_STATE):
                base = pick(seed_cities)
                # Keep synthesized city names unique within the state so the
                # (city_name, state_id) key that postal/coord maps rely on is 1:1.
                for _attempt in range(50):
                    name = f"{pick(ref.CITY_PREFIXES)} {base[0].split()[0]}{pick(ref.CITY_SUFFIXES)}"
                    if name not in used_names:
                        break
                else:
                    name = f"{name} {len(used_names)}"
                used_names.add(name)
                lat = round(base[1] + random.uniform(-ref.CITY_JITTER_DEG, ref.CITY_JITTER_DEG), 6)
                lon = round(base[2] + random.uniform(-ref.CITY_JITTER_DEG, ref.CITY_JITTER_DEG), 6)
                postal = synth_postal(country_code, base[3])
                all_cities.append((name, lat, lon, postal))

            for city_name, lat, lon, postal in all_cities:
                city_rows.append({
                    "city_id": next_city_id,
                    "state_id": state_id,
                    "city_name": city_name,
                    "lattitude": round(lat, 6),
                    "longitude": round(lon, 6),
                    "last_updated_at": format_ts(random_datetime()),
                })
                next_city_id += 1
                aux["city_coord"][(city_name, state_id)] = (lat, lon)
                aux["postal_by_city"][(city_name, state_id)] = postal
                locations.append(Location(country_id, country_code, country_is_eu,
                                          state_id, state_code, state_name, tz,
                                          city_name, lat, lon, postal))

    return ((COLUMNS["countries"], country_rows),
            (COLUMNS["states"], state_rows),
            (COLUMNS["cities"], city_rows),
            locations, aux)


# ---------------------------------------------------------------------------
# help_categories
# ---------------------------------------------------------------------------
def build_help_categories() -> Tuple[Built, List[str]]:
    rows: Rows = [{"cat_id": cid, "cat_name": name, "cat_desc": desc,
                   "last_updated_at": format_ts(random_datetime())}
                  for cid, name, desc in ref.HELP_CATEGORIES]
    cat_ids = [cid for cid, _, _ in ref.HELP_CATEGORIES]
    return (COLUMNS["help_categories"], rows), cat_ids


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------
class User:
    __slots__ = ("user_id", "location", "created", "is_volunteer")

    def __init__(self, user_id, location, created):
        self.user_id = user_id
        self.location = location
        self.created = created
        self.is_volunteer = False


def _synth_phone(country_code: str) -> str:
    """Reserved NANP fictional numbers; NULL for other countries."""
    suffix = random.randint(0, 99)
    prefix = {"USA": "+1-202", "CAN": "+1-416"}.get(country_code)
    return f"{prefix}-555-01{suffix:02d}" if prefix else None


def _point_near(loc: Location) -> Tuple[float, float]:
    j = ref.POINT_JITTER_DEG
    return (round(loc.lon + random.uniform(-j, j), 6),
            round(loc.lat + random.uniform(-j, j), 6))


def build_users(locations: List[Location], count: int) -> Tuple[Built, List[User]]:
    rows: Rows = []
    users: List[User] = []
    seen_ids = set()
    status_ids = config.USER_STATUS_IDS
    lang_ids = config.LANGUAGE_IDS

    for _ in range(count):
        uid = synthetic_user_id()
        while uid in seen_ids:
            uid = synthetic_user_id()
        seen_ids.add(uid)

        loc = pick(locations)
        first = pick(ref.FIRST_NAMES)
        middle = pick(ref.MIDDLE_NAMES)
        last = pick(ref.LAST_NAMES)
        full = " ".join(p for p in [first, middle, last] if p)
        email = f"{first}.{last}{random.randint(1, 9999)}@example.org".lower()
        created = random_datetime()
        langs = random.sample(lang_ids, k=min(random.randint(1, 3), len(lang_ids))) if lang_ids else []
        langs += [None] * (3 - len(langs))
        lon, lat = _point_near(loc)

        rows.append({
            "user_id": uid,
            "state_id": loc.state_id,
            "country_id": loc.country_id,
            "user_status_id": (pick(status_ids) if status_ids else None),
            "full_name": full,
            "first_name": first,
            "middle_name": middle or None,
            "last_name": last,
            "primary_email_address": email,
            "primary_phone_number": _synth_phone(loc.country_code),
            "addr_ln1": f"{random.randint(1, 9999)} {pick(ref.STREET_NAMES)} {pick(ref.STREET_TYPES)}",
            "addr_ln2": maybe(f"Apt {random.randint(1, 400)}", 0.35),
            "addr_ln3": None,
            "city_name": loc.city_name,
            "zip_code": loc.postal,
            "last_location": native_point(lon, lat),
            "last_updated_at": format_ts(later_than(created)),
            "time_zone": loc.tz,
            "profile_picture_path": maybe(f"s3://saayam-mock/profiles/{uid}.jpg", 0.6),
            "gender": pick(ref.GENDERS),
            "language_1": langs[0],
            "language_2": langs[1],
            "language_3": langs[2],
            "promotion_wizard_stage": random.randint(0, 5),
            "promotion_wizard_last_updated_at": format_ts(later_than(created)),
            "external_auth_provider": pick(ref.AUTH_PROVIDERS),
            "dob": format_date(date(random.randint(1950, 2005),
                                    random.randint(1, 12), random.randint(1, 28))),
            "is_eu": str(loc.is_eu),
        })
        users.append(User(uid, loc, created))

    return (COLUMNS["users"], rows), users


# ---------------------------------------------------------------------------
# user_skills (composite PK: user_id + cat_id)
# ---------------------------------------------------------------------------
def build_user_skills(users: List[User], cat_ids: List[str]) -> Built:
    rows: Rows = []
    if not cat_ids:
        return COLUMNS["user_skills"], rows
    lo = config.SKILLS_PER_USER_MIN
    hi = min(config.SKILLS_PER_USER_MAX, len(cat_ids))
    for u in users:
        k = random.randint(lo, max(lo, hi))
        for cid in random.sample(cat_ids, k=min(k, len(cat_ids))):
            created = later_than(u.created, max_days=30)
            updated = later_than(created, max_days=60)
            rows.append({
                "user_id": u.user_id,
                "cat_id": cid,
                "skill_level": pick(ref.SKILL_LEVELS),
                "created_at": format_ts(created),
                "last_updated_at": format_ts(updated),   # >= created_at
            })
    return COLUMNS["user_skills"], rows


# ---------------------------------------------------------------------------
# user_locations (PK: user_id)
# ---------------------------------------------------------------------------
def _geo_near(loc: Location) -> str:
    lon, lat = _point_near(loc)
    return geography_point(lon, lat)


def build_user_locations(users: List[User]) -> Built:
    rows: Rows = []
    for u in users:
        if random.random() > config.USER_LOCATION_RATIO:
            continue
        rows.append({
            "user_id": u.user_id,
            "prev_loc": maybe(_geo_near(u.location), 0.6),
            "curr_loc": _geo_near(u.location),
            "last_updated_at": format_ts(later_than(u.created)),
        })
    return COLUMNS["user_locations"], rows


# ---------------------------------------------------------------------------
# volunteers -> volunteer_details, then volunteer_locations (FK to details)
# ---------------------------------------------------------------------------
def select_volunteers(users: List[User]) -> List[User]:
    """Pick a random subset of users to act as volunteers (schema has no
    user_category column, so volunteers are chosen by ratio)."""
    target = int(len(users) * config.VOLUNTEER_RATIO)
    vols = random.sample(users, k=min(target, len(users))) if users else []
    for u in vols:
        u.is_volunteer = True
    return vols


def build_volunteer_details(volunteers: List[User]):
    """Returns (Built, {user_id: (created_dt, last_updated_dt)}) so
    volunteer_locations can order its timestamps after details creation.
    All document-update timestamps fall within [created_at, last_updated_at]."""
    rows: Rows = []
    ts_map: Dict[str, Tuple[Any, Any]] = {}
    for u in volunteers:
        created = later_than(u.created, max_days=20)
        last_updated = later_than(created, max_days=60)   # >= created
        terms_accepted = between(created, last_updated)
        path1 = between(created, last_updated)
        path2 = between(created, last_updated)
        rows.append({
            "user_id": u.user_id,
            "terms_and_conditions": "True",
            "terms_accepted_at": format_ts(terms_accepted),
            "govt_id_path1": maybe(f"s3://saayam-mock/govt-id/{u.user_id}_1.pdf", 0.8),
            "govt_id_path2": maybe(f"s3://saayam-mock/govt-id/{u.user_id}_2.pdf", 0.4),
            "path1_updated_at": format_ts(path1),
            "path2_updated_at": maybe(format_ts(path2), 0.4),
            "availability_days": json_text(pick(ref.AVAILABILITY_DAYS)),
            "availability_times": json_text(pick(ref.AVAILABILITY_TIMES)),
            "created_at": format_ts(created),
            "last_updated_at": format_ts(last_updated),
        })
        ts_map[u.user_id] = (created, last_updated)
    return (COLUMNS["volunteer_details"], rows), ts_map


def build_volunteer_locations(volunteers: List[User], details_ts) -> Built:
    """Only users with a volunteer_details row get a location (FK
    volunteer_locations.user_id -> volunteer_details.user_id). last_updated_at
    is generated at/after the details row's created_at."""
    rows: Rows = []
    for u in volunteers:
        if random.random() > 0.85:
            continue
        created, last_updated = details_ts[u.user_id]
        loc_updated = between(created, later_than(last_updated, 30))  # >= created
        rows.append({
            "user_id": u.user_id,
            "prev_loc": maybe(_geo_near(u.location), 0.6),
            "curr_loc": _geo_near(u.location),
            "last_updated_at": format_ts(loc_updated),
        })
    return COLUMNS["volunteer_locations"], rows


# ---------------------------------------------------------------------------
# organizations (PK: org_id)
# ---------------------------------------------------------------------------
def _org_name() -> str:
    return f"{pick(ref.ORG_NAME_PREFIX)} {pick(ref.ORG_NAME_CORE)} {pick(ref.ORG_NAME_SUFFIX)}"


def _mission() -> str:
    words = random.sample(ref.MISSION_WORDS, k=random.randint(8, 12))
    return ("To " + " ".join(words)).capitalize() + "."


def build_organizations(locations: List[Location], count: int) -> Built:
    rows: Rows = []
    for i in range(1, count + 1):
        loc = pick(locations)
        name = _org_name()
        # ORG<n> suffix keeps each invented domain unique; the .example TLD is
        # reserved (RFC 2606) and can never belong to a real organization.
        slug = "".join(c for c in name.lower() if c.isalnum())[:24] + f"-{i:06d}"
        created = random_datetime()
        last_updated = later_than(created)   # >= created_at
        rows.append({
            "org_id": f"ORG{i:06d}",
            "org_name": name[:125],
            "street": f"{random.randint(1, 9999)} {pick(ref.STREET_NAMES)} {pick(ref.STREET_TYPES)}",
            "city_name": loc.city_name,
            "state_id": loc.state_id,
            "zip_code": loc.postal,
            "mission": _mission(),
            "web_url": f"https://www.{slug}.example",
            "phone": _synth_phone(loc.country_code),
            "email": maybe(f"contact@{slug}.example", 0.85),
            "org_type": pick(ref.ORG_TYPES),
            "org_size": pick(ref.ORG_SIZES),
            "org_rating": random.randint(1, 5),
            "is_collaborator": str(random.random() < 0.4),
            "is_contributor": str(random.random() < 0.6),
            "created_at": format_ts(created),
            "last_updated_at": format_ts(last_updated),
        })
    return COLUMNS["organizations"], rows
