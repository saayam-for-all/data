"""
Generate mock data for the requests table and every table it references.

Run it like this:
    python generate_requests_mock_data.py --seed 42 --out output

Same seed gives the same files, byte for byte.
Nothing here is copied from the dev database.
"""
import argparse
import os
import random
from datetime import datetime, timedelta

NUM_REQUESTS = 500
NUM_USERS = 60

# fixed dates, never datetime.now(), so the output is repeatable
BASE_TIME = datetime(2026, 1, 1, 8, 0, 0)
LOOKUP_TIME = datetime(2026, 1, 1, 0, 0, 0)

# lookup values from the comments in saayam_schema.sql
REQUEST_FOR = [(0, "SELF"), (1, "OTHER")]
ISLEAD = [(0, "NO"), (1, "YES")]
REQUEST_TYPES = [(0, "IN_PERSON"), (1, "REMOTE")]
PRIORITIES = [(0, "LOW"), (1, "MEDIUM"), (2, "HIGH"), (3, "CRITICAL")]
STATUSES = [
    (0, "CREATED"), (1, "MATCHING_VOLUNTEER"), (2, "IN_PROGRESS"),
    (3, "RESOLVED"), (4, "CANCELLED"), (5, "DELETED"),
    (6, "RATED_BY_REQUESTER"), (7, "RATED_BY_VOLUNTEER"),
    (8, "VOLUNTEER_NOT_FOUND"),
]

# made-up category tree, ids are hierarchy paths like '1', '1.3', '1.3.1'
SUBCATEGORIES = {
    "Food": ["Groceries", "Meal delivery", "Baby supplies"],
    "Housing": ["Rent help", "Repairs", "Temporary shelter"],
    "Health": ["Transport to clinic", "Medication pickup", "Mental wellness"],
    "Education": ["Tutoring", "School supplies", "Job training"],
    "Transport": ["Rides", "Bus passes", "Car repair"],
}

SUBJECTS = [
    "Need help with groceries", "Ride to the clinic", "Help with rent",
    "Homework tutoring", "Broken heater", "Pick up my prescription",
    "Need a bus pass", "Help filling out a form",
]
DESCRIPTIONS = [
    "I need some help this week, please.",
    "Could someone assist me when they have time?",
    "This is fairly urgent for my family.",
    "I have not been able to do this on my own since last month.",
    "Any help at all would be appreciated.",
]
DELETION_REASONS = ["Duplicate request", "No longer needed", "Created by mistake"]


def make_user_id(n):
    # looks like SID-00-000-000-000-000-026
    d = f"{n:017d}"
    return "SID-" + "-".join([d[0:2], d[2:5], d[5:8], d[8:11], d[11:14], d[14:17]])


def make_req_id(n):
    # looks like REQ-000-000-000-0001
    d = f"{n:013d}"
    return f"REQ-{d[0:3]}-{d[3:6]}-{d[6:9]}-{d[9:13]}"


def fmt(value):
    # NULL becomes nothing between the commas. Text is always quoted, so an
    # empty string comes out as "" and Postgres can tell it apart from NULL.
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"' + value.replace('"', '""') + '"'
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S.%f")
    return str(value)


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(header) + "\n")
        for row in rows:
            f.write(",".join(fmt(v) for v in row) + "\n")


def build_categories():
    # returns (cat_id, parent_id, name, description)
    cats = []
    for i, (top, subs) in enumerate(SUBCATEGORIES.items(), start=1):
        cats.append((str(i), None, top, top + " related help"))
        for j, sub in enumerate(subs, start=1):
            sub_id = f"{i}.{j}"
            cats.append((sub_id, str(i), sub, sub + " requests"))
            for k, kind in enumerate(["One-time", "Ongoing"], start=1):
                cats.append((f"{sub_id}.{k}", sub_id,
                             f"{sub} ({kind.lower()})",
                             f"{kind} {sub.lower()} support"))
    return cats


def random_point(rng):
    lon = rng.uniform(-97.1, -96.6)
    lat = rng.uniform(32.6, 33.1)
    return f"SRID=4326;POINT({lon:.6f} {lat:.6f})"


