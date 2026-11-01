#!/usr/bin/env python3
"""
Mock data generator for the Saayam request archival pipeline (issue #573).

Builds one CSV per table for `requests` and every table it references, using
only saayam_schema.sql. Nothing is read from, or copied out of, any database.

    python3 generate.py                          # seed 573, 500 requests -> ./output
    python3 generate.py --seed 7 --requests 800 --out /tmp/mock

Same seed and arguments -> byte-identical files. Standard library only.
"""

import argparse
import os
import random
import sys
from datetime import datetime, timedelta

# =================================================================== settings

DEFAULT_SEED = 573
DEFAULT_REQUESTS = 500
DEFAULT_USERS = 150

# Fixed range, so output never depends on the clock.
TIME_START = datetime(2025, 11, 1, 0, 0, 0)
TIME_END = datetime(2026, 10, 24, 23, 59, 59)
REF_TS = "2025-10-01 00:00:00.000000"  # last_updated_at for lookup/category rows

# Case 2: values shared, to the microsecond, by several rows each.
SHARED_TS = [
    datetime(2026, 9, 1, 0, 0, 0, 0),          # exact midnight, a likely window edge
    datetime(2026, 7, 14, 9, 30, 15, 482913),  # arbitrary microsecond value
]
ROWS_PER_SHARED_TS = 4

# Case 1 / 10: proportions from dev (221 requests, 24 Oct 2026).
DEV_TOTAL, DEV_ISLEAD_YES, DEV_LEAD_SET, DEV_BENEFICIARY_NULL = 221, 9, 3, 8

# Column limits from saayam_schema.sql (characters, not bytes).
LIMITS = {
    "req_subj": 125, "req_desc": 255, "audio_req_desc": 255,
    "cat_id": 50, "cat_name": 100, "cat_desc": 150,
    "req_for": 25, "req_for_desc": 125,
    "req_islead": 15, "req_islead_desc": 100,
    "req_type": 25, "req_type_desc": 125,
    "req_priority": 25, "req_priority_desc": 125,
    "req_status": 25, "req_status_desc": 125,
}

# Mock-only bucket name; never a real one.
BUCKET = "s3://saayam-mock-bucket/requests"

# ======================================================================= rng


class Rng:
    """Everything goes through random.Random.random(), the one method Python
    guarantees gives the same sequence for a seed across versions."""

    def __init__(self, seed):
        self._r = random.Random(seed)

    def random(self):
        return self._r.random()

    def int(self, lo, hi):
        return lo + int(self._r.random() * (hi - lo + 1))

    def choice(self, seq):
        return seq[self.int(0, len(seq) - 1)]

    def weighted(self, pairs):
        x = self._r.random() * sum(w for _, w in pairs)
        for value, w in pairs:
            x -= w
            if x < 0:
                return value
        return pairs[-1][0]

    def shuffle(self, lst):
        for i in range(len(lst) - 1, 0, -1):
            j = self.int(0, i)
            lst[i], lst[j] = lst[j], lst[i]


# =================================================================== helpers


def fill_to(text, n):
    """Repeat text and cut to exactly n characters, never ending in a space."""
    out = text
    while len(out) < n:
        out += text
    out = out[:n]
    return out[:-1] + "." if out.endswith(" ") else out


def user_id(n):
    d = f"{n:017d}"  # SID-00-000-000-000-000-026
    return f"SID-{d[0:2]}-{d[2:5]}-{d[5:8]}-{d[8:11]}-{d[11:14]}-{d[14:17]}"


def req_id(n):
    d = f"{n:013d}"  # REQ-000-000-000-0000
    return f"REQ-{d[0:3]}-{d[3:6]}-{d[6:9]}-{d[9:13]}"


