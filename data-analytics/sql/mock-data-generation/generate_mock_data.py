#!/usr/bin/env python3
"""Mock data generator for the requests table and the tables it references (issue #587).

Generates from saayam_schema.sql, never from a database. Running this script twice
with the same seed produces byte-identical output.

Usage:
    python generate_mock_data.py
    python generate_mock_data.py --seed 7 --requests 800 --output-dir /tmp/out

Output (written to --output-dir, default: data-analytics/sql, one level up from this
script):
    requests.csv, help_categories.csv, help_categories_map.csv, request_for.csv,
    request_isleadvol.csv, request_types.csv, request_priorities.csv,
    request_statuses.csv, users.csv

A second file, broken_reference_fixture.csv, is written next to this script (not
into --output-dir), since it must stay out of the main data: it is a single request
row with a reference that cannot exist under the real constraints, kept separate so
loading the main CSVs never fails because of it.

Every numbered "case" below is referenced by number in README.md and in the
printed case-row report this script prints after writing its output.
"""

import argparse
import csv
import os
import random
from datetime import datetime, timedelta

SEED = 42
TARGET_REQUESTS = 500
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = os.path.normpath(os.path.join(HERE, ".."))

TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"  # timestamp(6): microsecond precision
DATE_START = datetime(2025, 1, 1)
DATE_END = datetime(2026, 10, 1)

# --- fixed lookup values (real, small, and listed in the schema's own comments) ----
REQUEST_FOR = [
    (0, "SELF", "The requester is asking for themselves"),
    (1, "OTHER", "The requester is asking on someone else's behalf"),
]
REQUEST_ISLEADVOL = [
    (0, "NO", "No lead volunteer is assigned"),
    (1, "YES", "A lead volunteer is assigned"),
]
REQUEST_TYPES = [
    (0, "IN_PERSON", "Help is provided in person"),
    (1, "REMOTE", "Help is provided remotely"),
]
REQUEST_PRIORITIES = [
    (0, "LOW", "Low priority"),
    (1, "MEDIUM", "Medium priority"),
    (2, "HIGH", "High priority"),
    (3, "CRITICAL", "Critical priority"),
]
REQUEST_STATUSES = [
    (0, "CREATED", "Request created"),
    (1, "MATCHING_VOLUNTEER", "Matching a volunteer"),
    (2, "IN_PROGRESS", "In progress"),
    (3, "RESOLVED", "Resolved"),
    (4, "CANCELLED", "Cancelled"),
    (5, "DELETED", "Deleted"),
    (6, "RATED_BY_REQUESTER", "Rated by the requester"),
    (7, "RATED_BY_VOLUNTEER", "Rated by the volunteer"),
    (8, "VOLUNTEER_NOT_FOUND", "No volunteer was found"),
]

# A plausible category tree, not a copy of the live 80-row one (case: realistic shape only).
HELP_CATEGORIES = [
    ("1", "FOOD_AND_ESSENTIALS", "Groceries, meals and household essentials"),
    ("1.1", "GROCERY_SHOPPING", "Picking up or delivering groceries"),
    ("1.2", "MEAL_PREPARATION", "Cooking or delivering prepared meals"),
    ("2", "TRANSPORTATION", "Rides and errands"),
    ("2.1", "RIDES_TO_APPOINTMENTS", "Transport to medical or other appointments"),
    ("2.2", "ERRANDS", "Running errands such as pharmacy pickup"),
    ("3", "HOME_HELP", "Help around the home"),
    ("3.1", "YARD_WORK", "Mowing, raking, and other yard work"),
    ("3.2", "MINOR_REPAIRS", "Small household repairs"),
    ("4", "COMPANIONSHIP", "Visits and companionship"),
    ("5", "TECH_SUPPORT", "Help with computers, phones and devices"),
    ("5.1", "DEVICE_SETUP", "Setting up a new device or account"),
]

# Column order for requests.csv and broken_reference_fixture.csv - must match
# saayam_schema.sql's requests table exactly, including req_loc/created_loc, or a
# \copy silently shifts every later column into the wrong one.
REQUESTS_HEADER = [
    "req_id", "creator_id", "beneficiary_id", "lead_volunteer_id", "req_cat_id",
    "req_for_id", "req_islead_id", "req_type_id", "req_priority_id", "req_status_id",
    "req_subj", "req_desc", "req_doc_link", "audio_req_desc", "deletion_reason",
    "req_loc", "created_loc", "iscalamity", "to_public",
    "submission_date", "serviced_date", "last_updated_at",
]

