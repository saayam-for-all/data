"""
generators.py
-------------
Per-table generator functions for the mock-data pipeline.

Public API
~~~~~~~~~~
Every public generator follows this signature::

    generate_<table>(
        ctx:   dict,          # runtime context (ID pools, related rows)
        rng:   random.Random,
        fake:  Faker,
        count: int,
    ) -> list[dict[str, str]]

``config`` is accessed as a module-level import (``import config as cfg``),
not as a parameter.

Values are always returned as strings — csv.DictWriter writes them verbatim.

The ``GENERATORS`` dict at the bottom of this file maps every table name
to its generator function so that ``generate_mock_data.py`` can dispatch
without a long if/elif chain.
"""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta

from faker import Faker

import config as cfg


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fmt_ts(dt: datetime) -> str:
    return dt.strftime(cfg.TIMESTAMP_FORMAT)


def _fmt_date(d: date) -> str:
    return d.strftime(cfg.DATE_FORMAT)


def _data_start() -> datetime:
    return datetime(cfg.DATA_START_YEAR, cfg.DATA_START_MONTH, cfg.DATA_START_DAY)


def _data_end() -> datetime:
    return datetime(cfg.DATA_END_YEAR, cfg.DATA_END_MONTH, cfg.DATA_END_DAY)


def _rand_dt(rng: random.Random, lo: datetime | None = None, hi: datetime | None = None) -> datetime:
    """Return a random datetime within [lo, hi], defaulting to the data window."""
    lo = lo or _data_start()
    hi = hi or _data_end()
    span = int((hi - lo).total_seconds())
    if span <= 0:
        return lo
    return lo + timedelta(seconds=rng.randint(0, span))


def _rand_date(rng: random.Random, lo: date | None = None, hi: date | None = None) -> date:
    return _rand_dt(rng, *(datetime(d.year, d.month, d.day) if d else None for d in (lo, hi))).date()


def _wkt_point(rng: random.Random) -> str:
    """Return a WKT POINT string within the configured bounding box."""
    lat = rng.uniform(cfg.GEO_LAT_MIN, cfg.GEO_LAT_MAX)
    lon = rng.uniform(cfg.GEO_LON_MIN, cfg.GEO_LON_MAX)
    return f"POINT({lon:.6f} {lat:.6f})"


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _sample(rng: random.Random, pool: list, k: int = 1) -> Any:
    """Sample k items from pool.  Returns a single item when k == 1."""
    if not pool:
        return "" if k == 1 else []
    if k == 1:
        return rng.choice(pool)
    return rng.sample(pool, min(k, len(pool)))


def _weighted_bool(rng: random.Random, true_weight: float) -> str:
    return "true" if rng.random() < true_weight else "false"



# ---------------------------------------------------------------------------
# Lookup-adjacent independent tables
# (small, no FK dependencies on generated tables)
# ---------------------------------------------------------------------------