def ts_us(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def ts_s(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def point(rng):
    """EWKT point around Hampton Roads, VA. PostGIS accepts this as text input."""
    lon = -76.30 + (rng.random() - 0.5) * 0.6
    lat = 36.85 + (rng.random() - 0.5) * 0.4
    return f"SRID=4326;POINT({lon:.6f} {lat:.6f})"


# ============================================================ lookup tables
# Real IDs and values from the schema comments. Descriptions are invented.
# Every desc column holds both NULL and '' (case 7); two-row tables therefore
# hold only those two. Where room allows, one desc fills its limit (case 8).

LOOKUPS = {
    "request_for": {
        "cols": ["req_for_id", "req_for", "req_for_desc", "last_updated_at"],
        "rows": [(0, "SELF", None), (1, "OTHER", "")],
    },
    "request_isleadvol": {
        "cols": ["req_islead_id", "req_islead", "req_islead_desc", "last_updated_at"],
        "rows": [(0, "NO", ""), (1, "YES", None)],
    },
    "request_types": {
        "cols": ["req_type_id", "req_type", "req_type_desc", "last_updated_at"],
        "rows": [(0, "IN_PERSON", None), (1, "REMOTE", "")],
    },
    "request_priorities": {
        "cols": ["req_priority_id", "req_priority", "req_priority_desc", "last_updated_at"],
        "rows": [
            (0, "LOW", "Can wait a week or more"),
            (1, "MEDIUM", ""),
            (2, "HIGH", None),
            (3, "CRITICAL", fill_to("Needs attention the same day, escalate if no volunteer responds. ", 125)),
        ],
    },
    "request_statuses": {
        "cols": ["req_status_id", "req_status", "req_status_desc", "last_updated_at"],
        "rows": [
            (0, "CREATED", "Submitted, not yet picked up"),
            (1, "MATCHING_VOLUNTEER", "Looking for a volunteer"),
            (2, "IN_PROGRESS", "A volunteer is working on it"),
            (3, "RESOLVED", "Help was delivered"),
            (4, "CANCELLED", fill_to("Withdrawn by the requester before help was delivered, no further action. ", 125)),
            (5, "DELETED", ""),
            (6, "RATED_BY_REQUESTER", "Requester left a rating"),
            (7, "RATED_BY_VOLUNTEER", "Volunteer left a rating"),
            (8, "VOLUNTEER_NOT_FOUND", None),
        ],
    },
}

# Request distributions. Values that no dev request uses get weight 0 here and
# are forced in afterwards (case 9).
STATUS_WEIGHTS = [(0, 30), (1, 25), (2, 15), (3, 0), (4, 0), (5, 6), (6, 8), (7, 6), (8, 0)]
PRIORITY_WEIGHTS = [(0, 30), (1, 45), (2, 25), (3, 0)]
TYPE_WEIGHTS = [(0, 70), (1, 30)]
FOR_WEIGHTS = [(0, 80), (1, 20)]
SERVICED_STATUSES = {3, 6, 7}
DELETED = 5

# ============================================================ category tree
# Invented, in the live tree's format: dotted-path IDs, up to three levels,
# UPPER_SNAKE names, NAME_DESC descriptions, and a 0.0.0.0.0 catch-all.
# Deliberate traps: a parent with 12 children (3.1.10 sorts before 3.1.2 as
# text), one row out of order (3.1.12 last), parentheses in a name, and one
# row at the name/desc length limits.

GENERAL_CAT = "0.0.0.0.0"

CATEGORIES = [
    (GENERAL_CAT, "GENERAL_HELP"),
    ("1", "TRANSPORT_AND_ERRANDS"),
    ("1.1", "RIDE_TO_APPOINTMENT"),
    ("1.2", "AIRPORT_PICKUP_OR_DROP"),
    ("1.3", "PRESCRIPTION_PICKUP"),
    ("1.4", "POST_OFFICE_AND_BANK_ERRANDS"),
    ("1.5", "OTHER_TRANSPORT_HELP"),
    ("2", "MEALS_AND_PANTRY"),
    ("2.1", "PANTRY_RESTOCK"),
    ("2.2", "HOT_MEAL_DROPOFF"),
    ("2.3", "MEAL_PLANNING"),
    ("2.3.1", "LOW_SUGAR_MEAL_PLANNING"),
    ("2.3.2", "BUDGET_MEAL_PLANNING"),
    ("2.3.3", "VEGETARIAN_MEAL_PLANNING"),
    ("2.4", "COMMUNITY_KITCHEN_VOLUNTEERING"),
    ("3", "HOME_AND_REPAIRS"),
    ("3.1", "MINOR_REPAIRS"),
    ("3.1.1", "LEAKY_FAUCET"),
    ("3.1.2", "DOOR_AND_LOCK_FIX"),
    ("3.1.3", "LIGHT_FIXTURE_SWAP"),
    ("3.1.4", "SHELF_MOUNTING"),
    ("3.1.5", "FURNITURE_ASSEMBLY"),
    ("3.1.6", "WINDOW_SCREEN_REPAIR"),
    ("3.1.7", "GUTTER_CLEANING"),
    ("3.1.8", "FENCE_REPAIR"),
    ("3.1.9", "DRYWALL_PATCH"),
    ("3.1.10", "APPLIANCE_TROUBLESHOOTING"),
    ("3.1.11", "SMOKE_DETECTOR_CHECK"),
    ("3.2", "MOVING_HELP"),
    ("3.3", "YARD_WORK"),
    ("3.4", "HOME_SAFETY_CHECK"),
    ("3.5", "TEMPORARY_STAY_REFERRAL"),
    ("4", "LEARNING_AND_JOBS"),
    ("4.1", "RESUME_REVIEW"),
    ("4.2", "INTERVIEW_PRACTICE"),
    ("4.3", "HOMEWORK_HELP"),
    ("4.3.1", "ALGEBRA"),
    ("4.3.2", "READING_AND_WRITING"),
    ("4.3.3", "BIOLOGY_AND_CHEMISTRY"),
    ("4.3.4", "CODING_BASICS"),
    ("4.4", "LANGUAGE_PRACTICE(ESL_AND_OTHERS)"),
    ("4.5", "FINANCIAL_LITERACY_BASICS"),
    ("5", "HEALTH_AND_CARE"),
    ("5.1", "APPOINTMENT_COMPANION"),
    ("5.2", "PHARMACY_COORDINATION"),
    ("5.3", "MOBILITY_AID_LOAN"),
    ("5.4", "CAREGIVER_RELIEF"),
    ("5.5", "WELLNESS_CHECK_IN_CALLS"),
    ("6", "TECH_AND_PAPERWORK"),
    ("6.1", "PHONE_AND_TABLET_SETUP"),
    ("6.2", "VIDEO_CALL_HELP"),
    ("6.3", "ONLINE_FORMS_AND_PORTALS"),
    ("6.4", "TRANSLATION_HELP"),
    ("6.5", "SCAM_AWARENESS"),
    ("7", "COMMUNITY_AND_COMPANIONSHIP"),
    ("7.1", "FRIENDLY_VISITS"),
    ("7.2", "PET_CARE"),
    ("7.3", "EVENT_SETUP_VOLUNTEERS"),
    ("7.4", "SHORT_TERM_CHILD_CARE"),
    ("7.5", fill_to("NEIGHBOURHOOD_SKILL_SHARE_AND_TOOL_LIBRARY_", 100)),
    ("3.1.12", "OTHER_MINOR_REPAIR"),  # out of order on purpose
]
MAX_LEN_CAT = "7.5"


def build_categories():
    rows = []
    for cat_id, name in CATEGORIES:
        desc = name + "_DESC"
        if cat_id == MAX_LEN_CAT:
            desc = fill_to("NEIGHBOURHOOD_SKILL_SHARE_AND_TOOL_LIBRARY_DESC_", 150)
        rows.append({"cat_id": cat_id, "cat_name": name, "cat_desc": desc, "last_updated_at": REF_TS})
    return rows


def build_category_map(categories):
    """One row per child, pointing at its parent. Top-level categories and the
    catch-all have no parent and so get no row."""
    rows = []
    for c in categories:
        cid = c["cat_id"]
        if cid == GENERAL_CAT or "." not in cid:
            continue
        rows.append({"parent_id": cid.rsplit(".", 1)[0], "child_id": cid, "last_updated_at": REF_TS})
    return rows


# ===================================================================== text
# Ordinary rows contain no personal details. All special text is below.

TEMPLATES = {
    "0": [("General help needed", "Not sure which category fits; would like to talk through options."),
          ("Need a hand this week", "Short task, about an hour. Flexible on timing.")],
    "1": [("Ride to a medical appointment", "Appointment is mid-morning; needs a ride there and back."),
          ("Airport pickup", "Arriving on an evening flight with two bags."),
          ("Pick up a prescription", "Pharmacy has it ready but I can't drive this week."),
          ("Errands at the post office", "Two packages to mail and a form to drop off.")],
    "2": [("Groceries for the week", "Small list, mostly staples. Can pay on delivery."),
          ("Hot meal drop-off", "Recovering after a procedure and can't cook for a few days."),
          ("Help planning cheap meals", "Looking for a simple weekly plan on a tight budget.")],
    "3": [("Leaky kitchen faucet", "Drips constantly; I have the replacement washer."),
          ("Assemble a bookshelf", "Flat-pack shelf, tools provided."),
          ("Moving boxes to a new apartment", "About fifteen boxes, ground floor to ground floor."),
          ("Yard cleanup", "Leaves and a few fallen branches after the storm.")],
    "4": [("Resume review", "Applying for warehouse and retail roles; want feedback."),
          ("Algebra homework help", "High school student stuck on quadratic equations."),
          ("English conversation practice", "Weekly half-hour practice, online is fine.")],
    "5": [("Company for a clinic visit", "Would like someone to come along and take notes."),
          ("Borrow a walker", "Need one for about two weeks."),
          ("Weekly check-in call", "Lives alone; a short call twice a week would help.")],
    "6": [("Set up a new phone", "Need contacts moved over and video calling set up."),
          ("Help with an online form", "The benefits portal keeps timing out."),
          ("Translate a letter", "One-page letter from the school, need it explained.")],
    "7": [("Friendly visit", "Would enjoy company for an afternoon."),
          ("Walk my dog", "Small dog, two short walks a day for a week."),
          ("Volunteers for a block event", "Need four people to set up tables and chairs.")],
}

DELETION_REASONS = ["Duplicate request", "Created by mistake", "No longer needed",
                    "Requester asked to remove it"]

# Case 4: CSV-hostile characters.
TRICKY_TEXT = [
    ('Moving help: couch, bed, and "a few" boxes',
     'We need two people.\nThe couch is "huge", heavy, and won\'t fit the elevator.\nParking is behind the building, by the gate.'),
    ("Line endings, commas, quotes",
     'Line one\r\nLine two, with a comma\r\n"A whole quoted line"'),
    ('Ends with a newline, "quoted"',
     'Trailing newline after this sentence, which some parsers drop.\n'),
]

# Case 5: non-ASCII. Spanish first, since real requests include it.
SPANISH_TEXT = [
    ("Ayuda con la compra semanal", "Necesito ayuda para traer la compra; vivo en un segundo piso sin ascensor."),
    ("Transporte a la clínica", "Mi madre tiene cita el miércoles por la mañana y no tenemos coche."),
    ("Reparar una puerta", "La puerta del baño no cierra bien. Tengo las herramientas."),
    ("Clases de inglés", "Busco práctica de conversación en inglés, una vez por semana."),
    ("Mudanza pequeña", "Unas diez cajas y un sofá. ¿Alguien puede ayudar el sábado?"),
]
SPANISH_ROWS = 10
OTHER_SCRIPT_TEXT = [
    ("Cần giúp đưa mẹ đi khám", "Mẹ tôi cần người đưa đi khám bệnh vào thứ Năm."),
    ("किराने के सामान में मदद", "मुझे किराने का सामान लाने में मदद चाहिए।"),
    ("帮忙搬家具", "需要有人帮忙搬一张沙发和几个箱子。"),
    ("Dog walking 🐕", "Two short walks a day — thank you! 🙏"),
]

# Case 6: planted personal details. All fictional: 555-01xx numbers, the UK
# 020 7946 0xxx drama range, example.* domains, invented streets.
# Each item: {column: (text, "pii;types")}, optional "status" requirement.
PII_ITEMS = [
    {"req_desc": ("Please call my son Rahul Venkataraman at (757) 555-0143 before pickup. Address is 2218 Larkspur Ct, Apt 4B, Chesapeake VA 23320.",
                  "name;phone;address")},
    {"req_desc": ("Contact me at maria.lopez.test@example.com or 757-555-0178 if the time changes.", "email;phone")},
    {"req_desc": ("Por favor llamen a José Hernández al +1 757 555 0121. Vivimos en 415 Calle Robles, Norfolk.",
                  "name;phone;address")},
    {"req_desc": ("My number is four eight zero, five five five, zero one nine two. Ask for Mrs. Okonkwo.",
                  "phone_as_words;name")},
    {"req_desc": ("Text 757.555.0166, gate code is on the note. Name on the door: Nguyễn Thị Lan.", "phone;name")},
    {"req_desc": ("Email me: priya [at] example [dot] org, I'm Priya Raghunathan.", "email_obfuscated;name")},
    {"req_desc": ("seven five seven, five five five, oh one three three. Call after 6pm, ask for Dmitri Volkov.",
                  "phone_as_words;name")},
    {"req_subj": ("Help for Olusegun Adeyemi on Elm St", "name;address"),
     "req_desc": ("He lives at 87 Elm Street, Suffolk, VA. Phone 7575550109.", "address;phone")},
    {"deletion_reason": ("Duplicate of request made by Sun-hee Park (sunhee.park@example.net)", "name;email"),
     "status": DELETED},
    {"audio_req_desc": ("Transcript: hi this is Fatima Al-Sayed, my number is (804) 555-0117", "name;phone")},
    {"req_desc": ("Family abroad can be reached at +44 20 7946 0321 (my brother, Seán Ó Briain).", "phone;name")},
    {"req_desc": ("Mail the forms to PO Box 3381, Virginia Beach, VA 23454, attn: Zoë Müller.", "address;name")},
    {"req_desc": ("Mi número es siete cinco siete, cinco cinco cinco, cero uno cinco cuatro.", "phone_as_words")},
]

# Case 8: values at each request text column's limit, ASCII and multi-byte.
MAX_LEN_TEXT = [
    ("req_subj", "Help moving furniture and boxes up three flights of stairs this weekend "),
    ("req_subj", "Ayuda para mudanza: sofá, colchón y cajas pequeñas, por favor "),
    ("req_desc", "Need two volunteers for a half-day move; the building has no elevator and parking is limited. "),
    ("req_desc", "Necesito ayuda urgente con la mudanza; el edificio no tiene ascensor y el señor García está solo. "),
    ("audio_req_desc", "Transcript of voice note describing a request for help with groceries and a ride to the pharmacy. "),
]

# ================================================================= requests

REQUEST_COLS = [
    "req_id", "creator_id", "beneficiary_id", "lead_volunteer_id",
    "req_cat_id", "req_for_id", "req_islead_id", "req_type_id",
    "req_priority_id", "req_status_id", "req_subj", "req_desc",
    "req_doc_link", "audio_req_desc", "deletion_reason", "req_loc",
    "created_loc", "iscalamity", "to_public", "submission_date",
    "serviced_date", "last_updated_at",
]

CASE_NAMES = {
    1: "Skewed nulls in nullable references",
    2: "Rows sharing one last_updated_at",
    3: "last_updated_at earlier than submission_date",
    4: "Embedded newlines, commas and double quotes",
    5: "Non-ASCII text",
    6: "Planted personal details",
    7: "Empty string as distinct from NULL",
    8: "Value at column maximum length",
    9: "Lookup or category value forced into use",
    10: "req_islead_id = 1 with NULL lead_volunteer_id",
    11: "Reference to a row that does not exist (fixture file)",
}


class Pool:
    """Shuffled row indexes handed out once each, so special cases never overlap."""

    def __init__(self, rng, n):
        self.free = list(range(n))
        rng.shuffle(self.free)

    def take(self, k, where=None):
        picked = [i for i in self.free if where is None or where(i)][:k]
        if len(picked) < k:
            raise SystemExit(f"Not enough rows left for a special case (wanted {k}).")
        for i in picked:
            self.free.remove(i)
        return picked


def other_user(rng, users, not_this):
    while True:
        u = rng.choice(users)
        if u != not_this:
            return u


def build_requests(rng, n, users, categories):
    cat_ids = [c["cat_id"] for c in categories]
    cat_weights = [(c, 15 if c == GENERAL_CAT else 1) for c in cat_ids]
    sub_span = int((TIME_END - timedelta(days=30) - TIME_START).total_seconds())

    rows, cases, pii = [], [], []

    def mark(i, case, note):
        cases.append({"req_id": rows[i]["req_id"], "case_number": case,
                      "case_name": CASE_NAMES[case], "note": note})

    # --- base rows
    for k in range(1, n + 1):
        sub = TIME_START + timedelta(seconds=rng.int(0, sub_span))
        rows.append({
            "req_id": req_id(k),
            "creator_id": rng.choice(users),
            "beneficiary_id": None,
            "lead_volunteer_id": None,
            "req_cat_id": rng.weighted(cat_weights),
            "req_for_id": rng.weighted(FOR_WEIGHTS),
            "req_islead_id": 0,
            "req_type_id": rng.weighted(TYPE_WEIGHTS),
            "req_priority_id": rng.weighted(PRIORITY_WEIGHTS),
            "req_status_id": rng.weighted(STATUS_WEIGHTS),
            "req_subj": None, "req_desc": None,
            "req_doc_link": None, "audio_req_desc": None, "deletion_reason": None,
            "req_loc": None, "created_loc": None,
            "iscalamity": rng.weighted([(True, 5), (False, 75), (None, 20)]),
            "to_public": rng.weighted([(True, 30), (False, 68), (None, 2)]),
            "_sub": sub,
            "_upd": sub + timedelta(microseconds=rng.int(0, 30 * 86400 * 10**6)),
            "_beneficiary_null": False,
        })

    pool = Pool(rng, n)

    # --- cases 1 and 10: lead volunteer flag vs. value, skewed like dev
    flagged = pool.take(round(n * DEV_ISLEAD_YES / DEV_TOTAL))
    with_lead = round(n * DEV_LEAD_SET / DEV_TOTAL)
    for j, i in enumerate(flagged):
        rows[i]["req_islead_id"] = 1
        if j < with_lead:
            rows[i]["lead_volunteer_id"] = other_user(rng, users, rows[i]["creator_id"])
            mark(i, 1, "one of the few rows with a lead_volunteer_id")
        else:
            mark(i, 10, "flagged as having a lead volunteer, none recorded")

    for i in pool.take(round(n * DEV_BENEFICIARY_NULL / DEV_TOTAL)):
        rows[i]["_beneficiary_null"] = True
        mark(i, 1, "beneficiary_id is NULL")

    # --- case 9: every lookup value and category used at least once
    forced = [("req_status_id", "request_statuses", 2), ("req_priority_id", "request_priorities", 2),
              ("req_type_id", "request_types", 1), ("req_for_id", "request_for", 1)]
    for col, table, minimum in forced:
        for value, _label, _desc in LOOKUPS[table]["rows"]:
            have = sum(1 for r in rows if r[col] == value)
            if have < minimum:
                for i in pool.take(minimum - have):
                    rows[i][col] = value
                    mark(i, 9, f"{col} = {value} ({_label})")
    for cid in cat_ids:
        if not any(r["req_cat_id"] == cid for r in rows):
            i = pool.take(1)[0]
            rows[i]["req_cat_id"] = cid
            mark(i, 9, f"req_cat_id = {cid}")

    # --- case 2: shared last_updated_at
    for shared in SHARED_TS:
        for i in pool.take(ROWS_PER_SHARED_TS):
            rows[i]["_upd"] = shared
            rows[i]["_sub"] = shared - timedelta(seconds=rng.int(3600, 20 * 86400))
            mark(i, 2, f"last_updated_at = {ts_us(shared)}")

    # --- case 3: updated before submitted
    for i in pool.take(3):
        rows[i]["_upd"] = rows[i]["_sub"] - timedelta(microseconds=rng.int(3600 * 10**6, 5 * 86400 * 10**6))
        mark(i, 3, "last_updated_at < submission_date")

    # --- extra: submission_date is nullable
    null_sub = pool.take(2)
    for i in null_sub:
        rows[i]["_sub"] = None

    # --- derived columns
    for r in rows:
        if r["_beneficiary_null"]:
            r["beneficiary_id"] = None
        elif r["req_for_id"] == 0:
            r["beneficiary_id"] = r["creator_id"]
        else:
            r["beneficiary_id"] = other_user(rng, users, r["creator_id"])

        sub, upd = r["_sub"], r["_upd"]
        r["submission_date"] = ts_s(sub) if sub else None
        r["last_updated_at"] = ts_us(upd)
        if r["req_status_id"] in SERVICED_STATUSES and sub and upd > sub:
            gap = int((upd - sub).total_seconds())
            r["serviced_date"] = ts_s(sub + timedelta(seconds=rng.int(0, max(gap - 1, 0))))
        else:
            r["serviced_date"] = None

        r["deletion_reason"] = rng.choice(DELETION_REASONS) if r["req_status_id"] == DELETED else None
        if rng.random() < 0.10:
            r["req_doc_link"] = f"{BUCKET}/{r['req_id']}/attachment.pdf"
        if rng.random() < 0.08:
            r["audio_req_desc"] = f"{BUCKET}/{r['req_id']}/audio.mp3"
        r["req_loc"] = point(rng) if rng.random() < 0.85 else None
        r["created_loc"] = point(rng) if rng.random() < 0.80 else None

        top = "0" if r["req_cat_id"] == GENERAL_CAT else r["req_cat_id"].split(".")[0]
        r["req_subj"], r["req_desc"] = rng.choice(TEMPLATES[top])

    # --- case 4: CSV-hostile text
    for (subj, desc), i in zip(TRICKY_TEXT, pool.take(len(TRICKY_TEXT))):
        rows[i]["req_subj"], rows[i]["req_desc"] = subj, desc
        mark(i, 4, "newlines, commas or quotes in req_subj/req_desc")

    # --- case 5: non-ASCII text
    for j, i in enumerate(pool.take(SPANISH_ROWS)):
        rows[i]["req_subj"], rows[i]["req_desc"] = SPANISH_TEXT[j % len(SPANISH_TEXT)]
        mark(i, 5, "Spanish")
    for (subj, desc), i in zip(OTHER_SCRIPT_TEXT, pool.take(len(OTHER_SCRIPT_TEXT))):
        rows[i]["req_subj"], rows[i]["req_desc"] = subj, desc
        mark(i, 5, "non-Latin script or emoji")

    # --- case 6: planted personal details
    for item in PII_ITEMS:
        status = item.get("status")
        i = pool.take(1, None if status is None else (lambda x, s=status: rows[x]["req_status_id"] == s))[0]
        for col, value in item.items():
            if col == "status":
                continue
            text, kinds = value
            rows[i][col] = text
            pii.append({"req_id": rows[i]["req_id"], "column": col, "pii_types": kinds})
        mark(i, 6, "see pii_rows.csv")

    # --- case 7: '' alongside NULL in each nullable text column
    for col, where in [("req_doc_link", None), ("audio_req_desc", None),
                       ("deletion_reason", lambda x: rows[x]["req_status_id"] == DELETED)]:
        for i in pool.take(2, where):
            rows[i][col] = ""
            mark(i, 7, f"{col} = ''")
    i = pool.take(1, lambda x: rows[x]["req_status_id"] == DELETED)[0]
    rows[i]["deletion_reason"] = None
    mark(i, 7, "DELETED with deletion_reason NULL (contrast with '')")

    # --- case 8: maximum lengths
    for (col, seed_text), i in zip(MAX_LEN_TEXT, pool.take(len(MAX_LEN_TEXT))):
        rows[i][col] = fill_to(seed_text, LIMITS[col])
        kind = "ASCII" if rows[i][col].isascii() else "multi-byte"
        mark(i, 8, f"{col} at {LIMITS[col]} characters, {kind}")

    for r in rows:
        for k in [k for k in r if k.startswith("_")]:
            del r[k]
    cases.sort(key=lambda c: (c["case_number"], c["req_id"]))
    return rows, cases, pii, [rows[i]["req_id"] for i in null_sub]


def build_broken_fixture(categories):
    """Case 11: one request whose creator_id matches no user. Kept out of the
    main data, which would otherwise fail its foreign keys on load."""
    return [{
        "req_id": "REQ-999-999-999-9999",
        "creator_id": user_id(99_999_999),
        "beneficiary_id": None, "lead_volunteer_id": None,
        "req_cat_id": categories[1]["cat_id"],
        "req_for_id": 0, "req_islead_id": 0, "req_type_id": 0,
        "req_priority_id": 1, "req_status_id": 0,
        "req_subj": "Orphaned creator reference",
        "req_desc": "creator_id points at a user that does not exist; an inner join on users drops this row.",
        "req_doc_link": None, "audio_req_desc": None, "deletion_reason": None,
        "req_loc": None, "created_loc": None, "iscalamity": False, "to_public": False,
        "submission_date": "2026-08-10 10:00:00", "serviced_date": None,
        "last_updated_at": "2026-08-10 10:00:00.000000",
    }]


# =================================================================== output


def fmt(v):
    """NULL -> nothing; text -> always quoted, so '' stays distinct from NULL
    under Postgres COPY ... CSV."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return '"' + v.replace('"', '""') + '"'


def write_csv(path, cols, rows):
    lines = [",".join(cols)] + [",".join(fmt(r[c]) for c in cols) for r in rows]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + "\n")


# =============================================================== self-check


def check(tables, requests, cases, fixture):
    errors = []

    def need(ok, msg):
        if not ok:
            errors.append(msg)

    users = {u["user_id"] for u in tables["users"]}
    cats = {c["cat_id"] for c in tables["help_categories"]}
    lookup_ids = {t: {r[spec["cols"][0]] for r in tables[t]} for t, spec in LOOKUPS.items()}
    fk = {"req_for_id": "request_for", "req_islead_id": "request_isleadvol",
          "req_type_id": "request_types", "req_priority_id": "request_priorities",
          "req_status_id": "request_statuses"}

    need(len({r["req_id"] for r in requests}) == len(requests), "duplicate req_id")
    need(len(users) == len(tables["users"]), "duplicate user_id")
    need(len(cats) == len(tables["help_categories"]), "duplicate cat_id")
    for m in tables["help_categories_map"]:
        need(m["parent_id"] in cats and m["child_id"] in cats, f"map row {m} points outside categories")

    for r in requests:
        need(r["creator_id"] in users, f"{r['req_id']}: creator_id not in users")
        for col in ("beneficiary_id", "lead_volunteer_id"):
            need(r[col] is None or r[col] in users, f"{r['req_id']}: {col} not in users")
        need(r["req_cat_id"] in cats, f"{r['req_id']}: req_cat_id not in categories")
        for col, table in fk.items():
            need(r[col] in lookup_ids[table], f"{r['req_id']}: {col} not in {table}")
        for col in ("req_subj", "req_desc", "audio_req_desc"):
            need(r[col] is None or len(r[col]) <= LIMITS[col], f"{r['req_id']}: {col} too long")

    for col, table in fk.items():
        used = {r[col] for r in requests}
        need(lookup_ids[table] <= used, f"unused {table} values: {sorted(lookup_ids[table] - used)}")
    need(cats <= {r["req_cat_id"] for r in requests}, "unused categories")

    leads = sum(r["lead_volunteer_id"] is not None for r in requests)
    need(0 < leads < len(requests) * 0.05, f"lead_volunteer_id non-null count {leads} not skewed")
    need(any(r["req_islead_id"] == 1 and r["lead_volunteer_id"] is None for r in requests), "case 10 missing")
    need(any(r["beneficiary_id"] is None for r in requests), "no NULL beneficiary_id")
    for s in SHARED_TS:
        need(sum(r["last_updated_at"] == ts_us(s) for r in requests) == ROWS_PER_SHARED_TS,
             f"shared timestamp {ts_us(s)} count wrong")
    need(any(r["submission_date"] and r["last_updated_at"][:19] < r["submission_date"] for r in requests),
         "case 3 missing")
    texts = [r["req_desc"] for r in requests]
    for ch in ("\n", ",", '"'):
        need(any(ch in t for t in texts), f"no req_desc containing {ch!r}")
    need(any(not t.isascii() for t in texts), "no non-ASCII req_desc")

    for col in ("req_doc_link", "audio_req_desc", "deletion_reason"):
        vals = [r[col] for r in requests]
        need("" in vals and None in vals, f"{col} lacks '' or NULL")
    for t, spec in LOOKUPS.items():
        vals = [r[spec["cols"][2]] for r in tables[t]]
        need("" in vals and None in vals, f"{t} desc lacks '' or NULL")
        for r in tables[t]:
            for c in spec["cols"][1:3]:
                need(r[c] is None or len(r[c]) <= LIMITS[c], f"{t}.{c} too long")

    for col in ("req_subj", "req_desc", "audio_req_desc"):
        need(any(r[col] and len(r[col]) == LIMITS[col] for r in requests), f"no {col} at max length")
    for col in ("cat_name", "cat_desc"):
        lens = [len(c[col]) for c in tables["help_categories"]]
        need(max(lens) == LIMITS[col], f"no {col} at max length")

    need(all(f["creator_id"] not in users for f in fixture), "fixture reference unexpectedly exists")
    need(all(f["req_id"] not in {r["req_id"] for r in requests} for f in fixture), "fixture req_id clashes")
    need({c["case_number"] for c in cases} >= set(range(1, 11)), "a numbered case has no rows")
    return errors


# ===================================================================== main


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--requests", type=int, default=DEFAULT_REQUESTS)
    ap.add_argument("--users", type=int, default=DEFAULT_USERS)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "output"))
    args = ap.parse_args()

    rng = Rng(args.seed)
    users = [user_id(k) for k in range(1, args.users + 1)]
    categories = build_categories()
    requests, cases, pii, null_sub = build_requests(rng, args.requests, users, categories)
    fixture = build_broken_fixture(categories)

    tables = {t: [dict(zip(spec["cols"], row + (REF_TS,))) for row in spec["rows"]]
              for t, spec in LOOKUPS.items()}
    tables["help_categories"] = categories
    tables["help_categories_map"] = build_category_map(categories)
    tables["users"] = [{"user_id": u} for u in users]

    errors = check(tables, requests, cases, fixture)
    if errors:
        print("Self-check failed:", *errors, sep="\n  ", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.join(args.out, "fixtures"), exist_ok=True)
    for t, spec in LOOKUPS.items():
        write_csv(os.path.join(args.out, f"{t}.csv"), spec["cols"], tables[t])
    write_csv(os.path.join(args.out, "help_categories.csv"),
              ["cat_id", "cat_name", "cat_desc", "last_updated_at"], categories)
    write_csv(os.path.join(args.out, "help_categories_map.csv"),
              ["parent_id", "child_id", "last_updated_at"], tables["help_categories_map"])
    write_csv(os.path.join(args.out, "users.csv"), ["user_id"], tables["users"])
    write_csv(os.path.join(args.out, "requests.csv"), REQUEST_COLS, requests)
    write_csv(os.path.join(args.out, "case_index.csv"), ["req_id", "case_number", "case_name", "note"], cases)
    write_csv(os.path.join(args.out, "pii_rows.csv"), ["req_id", "column", "pii_types"], pii)
    write_csv(os.path.join(args.out, "fixtures", "requests_broken_reference.csv"), REQUEST_COLS, fixture)

    print(f"Wrote {len(requests)} requests, {len(users)} users, {len(categories)} categories "
          f"to {args.out} (seed {args.seed}). Self-check passed.")
    print(f"Rows with NULL submission_date (not a numbered case): {', '.join(null_sub)}")


if __name__ == "__main__":
    main()