# PII phrasings used to build case 6's planted rows (tracked in pii_flagged_requests.csv).
PII_PHONES_DIGIT = [
    "call me at 555-123-4567",
    "reach me at (555) 234-5678",
    "my number is 555.345.6789",
]
PII_PHONES_WORDS = [
    "my number is four eight zero, five five five, one two one two",
    "call five five five, seven six five, four three two one",
]
PII_EMAILS = ["contact me at jane.doe@example.com", "email me: r.martinez@example.org"]
PII_ADDRESSES = ["I live at 742 Evergreen Terrace, Springfield, IL 62704",
                 "please come to 18 Birch Lane, Apt 3B, Hartford, CT 06103"]
PII_NAMES = ["my neighbor Nguyen Thi Lan can confirm this", "ask for Priya Venkataraman at the front desk"]


def make_user_id(n):
    """SID-00-xxx-xxx-xxx-xxx-xxx, matching the trigger-generated format in the schema."""
    padded = f"{n:015d}"
    groups = [padded[i:i + 3] for i in range(0, 15, 3)]
    return "SID-00-" + "-".join(groups)


def make_req_id(n):
    """REQ-xxx-xxx-xxx-xxxx, matching the trigger-generated format in the schema."""
    padded = f"{n:013d}"
    return f"REQ-{padded[0:3]}-{padded[3:6]}-{padded[6:9]}-{padded[9:13]}"


def fmt_ts(dt):
    return dt.strftime(TS_FORMAT)


def rand_ts(rng, start, end):
    span = int((end - start).total_seconds())
    return start + timedelta(seconds=rng.randint(0, max(span, 0)),
                             microseconds=rng.randint(0, 999999))


def build_help_categories():
    return [{"cat_id": c, "cat_name": n, "cat_desc": d, "last_updated_at": fmt_ts(DATE_START)}
            for c, n, d in HELP_CATEGORIES]


def build_help_categories_map():
    rows = []
    for cat_id, _, _ in HELP_CATEGORIES:
        parent = cat_id.rsplit(".", 1)[0] if "." in cat_id else ""
        rows.append({"parent_id": parent or None, "child_id": cat_id,
                    "last_updated_at": fmt_ts(DATE_START)})
    return rows


def build_simple_lookup(values, id_field, name_field, desc_field):
    return [{id_field: v[0], name_field: v[1], desc_field: v[2], "last_updated_at": fmt_ts(DATE_START)}
            for v in values]


def build_users(rng, count):
    return [{"user_id": make_user_id(i), "last_updated_at": fmt_ts(rand_ts(rng, DATE_START, DATE_END))}
            for i in range(1, count + 1)]


def pad_to_length(text, length):
    if len(text) >= length:
        return text[:length]
    filler = " filler text to reach the maximum allowed length for this column"
    while len(text) < length:
        text += filler
    return text[:length]