def make_request(rng, n, user_ids, cat_ids):
    submitted = BASE_TIME + timedelta(minutes=rng.randint(0, 250000),
                                      microseconds=rng.randint(0, 999999))
    updated = submitted + timedelta(minutes=rng.randint(1, 5000),
                                    microseconds=rng.randint(0, 999999))
    creator = rng.choice(user_ids)
    req_for = rng.choice([0, 1])

    # about 3.6% of requests have no beneficiary (8 of 221 in dev)
    if rng.random() < 0.036:
        beneficiary = None
    elif req_for == 0:
        beneficiary = creator
    else:
        beneficiary = rng.choice(user_ids)

    # about 1.4% have a lead volunteer (3 of 221 in dev)
    has_lead = rng.random() < 0.008
    status = rng.randint(0, 8)

    serviced = None
    if status in (3, 6, 7):
        serviced = submitted + timedelta(hours=rng.randint(1, 200))
    deletion_reason = rng.choice(DELETION_REASONS) if status == 5 else None

    r = rng.random()
    calamity = None if r < 0.2 else (True if r > 0.98 else False)
    r = rng.random()
    to_public = None if r < 0.03 else (r > 0.7)

    return {
        "req_id": make_req_id(n),
        "creator_id": creator,
        "beneficiary_id": beneficiary,
        "lead_volunteer_id": rng.choice(user_ids) if has_lead else None,
        "req_cat_id": rng.choice(cat_ids),
        "req_for_id": req_for,
        "req_islead_id": 1 if has_lead else 0,
        "req_type_id": rng.choice([0, 1]),
        "req_priority_id": rng.choice([0, 1, 2, 3]),
        "req_status_id": status,
        "req_subj": rng.choice(SUBJECTS),
        "req_desc": rng.choice(DESCRIPTIONS),
        "req_doc_link": None,
        "audio_req_desc": None,
        "deletion_reason": deletion_reason,
        "req_loc": random_point(rng) if rng.random() < 0.8 else None,
        "created_loc": random_point(rng) if rng.random() < 0.9 else None,
        "iscalamity": calamity,
        "to_public": to_public,
        "submission_date": submitted,
        "serviced_date": serviced,
        "last_updated_at": updated,
    }