def generate_action(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``action`` lookup/audit table."""
    descs = cfg.ENUM_VALUES["action.action_desc"]
    rows = []
    for idx in range(count):
        created = _rand_dt(rng)
        rows.append({
            "action_id": str(idx + 1),
            "action_desc": descs[idx % len(descs)],
            "created_date": _fmt_ts(created),
            "created_by": fake.user_name()[:30],
            "last_update_by": fake.user_name()[:30],
            "last_update_date": _fmt_ts(created + timedelta(days=rng.randint(0, 30))),
        })
    return rows


def generate_identity_type(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``identity_type`` reference table."""
    values = cfg.ENUM_VALUES["identity_type.identity_value"]
    rows = []
    for idx in range(min(count, len(values))):
        rows.append({
            "identity_type_id": str(idx + 1),
            "identity_value": values[idx],
            "identity_type_dsc": f"Government-issued {values[idx].replace('_', ' ').title()}",
            "last_updated_date": _fmt_ts(_rand_dt(rng)),
        })
    return rows


def generate_sla(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``sla`` (Service Level Agreement) table."""
    tiers = [
        (4,   "CRITICAL - 4 hours response",   1),
        (24,  "HIGH - 24 hours response",       10),
        (72,  "MEDIUM - 72 hours response",     50),
        (168, "LOW - 7 days response",          200),
        (720, "STANDARD - 30 days response",    500),
    ]
    rows = []
    for idx in range(min(count, len(tiers))):
        hours, desc, impact = tiers[idx]
        rows.append({
            "sla_id": str(idx + 1),
            "sla_hours": str(hours),
            "sla_description": desc,
            "no_of_cust_impct": str(impact),
            "last_updated_date": _fmt_ts(_rand_dt(rng)),
        })
    return rows


def generate_news_snippets(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``news_snippets`` table."""
    link_keys = cfg.ENUM_VALUES["news_snippets.profile_links_keys"]
    rows = []
    for idx in range(count):
        created = _rand_dt(rng)
        profile_links = {k: fake.url() for k in rng.sample(link_keys, rng.randint(1, 3))}
        rows.append({
            "news_id": str(idx + 1),
            "headline": fake.sentence(nb_words=8)[:255],
            "snippet_text": fake.paragraph(nb_sentences=4),
            "image_path": f"/assets/news/{idx + 1}.jpg",
            "profile_links": _json(profile_links),
            "event_date": _fmt_date(_rand_date(rng)),
            "created_at": _fmt_ts(created),
            "last_updated_at": _fmt_ts(created + timedelta(days=rng.randint(0, 10))),
        })
    return rows


def generate_user_signoff(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``user_signoff`` table."""
    reasons = cfg.ENUM_VALUES["user_signoff.reason"]
    rows = []
    for idx in range(count):
        rows.append({
            "signoff_id": str(idx + 1),
            "reason": _sample(rng, reasons),
            "is_external_auth": _weighted_bool(rng, 0.40),
        })
    return rows


def generate_volunteer_organizations(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the standalone ``volunteer_organizations`` table."""
    rows = []
    for idx in range(count):
        rows.append({
            "volunteer_organization_id": str(idx + 1),
            "contact_id": f"U{str(rng.randint(1, 9999)).zfill(cfg.USER_ID_ZERO_PAD)}",
            "city_name": fake.city()[:255],
            "addr_ln1": fake.street_address()[:255],
            "addr_ln2": fake.secondary_address()[:255],
            "addr_ln3": "",
            "zip_code": fake.zipcode()[:255],
            "last_update_date": _fmt_ts(_rand_dt(rng)),
            "time_zone": rng.choice([
                "America/New_York", "America/Chicago",
                "America/Denver", "America/Los_Angeles",
            ]),
        })
    return rows


# ---------------------------------------------------------------------------
# Geography-dependent tables (depend on lookup country/state)
# ---------------------------------------------------------------------------


def generate_city(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``city`` table referencing lookup state IDs."""
    state_ids = ctx.get("state_ids", ["CA", "NY", "TX"])
    rows = []
    for idx in range(count):
        rows.append({
            "city_id": str(idx + 1),
            "state_id": str(_sample(rng, state_ids)),
            "city_name": fake.city()[:30],
            "lattitude": str(round(rng.uniform(cfg.GEO_LAT_MIN, cfg.GEO_LAT_MAX), 6)),
            "longitude": str(round(rng.uniform(cfg.GEO_LON_MIN, cfg.GEO_LON_MAX), 6)),
            "last_update_date": _fmt_ts(_rand_dt(rng)),
        })
    return rows


def generate_emergency_numbers(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``emergency_numbers`` table."""
    country_ids = ctx.get("country_ids", [1])
    state_ids = ctx.get("state_ids", ["CA"])
    rows = []
    for idx in range(count):
        is_country = rng.random() < 0.60
        rows.append({
            "en_id": str(idx + 1),
            "country_id": str(_sample(rng, country_ids)),
            "state_id": "" if is_country else str(_sample(rng, state_ids))[:50],
            "en_name": fake.company()[:100],
            "is_country": "true" if is_country else "false",
            "police": "911",
            "ambulance": "911",
            "fire": "911",
            "non_emergency": fake.numerify("###-###-####")[:75],
            "cyber_police": "",
            "medicare_support": fake.numerify("1-800-###-####")[:75],
            "gas_leak": fake.numerify("1-800-###-####")[:75],
            "electricity_outage": fake.numerify("1-800-###-####")[:75],
            "water_department": "",
            "disaster_recovery": "",
            "flood_help": "",
            "earthquake_info": "",
            "hurricane_info": "",
            "emergency_mgmt": "",
            "environmental_hazards": "",
            "transportation_assistance": "",
            "roadside_assistance": "",
            "highway_patrol": "",
            "suicide": "988",
            "help_women": fake.numerify("1-800-###-####")[:75],
            "child_abuse": fake.numerify("1-800-###-####")[:75],
            "domestic_abuse": fake.numerify("1-800-###-####")[:75],
            "mental_health": "988",
            "elderly_abuse": "",
            "poison_control": "1-800-222-1222",
            "animal_control": "",
            "wildlife_rescue": "",
            "homeless_services": "",
            "food_assistance": "",
        })
    return rows


# ---------------------------------------------------------------------------
# organizations (depends on cat_ids lookup)
# ---------------------------------------------------------------------------


def generate_organizations(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``organizations`` table."""
    cat_ids = ctx.get("cat_ids", ["1"])
    org_types = cfg.ENUM_VALUES["organizations.org_type"]
    sources = cfg.ENUM_VALUES["organizations.source"]
    rows = []
    for idx in range(count):
        org_id = f"{cfg.ORG_ID_PREFIX}{str(idx + 1).zfill(cfg.ORG_ID_ZERO_PAD)}"
        created = _rand_dt(rng)
        rows.append({
            "org_id": org_id,
            "org_name": fake.company()[:125],
            "org_type": _sample(rng, org_types),
            "street": fake.street_address()[:255],
            "city_name": fake.city()[:100],
            "state_code": fake.state_abbr()[:6],
            "zip_code": fake.zipcode()[:10],
            "mission": fake.paragraph(nb_sentences=2),
            "web_url": fake.url()[:255],
            "phone": fake.phone_number()[:20],
            "email": fake.company_email()[:255],
            "size": _sample(rng, ["SMALL", "MEDIUM", "LARGE", "ENTERPRISE"]),
            "rating": str(rng.randint(1, 5)),
            "source": _sample(rng, sources),
            "cat_id": str(_sample(rng, cat_ids)),
            "created_at": _fmt_ts(created),
            "last_updated_at": _fmt_ts(created + timedelta(days=rng.randint(0, 60))),
        })
    return rows


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------


# Weighted user_category distribution:
# Beneficiaries (~50%), Volunteers (~35%), Stewards (~10%), Admins (~4%), SuperAdmins (~1%)
_USER_CAT_WEIGHTS = [50, 35, 10, 4, 1]


def generate_users(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``users`` table.

    Produces a consistent user record per row: first/last/full name are
    derived from the same Faker call so they stay in sync.
    """
    country_ids = ctx.get("country_ids", [1])
    state_ids = ctx.get("state_ids", ["VA"])
    user_status_ids = ctx.get("user_status_ids", [1])
    user_category_ids = ctx.get("user_category_ids", [1, 2, 3, 4, 5])
    genders = cfg.ENUM_VALUES["users.gender"]
    auth_providers = cfg.ENUM_VALUES["users.external_auth_provider"]
    languages = ["en", "es", "hi", "zh", "fr", "ar", "de", "pt"]
    timezones = [
        "America/New_York", "America/Chicago",
        "America/Denver", "America/Los_Angeles",
        "America/Phoenix", "Pacific/Honolulu",
    ]

    # Weighted category sampling
    cat_population = []
    for cat_id, weight in zip(user_category_ids, _USER_CAT_WEIGHTS):
        cat_population.extend([cat_id] * weight)

    rows = []
    for idx in range(count):
        user_id = f"{cfg.USER_ID_PREFIX}{str(idx + 1).zfill(cfg.USER_ID_ZERO_PAD)}"
        first = fake.first_name()
        last = fake.last_name()
        full = f"{first} {last}"
        dob = _rand_date(
            rng,
            date.today() - timedelta(days=365 * 80),
            date.today() - timedelta(days=365 * 18),
        )
        created = _rand_dt(rng)
        rows.append({
            "user_id": user_id,
            "state_id": str(_sample(rng, state_ids))[:50],
            "country_id": str(_sample(rng, country_ids)),
            "user_status_id": str(_sample(rng, user_status_ids)),
            "user_category_id": str(_sample(rng, cat_population)),
            "full_name": full[:255],
            "first_name": first[:255],
            "middle_name": fake.first_name()[:255] if rng.random() < 0.25 else "",
            "last_name": last[:255],
            "primary_email_address": fake.unique.email()[:255],
            "primary_phone_number": fake.phone_number()[:255],
            "addr_ln1": fake.street_address()[:255],
            "addr_ln2": fake.secondary_address()[:255] if rng.random() < 0.30 else "",
            "addr_ln3": "",
            "city_name": fake.city()[:255],
            "zip_code": fake.zipcode()[:255],
            "last_location": f"{fake.city()}, {fake.state_abbr()}"[:255],
            "last_update_date": _fmt_ts(created + timedelta(days=rng.randint(0, 90))),
            "time_zone": _sample(rng, timezones),
            "profile_picture_path": f"/assets/profiles/{user_id}.jpg" if rng.random() < 0.60 else "",
            "gender": _sample(rng, genders),
            "language_1": _sample(rng, languages),
            "language_2": _sample(rng, languages) if rng.random() < 0.40 else "",
            "language_3": _sample(rng, languages) if rng.random() < 0.10 else "",
            "promotion_wizard_stage": str(rng.randint(0, 4)),
            "promotion_wizard_last_update_date": _fmt_ts(created),
            "external_auth_provider": _sample(rng, auth_providers),
            "dob": _fmt_date(dob),
        })
    return rows


# ---------------------------------------------------------------------------
# User child tables
# ---------------------------------------------------------------------------


def generate_user_additional_details(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``user_additional_details`` (subset of users)."""
    user_ids = _pick_subset(ctx["user_ids"], count, rng)
    rows = []
    for idx, uid in enumerate(user_ids):
        rows.append({
            "additional_detail_id": str(idx + 1),
            "user_id": uid,
            "secondary_email_1": fake.email()[:255] if rng.random() < 0.70 else "",
            "secondary_email_2": fake.email()[:255] if rng.random() < 0.20 else "",
            "secondary_phone_1": fake.phone_number()[:255] if rng.random() < 0.60 else "",
            "secondary_phone_2": fake.phone_number()[:255] if rng.random() < 0.15 else "",
        })
    return rows


def generate_user_availability(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``user_availability`` (one row per user/day slot)."""
    user_ids = _pick_subset(ctx["user_ids"], count, rng)
    days = cfg.ENUM_VALUES["user_availability.day_of_week"]
    rows = []
    avail_id = 1
    for uid in user_ids:
        n_days = rng.randint(1, 4)
        for day in rng.sample(days, n_days):
            start = _rand_dt(rng)
            end = start + timedelta(hours=rng.randint(1, 8))
            rows.append({
                "user_availability_id": str(avail_id),
                "user_id": uid,
                "day_of_week": day,
                "start_time": _fmt_ts(start),
                "end_time": _fmt_ts(end),
                "last_update_date": _fmt_ts(end),
            })
            avail_id += 1
    return rows


def generate_user_locations(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``user_locations`` (one per user)."""
    user_ids = _pick_subset(ctx["user_ids"], count, rng)
    rows = []
    for uid in user_ids:
        updated = _rand_dt(rng)
        rows.append({
            "user_id": uid,
            "prev_loc": _wkt_point(rng),
            "curr_loc": _wkt_point(rng),
            "updated_at": _fmt_ts(updated),
        })
    return rows


def generate_user_notification_preferences(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``user_notification_preferences``."""
    user_ids = _pick_subset(ctx["user_ids"], count, rng)
    channel_ids = ctx.get("channel_ids", [1, 2, 3, 4])
    prefs = cfg.ENUM_VALUES["user_notification_preferences.preference"]
    rows = []
    pref_id = 1
    for uid in user_ids:
        for ch_id in channel_ids:
            rows.append({
                "user_notification_preferences_id": str(pref_id),
                "user_id": uid,
                "channel_id": str(ch_id),
                "preference": _sample(rng, prefs),
            })
            pref_id += 1
    return rows


def generate_user_notification_status(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``user_notification_status`` (one per user)."""
    user_ids = _pick_subset(ctx["user_ids"], count, rng)
    rows = []
    for uid in user_ids:
        rows.append({
            "user_id": uid,
            "last_accessed_at": _fmt_ts(_rand_dt(rng)),
        })
    return rows


def generate_user_org_map(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``user_org_map`` association table."""
    user_ids = _pick_subset(ctx["user_ids"], count, rng)
    org_ids = ctx.get("org_ids", [])
    if not org_ids:
        return []
    roles = ["MEMBER", "ADMIN", "CONTACT", "VOLUNTEER", "OBSERVER"]
    rows = []
    seen: set[tuple[str, str]] = set()
    for uid in user_ids:
        org_id = _sample(rng, org_ids)
        if (uid, org_id) in seen:
            continue
        seen.add((uid, org_id))
        created = _rand_dt(rng)
        rows.append({
            "user_id": uid,
            "org_id": org_id,
            "user_role": _sample(rng, roles),
            "created_at": _fmt_ts(created),
            "last_updated_at": _fmt_ts(created + timedelta(days=rng.randint(0, 30))),
        })
    return rows


# ---------------------------------------------------------------------------
# Volunteer tables
# ---------------------------------------------------------------------------

_AVAIL_TIME_WINDOWS = [
    "06:00-09:00", "09:00-12:00",
    "12:00-15:00", "15:00-18:00", "18:00-21:00",
]


def generate_volunteer_applications(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``volunteer_applications``.

    skill_codes is a JSON array of cat_ids; the same IDs are stored in
    ``ctx["vol_app_skills"]`` so that ``generate_user_skills`` can derive
    its rows without re-parsing CSVs.
    """
    user_ids = _pick_subset(ctx["user_ids"], count, rng)
    cat_ids = [c for c in ctx.get("cat_ids", []) if c != "0.0.0.0.0"]
    statuses = cfg.ENUM_VALUES["volunteer_applications.application_status"]
    status_weights = [5, 12, 45, 20, 18]
    days = cfg.ENUM_VALUES["volunteer_details.availability_days"]

    skill_map: dict[str, list[str]] = {}
    rows = []
    for uid in user_ids:
        skills = rng.sample(cat_ids, min(rng.randint(2, 4), len(cat_ids)))
        skill_map[uid] = skills

        is_completed = rng.random() > 0.18
        status = rng.choices(statuses, weights=status_weights, k=1)[0]
        if is_completed and status in {"DRAFT", "IN_PROGRESS"}:
            status = "SUBMITTED"
        if not is_completed and status == "APPROVED":
            status = "UNDER_REVIEW"

        created = _rand_dt(rng)
        terms_ok = rng.random() > 0.03
        terms_at = (created + timedelta(minutes=rng.randint(0, 180))) if terms_ok else None
        path_at = (terms_at or created) + timedelta(minutes=rng.randint(0, 240))
        updated = path_at + timedelta(days=rng.randint(0, 10), hours=rng.randint(0, 12))

        avail_days = rng.sample(days, rng.randint(2, 5))
        avail = {d: rng.sample(_AVAIL_TIME_WINDOWS, rng.randint(1, 2)) for d in avail_days}

        rows.append({
            "user_id": uid,
            "terms_and_conditions": "TRUE" if terms_ok else "FALSE",
            "terms_accepted_at": _fmt_ts(terms_at) if terms_at else "",
            "govt_id_path": f"/mock-storage/kyc/{uid}/govt_id_front.pdf",
            "path_updated_at": _fmt_ts(path_at),
            "skill_codes": _json(skills),
            "availability": _json(avail),
            "current_page": str(rng.randint(1, 5 if not is_completed else 4)),
            "application_status": status,
            "is_completed": "TRUE" if is_completed else "FALSE",
            "created_at": _fmt_ts(created),
            "last_updated_at": _fmt_ts(updated),
        })

    ctx["vol_app_skills"] = skill_map   # stored for user_skills derivation
    return rows


def generate_user_skills(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Derive ``user_skills`` rows from ``ctx['vol_app_skills']``.

    One row per (user, skill_cat_id) pair.  The ``count`` arg is ignored
    because this table is fully derived.
    """
    skill_map: dict[str, list[str]] = ctx.get("vol_app_skills", {})
    rows = []
    for uid, cat_ids_for_user in skill_map.items():
        created = _rand_dt(rng)
        for cat_id in cat_ids_for_user:
            rows.append({
                "user_id": uid,
                "cat_id": cat_id,
                "created_date": _fmt_ts(created),
                "last_update_date": _fmt_ts(created + timedelta(days=rng.randint(0, 30))),
            })
    return rows


def generate_volunteer_details(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``volunteer_details``."""
    user_ids = _pick_subset(ctx["user_ids"], count, rng)
    days = cfg.ENUM_VALUES["volunteer_details.availability_days"]
    rows = []
    for uid in user_ids:
        created = _rand_dt(rng)
        terms_at = created - timedelta(days=rng.randint(1, 45))
        updated = created + timedelta(days=rng.randint(0, 60))
        path1_at = created + timedelta(days=rng.randint(0, 10))
        has_back = rng.random() < 0.65
        path2_at = path1_at + timedelta(days=rng.randint(0, 5)) if has_back else None

        sel_days = sorted(rng.sample(days, rng.randint(2, 6)), key=days.index)
        day_times = {d: rng.sample(_AVAIL_TIME_WINDOWS, rng.randint(1, 2)) for d in sel_days}

        rows.append({
            "user_id": uid,
            "terms_and_conditions": "true",
            "terms_accepted_at": _fmt_ts(terms_at),
            "govt_id_path1": f"/mock-storage/kyc/{uid}/govt_id_front_{rng.randint(1000,9999)}.pdf",
            "govt_id_path2": (f"/mock-storage/kyc/{uid}/govt_id_back_{rng.randint(1000,9999)}.pdf"
                              if has_back else ""),
            "path1_updated_at": _fmt_ts(path1_at),
            "path2_updated_at": _fmt_ts(path2_at) if path2_at else "",
            "availability_days": _json(sel_days),
            "availability_times": _json(day_times),
            "created_at": _fmt_ts(created),
            "last_updated_at": _fmt_ts(updated),
        })
    return rows


def generate_volunteer_locations(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``volunteer_locations`` (one per volunteer user)."""
    vol_ids = ctx.get("volunteer_detail_ids") or _pick_subset(ctx["user_ids"], count, rng)
    rows = []
    for uid in vol_ids:
        rows.append({
            "user_id": uid,
            "prev_loc": _wkt_point(rng),
            "curr_loc": _wkt_point(rng),
            "updated_at": _fmt_ts(_rand_dt(rng)),
        })
    return rows


# ---------------------------------------------------------------------------
# fraud_requests / meetings / meeting_participants
# ---------------------------------------------------------------------------


def generate_fraud_requests(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``fraud_requests`` table."""
    user_ids = _pick_subset(ctx["user_ids"], count, rng)
    rows = []
    for idx, uid in enumerate(user_ids):
        rows.append({
            "fraud_request_id": str(idx + 1),
            "user_id": uid,
            "request_datetime": _fmt_ts(_rand_dt(rng)),
            "reason": fake.sentence()[:255],
        })
    return rows


def generate_meetings(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``meetings`` table."""
    user_ids = ctx.get("user_ids", [])
    rows = []
    for idx in range(count):
        start = _rand_dt(rng)
        end = start + timedelta(hours=rng.randint(1, 3))
        rows.append({
            "meeting_id": str(idx + 1),
            "meeting_date": _fmt_date(start.date()),
            "start_time": _fmt_ts(start),
            "end_time": _fmt_ts(end),
            "cohost_id": _sample(rng, user_ids) if user_ids else "",
        })
    return rows


def generate_meeting_participants(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``meeting_participants`` (N participants per meeting)."""
    meeting_ids = ctx.get("meeting_ids", [])
    user_ids = ctx.get("user_ids", [])
    if not meeting_ids or not user_ids:
        return []

    per_meeting = ctx.get("meeting_participants_per_meeting", 4)
    rows = []
    seen: set[tuple[str, str]] = set()
    for mid in meeting_ids:
        n = rng.randint(max(1, per_meeting - 2), per_meeting + 2)
        participants = rng.sample(user_ids, min(n, len(user_ids)))
        for uid in participants:
            if (str(mid), uid) in seen:
                continue
            seen.add((str(mid), uid))
            rows.append({
                "meeting_id": str(mid),
                "participant_id": uid,
            })
    return rows


# ---------------------------------------------------------------------------
# request
# ---------------------------------------------------------------------------


# req_status_ids that indicate the request is complete/post-service
_CLOSED_STATUSES = {3, 4, 5, 6, 7}   # RESOLVED, CANCELLED, DELETED, RATED_*


def generate_request(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the main ``request`` table."""
    user_ids = ctx.get("user_ids", [])
    cat_ids = [c for c in ctx.get("cat_ids", []) if c != "0.0.0.0.0"]
    req_for_ids = ctx.get("req_for_ids", [0, 1])
    req_islead_ids = ctx.get("req_islead_ids", [0, 1])
    req_type_ids = ctx.get("req_type_ids", [0, 1])
    req_priority_ids = ctx.get("req_priority_ids", [0, 1, 2, 3])
    req_status_ids = ctx.get("req_status_ids", [0, 1, 2, 3])

    rows = []
    for idx in range(count):
        req_id = f"{cfg.REQUEST_ID_PREFIX}{str(idx + 1).zfill(cfg.REQUEST_ID_ZERO_PAD)}"
        status_id = _sample(rng, req_status_ids)
        submission = _rand_dt(rng)
        serviced = None
        if int(status_id) in _CLOSED_STATUSES:
            serviced = submission + timedelta(days=rng.randint(1, 30))
        rows.append({
            "req_id": req_id,
            "req_user_id": _sample(rng, user_ids) if user_ids else "",
            "req_for_id": str(_sample(rng, req_for_ids)),
            "req_islead_id": str(_sample(rng, req_islead_ids)),
            "req_cat_id": str(_sample(rng, cat_ids)),
            "req_type_id": str(_sample(rng, req_type_ids)),
            "req_priority_id": str(_sample(rng, req_priority_ids)),
            "req_status_id": str(status_id),
            "req_loc": f"{fake.city()}, {fake.state_abbr()}"[:125],
            "iscalamity": _weighted_bool(rng, 0.05),
            "req_subj": fake.sentence(nb_words=6)[:125],
            "req_desc": fake.sentence(nb_words=12)[:255],
            "req_doc_link": fake.url() if rng.random() < 0.20 else "",
            "audio_req_desc": "",
            "submission_date": _fmt_ts(submission),
            "serviced_date": _fmt_ts(serviced) if serviced else "",
            "last_update_date": _fmt_ts(
                (serviced or submission) + timedelta(days=rng.randint(0, 5))
            ),
            "to_public": _weighted_bool(rng, 0.75),
        })
    return rows


# ---------------------------------------------------------------------------
# Request child tables
# ---------------------------------------------------------------------------


def generate_request_comments(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``request_comments``."""
    request_ids = ctx.get("request_ids", [])
    user_ids = ctx.get("user_ids", [])
    if not request_ids:
        return []
    rows = []
    for idx in range(count):
        created = _rand_dt(rng)
        rows.append({
            "comment_id": str(idx + 1),
            "req_id": _sample(rng, request_ids),
            "commenter_id": _sample(rng, user_ids) if user_ids else "",
            "comment_desc": fake.paragraph(nb_sentences=2),
            "created_at": _fmt_ts(created),
            "last_updated_at": _fmt_ts(created + timedelta(minutes=rng.randint(0, 120))),
            "isdeleted": _weighted_bool(rng, 0.04),
        })
    return rows


def generate_request_guest_details(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``request_guest_details`` (one per guest-type request)."""
    request_ids = ctx.get("request_ids", [])
    if not request_ids:
        return []
    guest_req_ids = _pick_subset(request_ids, count, rng)
    langs = ["English", "Spanish", "Hindi", "Mandarin", "French", "Arabic"]
    genders = cfg.ENUM_VALUES["request_guest_details.req_gender"]
    rows = []
    for req_id in guest_req_ids:
        rows.append({
            "req_id": req_id,
            "req_fname": fake.first_name()[:100],
            "req_lname": fake.last_name()[:100],
            "req_email": fake.email()[:100],
            "req_phone": fake.phone_number()[:20],
            "req_age": str(rng.randint(18, 85)),
            "req_gender": _sample(rng, genders),
            "req_pref_lang": _sample(rng, langs),
        })
    return rows


def generate_req_add_info(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``req_add_info`` using category-aware field metadata.

    For each selected request, looks up its category, finds the matching
    fields from ``req_add_info_metadata``, and generates one row per field.
    ``count`` is treated as a target total, not a strict limit.
    """
    request_data: list[dict] = ctx.get("request_data", [])
    metadata_by_cat: dict[str, list[dict]] = ctx.get("req_add_info_metadata_by_cat", {})
    items_by_field: dict[str, list[str]] = ctx.get("list_items_by_field", {})

    if not request_data or not metadata_by_cat:
        return []

    # Sample a subset of requests up to target count (spread across them)
    sample_size = min(count, len(request_data))
    sampled = rng.sample(request_data, sample_size)

    rows = []
    for req_row in sampled:
        req_id = req_row.get("req_id", "")
        cat_id = req_row.get("req_cat_id", "")
        fields = metadata_by_cat.get(cat_id, [])
        for field in fields:
            field_id = field.get("field_id", "")
            field_type = field.get("field_type", "textbox")
            field_name_key = field.get("field_name_key", "")
            # Resolve a plausible field_value
            if field_type == "list":
                options = items_by_field.get(field_id, [])
                value = _sample(rng, options) if options else fake.word()
            elif field_type == "integer":
                value = str(rng.randint(1, 20))
            elif field_type in ("date&time", "time"):
                value = _fmt_ts(_rand_dt(rng))
            elif field_type == "checkbox":
                value = _weighted_bool(rng, 0.60)
            elif field_type == "currency":
                value = str(round(rng.uniform(100, 5000), 2))
            else:   # textbox or unknown
                value = fake.sentence()
            rows.append({
                "request_id": req_id,
                "cat_id": cat_id,
                "field_name_key": field_name_key,
                "field_value": value,
            })
    return rows


# ---------------------------------------------------------------------------
# notifications
# ---------------------------------------------------------------------------


def generate_notifications(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for the ``notifications`` table."""
    user_ids = ctx.get("user_ids", [])
    type_ids = ctx.get("notification_type_ids", [1])
    channel_ids = ctx.get("channel_ids", [1, 2])
    statuses = cfg.ENUM_VALUES["notifications.status"]
    rows = []
    for idx in range(count):
        created = _rand_dt(rng)
        rows.append({
            "notification_id": str(idx + 1),
            "user_id": _sample(rng, user_ids) if user_ids else "",
            "type_id": str(_sample(rng, type_ids)),
            "channel_id": str(_sample(rng, channel_ids)),
            "message": fake.sentence()[:255],
            "status": _sample(rng, statuses),
            "created_at": _fmt_ts(created),
            "last_update_date": _fmt_ts(created + timedelta(minutes=rng.randint(0, 60))),
        })
    return rows


# ---------------------------------------------------------------------------
# volunteer_rating / volunteers_assigned
# ---------------------------------------------------------------------------


def generate_volunteer_rating(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``volunteer_rating``."""
    user_ids = ctx.get("user_ids", [])
    request_ids = ctx.get("request_ids", [])
    if not request_ids:
        return []
    rows = []
    seen: set[tuple[str, str]] = set()
    attempts = 0
    while len(rows) < count and attempts < count * 3:
        attempts += 1
        uid = _sample(rng, user_ids)
        req_id = _sample(rng, request_ids)
        if (uid, req_id) in seen:
            continue
        seen.add((uid, req_id))
        rows.append({
            "volunteer_rating_id": str(len(rows) + 1),
            "user_id": uid,
            "request_id": req_id,
            "rating": str(rng.randint(1, 5)),
            "feedback": fake.paragraph(nb_sentences=1),
            "last_update_date": _fmt_ts(_rand_dt(rng)),
        })
    return rows


def generate_volunteers_assigned(ctx, rng, fake, count) -> list[dict[str, str]]:
    """Generate rows for ``volunteers_assigned``."""
    request_ids = ctx.get("request_ids", [])
    user_ids = ctx.get("user_ids", [])
    if not request_ids or not user_ids:
        return []
    vtypes = cfg.ENUM_VALUES["volunteers_assigned.volunteer_type"]
    rows = []
    seen: set[tuple[str, str]] = set()
    max_attempts = count * 5
    attempts = 0
    assigned_id = 1
    while len(rows) < count and attempts < max_attempts:
        attempts += 1
        req_id = _sample(rng, request_ids)
        vol_id = _sample(rng, user_ids)
        if (req_id, vol_id) in seen:
            continue
        seen.add((req_id, vol_id))
        rows.append({
            "volunteers_assigned_id": str(assigned_id),
            "request_id": req_id,
            "volunteer_id": vol_id,
            "volunteer_type": _sample(rng, vtypes),
            "last_update_date": _fmt_ts(_rand_dt(rng)),
        })
        assigned_id += 1
    return rows


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------


def _pick_subset(pool: list, n: int, rng: random.Random) -> list:
    """Return up to ``n`` unique items from ``pool`` in shuffled order."""
    n = min(n, len(pool))
    if n <= 0:
        return []
    return rng.sample(pool, n)


# ---------------------------------------------------------------------------
# Dispatch table  —  maps every generated table name to its function
# ---------------------------------------------------------------------------

GENERATORS: dict = {
    # Independent / lookup-adjacent
    "action":                       generate_action,
    "identity_type":                generate_identity_type,
    "sla":                          generate_sla,
    "news_snippets":                generate_news_snippets,
    "user_signoff":                 generate_user_signoff,
    "volunteer_organizations":      generate_volunteer_organizations,
    # Geography
    "city":                         generate_city,
    "emergency_numbers":            generate_emergency_numbers,
    # Core entities
    "organizations":                generate_organizations,
    "users":                        generate_users,
    # User children
    "user_additional_details":      generate_user_additional_details,
    "user_availability":            generate_user_availability,
    "user_locations":               generate_user_locations,
    "user_notification_preferences":generate_user_notification_preferences,
    "user_notification_status":     generate_user_notification_status,
    "user_org_map":                 generate_user_org_map,
    # Volunteer tables
    "volunteer_applications":       generate_volunteer_applications,
    "user_skills":                  generate_user_skills,
    "volunteer_details":            generate_volunteer_details,
    "volunteer_locations":          generate_volunteer_locations,
    # Misc user-dependent
    "fraud_requests":               generate_fraud_requests,
    "meetings":                     generate_meetings,
    "meeting_participants":         generate_meeting_participants,
    # Notifications
    "notifications":                generate_notifications,
    # Requests
    "request":                      generate_request,
    "request_comments":             generate_request_comments,
    "request_guest_details":        generate_request_guest_details,
    "req_add_info":                 generate_req_add_info,
    # Ratings / assignments
    "volunteer_rating":             generate_volunteer_rating,
    "volunteers_assigned":          generate_volunteers_assigned,
}