def build_requests(rng, user_ids, cat_ids):
    n = TARGET_REQUESTS
    rows = [dict() for _ in range(n)]

    # --- baseline random assignment for every row -----------------------------------
    for i, row in enumerate(rows):
        row["req_id"] = make_req_id(i + 1)
        row["creator_id"] = rng.choice(user_ids)
        row["beneficiary_id"] = rng.choice(user_ids)
        row["lead_volunteer_id"] = None
        row["req_cat_id"] = rng.choice(cat_ids)
        row["req_for_id"] = rng.choice([0, 1])
        row["req_islead_id"] = 0
        row["req_type_id"] = rng.choice([0, 1])
        row["req_priority_id"] = rng.choice([0, 1, 2])  # 3 (CRITICAL) added by the coverage pass
        row["req_status_id"] = rng.choice([0, 1, 2, 6, 7])  # 3,4,5,8 added by the coverage pass
        row["req_subj"] = f"Need help with request number {i + 1}"
        row["req_desc"] = f"This is a routine help request (number {i + 1}) generated for testing."
        row["req_doc_link"] = None
        row["audio_req_desc"] = None
        row["deletion_reason"] = None
        row["req_loc"] = None
        row["created_loc"] = None
        row["iscalamity"] = rng.choice([True, False, False, False, None])
        row["to_public"] = rng.choice([False, False, False, True])
        submission = rand_ts(rng, DATE_START, DATE_END)
        row["submission_date"] = fmt_ts(submission)
        row["serviced_date"] = (fmt_ts(rand_ts(rng, submission, DATE_END))
                               if row["req_status_id"] in (3, 4, 5, 6, 7) else None)
        row["last_updated_at"] = fmt_ts(rand_ts(rng, submission, DATE_END))
        row["_submission_dt"] = submission

    cases = {}  # case number -> list of req_ids, filled in as each case is applied

    # Every "special row" case below (2-10) draws from its own disjoint slice of this
    # shuffled index list, so no row is asked to demonstrate two unrelated cases at
    # once - each is independently identifiable in the README. Case 1's null-skew is
    # the one exception: it is a background statistical property of the whole table,
    # applied last, and is allowed to land on special rows too (nulling beneficiary_id
    # does not interfere with, say, a row's deliberately-oversized req_desc).
    order = list(range(n))
    rng.shuffle(order)
    next_free = 0

    def take(count):
        nonlocal next_free
        chunk = order[next_free:next_free + count]
        next_free += count
        return chunk

    # --- case 2: several rows sharing one last_updated_at, to the microsecond. --------
    # The shared value is computed from these rows' own submission dates (rather than
    # a fixed constant), so this case can never accidentally also trigger case 3 by
    # landing earlier than one row's own submission_date.
    shared_rows = take(5)
    latest_submission = max(rows[idx]["_submission_dt"] for idx in shared_rows)
    shared_ts = fmt_ts(latest_submission + timedelta(hours=1, microseconds=123456))
    for idx in shared_rows:
        rows[idx]["last_updated_at"] = shared_ts
    cases[2] = [rows[idx]["req_id"] for idx in shared_rows]

    # --- case 3: last_updated_at earlier than submission_date. ------------------------
    idx = take(1)[0]
    submission = rows[idx]["_submission_dt"]
    rows[idx]["last_updated_at"] = fmt_ts(submission - timedelta(days=3))
    cases[3] = [rows[idx]["req_id"]]

    # --- case 4: embedded newlines, commas and double quotes. -------------------------
    idx = take(1)[0]
    rows[idx]["req_desc"] = 'Need help with "yard work," and also groceries.\nPlease call after 5pm, thanks.'
    cases[4] = [rows[idx]["req_id"]]

    # --- case 5: non-ASCII (Spanish) free text. ----------------------------------------
    idx = take(1)[0]
    rows[idx]["req_desc"] = ("Necesito ayuda con la mudanza de mi abuela; esta muy enferma "
                            "y no puede subir escaleras. Es una situacion urgente, por favor.")
    cases[5] = [rows[idx]["req_id"]]

    # --- case 6: planted PII, several formats, tracked separately. --------------------
    pii_pool = (
        [("phone_digits", t) for t in PII_PHONES_DIGIT]
        + [("phone_words", t) for t in PII_PHONES_WORDS]
        + [("email", t) for t in PII_EMAILS]
        + [("address", t) for t in PII_ADDRESSES]
        + [("name", t) for t in PII_NAMES]
    )
    pii_rows = []
    for idx, (pii_type, text) in zip(take(len(pii_pool)), pii_pool):
        rows[idx]["req_desc"] = text
        pii_rows.append({"req_id": rows[idx]["req_id"], "pii_type": pii_type, "text": text})
    cases[6] = [r["req_id"] for r in pii_rows]

    # --- case 7: empty string vs. null, in every nullable text column. ----------------
    text_cols = ["req_doc_link", "audio_req_desc", "deletion_reason"]
    case7_ids = []
    for col in text_cols:
        empty_idx, null_idx = take(2)
        rows[empty_idx][col] = ""
        rows[null_idx][col] = None  # already None by default, set explicitly for clarity
        case7_ids += [rows[empty_idx]["req_id"], rows[null_idx]["req_id"]]
    cases[7] = case7_ids
    # a few more rows get realistic (non-case-7) populated values, for plausibility
    for idx in take(6):
        rows[idx]["req_doc_link"] = "https://docs.example.org/requests/attachment.pdf"

    # --- case 8: a value at the maximum length of req_subj (125) and req_desc (255). ---
    idx = take(1)[0]
    rows[idx]["req_subj"] = pad_to_length("Urgent request that fills the subject line completely", 125)
    rows[idx]["req_desc"] = pad_to_length(
        "This description is deliberately padded so it reaches the exact maximum length "
        "allowed for this column, to check that nothing truncates or rejects a value that "
        "exactly fills it.", 255)
    assert len(rows[idx]["req_subj"]) == 125 and len(rows[idx]["req_desc"]) == 255
    cases[8] = [rows[idx]["req_id"]]

    # --- case 9: every lookup value used by at least one request. ---------------------
    # req_for/req_type already cover {0,1} with 500 random draws almost certainly, but
    # force it to be certain rather than probabilistic.
    coverage_rows = []
    for value in (0, 1):
        if not any(r["req_for_id"] == value for r in rows):
            idx = take(1)[0]
            rows[idx]["req_for_id"] = value
            coverage_rows.append(idx)
        if not any(r["req_type_id"] == value for r in rows):
            idx = take(1)[0]
            rows[idx]["req_type_id"] = value
            coverage_rows.append(idx)
    for value in (3,):  # CRITICAL priority: no real request currently uses it
        idx = take(1)[0]
        rows[idx]["req_priority_id"] = value
        coverage_rows.append(idx)
    for value in (3, 4, 5, 8):  # RESOLVED, CANCELLED, DELETED, VOLUNTEER_NOT_FOUND
        idx = take(1)[0]
        rows[idx]["req_status_id"] = value
        coverage_rows.append(idx)
    cases[9] = [rows[idx]["req_id"] for idx in coverage_rows]

    # --- case 10: req_islead_id=1 with a null lead_volunteer_id (a contradiction that
    # exists in the live data - reproduced so nothing assumes the two always agree). --
    # Ratios scaled from the real dev snapshot in the schema comment (221 requests: 9
    # flagged islead=1, of which only 3 have a lead volunteer recorded).
    islead_1_with_lead = round(n * 3 / 221)      # ~7, the "correct" rows
    islead_1_without_lead = round(n * 9 / 221) - islead_1_with_lead  # ~13, the contradiction

    with_lead_rows = take(islead_1_with_lead)
    for idx in with_lead_rows:
        rows[idx]["req_islead_id"] = 1
        rows[idx]["lead_volunteer_id"] = rng.choice(user_ids)

    without_lead_rows = take(islead_1_without_lead)
    for idx in without_lead_rows:
        rows[idx]["req_islead_id"] = 1
        rows[idx]["lead_volunteer_id"] = None
    cases[10] = [rows[idx]["req_id"] for idx in without_lead_rows]

    # --- case 1: skewed nulls on lead_volunteer_id / beneficiary_id (background shape,
    # not a pinpoint row - applied across the whole table, last). ----------------------
    # Every row with req_islead_id=0 has no recorded lead volunteer (realistic: you
    # would not expect one if the flag says there isn't a lead), which combined with
    # the 13 "without_lead" rows above reproduces the real 218/221 null ratio exactly
    # for n=500 (480 + 13 = 493, i.e. round(500 * 218 / 221)).
    for row in rows:
        if row["req_islead_id"] == 0:
            row["lead_volunteer_id"] = None
    lead_null_count = sum(1 for r in rows if r["lead_volunteer_id"] is None)

    beneficiary_null_count = round(n * 8 / 221)  # ~18
    for idx in rng.sample(range(n), beneficiary_null_count):
        rows[idx]["beneficiary_id"] = None
    cases[1] = {
        "lead_volunteer_id_null_count": lead_null_count,
        "beneficiary_id_null_count": beneficiary_null_count,
    }

    for row in rows:
        del row["_submission_dt"]
    return rows, cases, pii_rows