def apply_special_cases(rng, rows, user_ids):
    pii_log = []

    def row(n):
        return rows[n - 1]  # request number n, counting from 1

    # case 1 (skewed nulls) comes from make_request, plus a few forced ones
    for n in (80, 81, 82):
        row(n)["beneficiary_id"] = None

    # case 2: ten rows share one last_updated_at to the microsecond
    shared = datetime(2026, 3, 1, 12, 0, 0, 123456)
    for n in range(1, 11):
        row(n)["submission_date"] = shared - timedelta(days=1)
        row(n)["last_updated_at"] = shared

    # case 3: last_updated_at earlier than submission_date
    for n in (11, 12, 13):
        row(n)["last_updated_at"] = row(n)["submission_date"] - timedelta(hours=3)

    # case 4: commas, double quotes and newlines in free text
    row(14)["req_desc"] = 'He said, "please call me"\nSecond line, with a comma'
    row(15)["req_subj"] = 'Needs "urgent" help, today'
    row(15)["req_desc"] = 'Line one\r\nLine two with "quotes", commas, and a blank line\n\nend'

    # case 5: non-ASCII text
    row(16)["req_subj"] = "Necesito ayuda con la comida"
    row(16)["req_desc"] = "Hola, necesito ayuda con alimentos para mis niños. ¿Pueden ayudarme?"
    row(17)["req_desc"] = "Se requiere ayuda con el alquiler, señor García."

    # case 6: personal details planted in the text, every one logged
    pii = {
        18: ("Call me at 480-555-0142 after 5pm.", "phone with dashes"),
        19: ("My number is (480) 555 0187.", "phone with parentheses"),
        20: ("Reach me at +1 480 555 0199.", "phone with country code"),
        21: ("Phone is four eight zero, five five five, zero one two three.", "phone written as words"),
        22: ("Email me at maria.garcia@example.com please.", "email address"),
        23: ("I live at 1234 Elm Street, Apt 5, Dallas TX 75201.", "street address"),
        24: ("My name is Sofía Hernández and I need help.", "non-English name"),
        25: ("Contact Priya Venkataraman or Józef Kowalski.", "names"),
    }
    for n, (text, kind) in pii.items():
        row(n)["req_desc"] = text
        pii_log.append((row(n)["req_id"], 6, kind))

    # case 7: empty string instead of NULL in the nullable text columns
    row(26)["req_doc_link"] = ""
    row(26)["audio_req_desc"] = ""
    row(26)["deletion_reason"] = ""

    # case 8: text that fills the column exactly
    row(27)["req_subj"] = "S" * 125
    row(27)["req_desc"] = "D" * 255
    row(27)["audio_req_desc"] = "A" * 255
    # same limit with non-ASCII, Postgres counts characters not bytes
    row(28)["req_subj"] = ("Necesito ayuda urgente " * 10)[:125]
    row(28)["req_desc"] = ("Ñandú, niños y señoras necesitan ayuda. " * 10)[:255]

    # case 9: every lookup value used at least once
    for i, (value, _) in enumerate(STATUSES):
        row(30 + i)["req_status_id"] = value
    for i, (value, _) in enumerate(PRIORITIES):
        row(40 + i)["req_priority_id"] = value
    for i, (value, _) in enumerate(REQUEST_TYPES):
        row(50 + i)["req_type_id"] = value
    for i, (value, _) in enumerate(REQUEST_FOR):
        row(60 + i)["req_for_id"] = value

    # case 10: islead = 1 but no lead volunteer recorded
    for n in range(70, 76):
        row(n)["req_islead_id"] = 1
        row(n)["lead_volunteer_id"] = None
    # and three where the flag and the volunteer agree
    for n in range(76, 79):
        row(n)["req_islead_id"] = 1
        row(n)["lead_volunteer_id"] = rng.choice(user_ids)

    return pii_log


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="output")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    os.makedirs(args.out, exist_ok=True)

    user_ids = [make_user_id(n) for n in range(1, NUM_USERS + 1)]
    categories = build_categories()
    cat_ids = [c[0] for c in categories]

    rows = [make_request(rng, n, user_ids, cat_ids)
            for n in range(1, NUM_REQUESTS + 1)]
    pii_log = apply_special_cases(rng, rows, user_ids)

    def out(name):
        return os.path.join(args.out, name)

    # lookup tables
    def lookup_rows(pairs):
        return [[i, name, name.replace("_", " ").lower(), LOOKUP_TIME]
                for i, name in pairs]

    write_csv(out("request_for.csv"),
              ["req_for_id", "req_for", "req_for_desc", "last_updated_at"],
              lookup_rows(REQUEST_FOR))
    write_csv(out("request_isleadvol.csv"),
              ["req_islead_id", "req_islead", "req_islead_desc", "last_updated_at"],
              lookup_rows(ISLEAD))
    write_csv(out("request_types.csv"),
              ["req_type_id", "req_type", "req_type_desc", "last_updated_at"],
              lookup_rows(REQUEST_TYPES))
    write_csv(out("request_priorities.csv"),
              ["req_priority_id", "req_priority", "req_priority_desc", "last_updated_at"],
              lookup_rows(PRIORITIES))
    write_csv(out("request_statuses.csv"),
              ["req_status_id", "req_status", "req_status_desc", "last_updated_at"],
              lookup_rows(STATUSES))

    # category tree
    write_csv(out("help_categories.csv"),
              ["cat_id", "cat_name", "cat_desc", "last_updated_at"],
              [[c[0], c[2], c[3], LOOKUP_TIME] for c in categories])
    write_csv(out("help_categories_map.csv"),
              ["parent_id", "child_id", "last_updated_at"],
              [[c[1], c[0], LOOKUP_TIME] for c in categories])

    # users, key column only
    write_csv(out("users.csv"), ["user_id"], [[u] for u in user_ids])

    # the requests themselves
    columns = list(rows[0].keys())
    write_csv(out("requests.csv"), columns,
              [[r[c] for c in columns] for r in rows])

    # which rows have personal details planted in them
    write_csv(out("pii_rows.csv"), ["req_id", "case_number", "kind"], pii_log)

    # case 11: a request that points at a user who does not exist.
    # Own file, so loading the main data never fails.
    broken = dict(rows[99])
    broken["req_id"] = make_req_id(9999)
    broken["creator_id"] = make_user_id(99999)
    write_csv(out("fixture_broken_reference.csv"), columns,
              [[broken[c] for c in columns]])

    print("Wrote", len(rows), "requests to", args.out)


if __name__ == "__main__":
    main()