def build_broken_reference_fixture(rng, user_ids, cat_ids):
    """One request row with a single reference that cannot exist under the real
    constraints (case 11). Every other reference on the row is valid, so loading it
    isolates exactly one broken relationship."""
    fake_cat_id = "99.99.99"
    assert fake_cat_id not in cat_ids
    submission = rand_ts(rng, DATE_START, DATE_END)
    return [{
        "req_id": "REQ-999-999-999-9999",
        "creator_id": rng.choice(user_ids),
        "beneficiary_id": None,
        "lead_volunteer_id": None,
        "req_cat_id": fake_cat_id,  # <- the broken reference; not in help_categories.csv
        "req_for_id": 0,
        "req_islead_id": 0,
        "req_type_id": 0,
        "req_priority_id": 1,
        "req_status_id": 0,
        "req_subj": "Fixture: references a help category that does not exist",
        "req_desc": "This row exists only to test that a broken (impossible-in-prod) "
                   "reference does not silently vanish from a LEFT JOIN-based export.",
        "req_doc_link": None,
        "audio_req_desc": None,
        "deletion_reason": None,
        "req_loc": None,
        "created_loc": None,
        "iscalamity": False,
        "to_public": False,
        "submission_date": fmt_ts(submission),
        "serviced_date": None,
        "last_updated_at": fmt_ts(submission),
    }]


def write_csv(path, header, rows):
    """Quotes every non-null field and leaves null fields bare and unquoted (Python
    3.12's csv.QUOTE_NOTNULL), so a genuinely-empty string ("") round-trips through
    Postgres COPY as an empty string while None round-trips as NULL - the two stay
    distinguishable on disk, which case 7 specifically requires."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n", quoting=csv.QUOTE_NOTNULL)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(col) for col in header])


def main():
    global TARGET_REQUESTS
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--requests", type=int, default=TARGET_REQUESTS,
                       help="only 500 (the default) has been validated against every case's exact ratio")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    TARGET_REQUESTS = args.requests
    rng = random.Random(args.seed)

    os.makedirs(args.output_dir, exist_ok=True)

    help_categories = build_help_categories()
    help_categories_map = build_help_categories_map()
    request_for = build_simple_lookup(REQUEST_FOR, "req_for_id", "req_for", "req_for_desc")
    request_isleadvol = build_simple_lookup(REQUEST_ISLEADVOL, "req_islead_id", "req_islead", "req_islead_desc")
    request_types = build_simple_lookup(REQUEST_TYPES, "req_type_id", "req_type", "req_type_desc")
    request_priorities = build_simple_lookup(REQUEST_PRIORITIES, "req_priority_id", "req_priority", "req_priority_desc")
    request_statuses = build_simple_lookup(REQUEST_STATUSES, "req_status_id", "req_status", "req_status_desc")
    users = build_users(rng, count=150)
    user_ids = [u["user_id"] for u in users]
    cat_ids = [c["cat_id"] for c in help_categories]

    requests_rows, cases, pii_rows = build_requests(rng, user_ids, cat_ids)
    broken_fixture = build_broken_reference_fixture(rng, user_ids, cat_ids)

    write_csv(os.path.join(args.output_dir, "help_categories.csv"),
             ["cat_id", "cat_name", "cat_desc", "last_updated_at"], help_categories)
    write_csv(os.path.join(args.output_dir, "help_categories_map.csv"),
             ["parent_id", "child_id", "last_updated_at"], help_categories_map)
    write_csv(os.path.join(args.output_dir, "request_for.csv"),
             ["req_for_id", "req_for", "req_for_desc", "last_updated_at"], request_for)
    write_csv(os.path.join(args.output_dir, "request_isleadvol.csv"),
             ["req_islead_id", "req_islead", "req_islead_desc", "last_updated_at"], request_isleadvol)
    write_csv(os.path.join(args.output_dir, "request_types.csv"),
             ["req_type_id", "req_type", "req_type_desc", "last_updated_at"], request_types)
    write_csv(os.path.join(args.output_dir, "request_priorities.csv"),
             ["req_priority_id", "req_priority", "req_priority_desc", "last_updated_at"], request_priorities)
    write_csv(os.path.join(args.output_dir, "request_statuses.csv"),
             ["req_status_id", "req_status", "req_status_desc", "last_updated_at"], request_statuses)
    write_csv(os.path.join(args.output_dir, "users.csv"), ["user_id", "last_updated_at"], users)
    write_csv(os.path.join(args.output_dir, "requests.csv"), REQUESTS_HEADER, requests_rows)
    write_csv(os.path.join(HERE, "broken_reference_fixture.csv"), REQUESTS_HEADER, broken_fixture)

    write_csv(os.path.join(HERE, "pii_flagged_requests.csv"), ["req_id", "pii_type", "text"], pii_rows)

    print(f"requests.csv:       {len(requests_rows)} rows")
    print(f"users.csv:          {len(users)} rows")
    print(f"help_categories.csv:{len(help_categories)} rows")
    print(f"broken_reference_fixture.csv: {len(broken_fixture)} row (kept out of {args.output_dir})")
    print(f"pii_flagged_requests.csv:     {len(pii_rows)} rows")
    print()
    print("Case -> req_id(s):")
    print(f"  1  (skewed nulls)                 lead_volunteer_id null={cases[1]['lead_volunteer_id_null_count']}, "
         f"beneficiary_id null={cases[1]['beneficiary_id_null_count']}")
    print(f"  2  (shared last_updated_at)        {cases[2]}")
    print(f"  3  (last_updated_at < submission)  {cases[3]}")
    print(f"  4  (newlines/commas/quotes)        {cases[4]}")
    print(f"  5  (non-ASCII Spanish)             {cases[5]}")
    print(f"  6  (planted PII)                   {cases[6]}")
    print(f"  7  (empty string vs null)          {cases[7]}")
    print(f"  8  (max-length values)             {cases[8]}")
    print(f"  9  (every lookup value used)       {cases[9]}")
    print(f"  10 (islead=1, lead_volunteer null) {cases[10]}")
    print(f"  11 (broken reference fixture)      {broken_fixture[0]['req_id']} (separate file)")


if __name__ == "__main__":
    main()
