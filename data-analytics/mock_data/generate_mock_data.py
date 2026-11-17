#!/usr/bin/env python3
"""Mock data generator for the `requests` table and the tables it references (issue #587).

Usage:
    python generate_mock_data.py [--seed 587] [--out ./output] [--n-requests 500]

Same seed => byte-identical output. No database access, no real data: everything is
generated from the definitions in the SCHEMA section below.

!! The SCHEMA section is the ONLY place that knows table/column names and lookup values.
!! It was written without access to saayam_schema.sql / the #573 comment. Verify it
!! against those and edit the constants if anything differs; nothing else should need to change.
"""
import argparse
import os
import random
from datetime import datetime, timedelta

# --------------------------------------------------------------------------------------
# SCHEMA  (verify against saayam_schema.sql)
# --------------------------------------------------------------------------------------
REQUESTS_COLS = [
    "req_id", "req_user_id", "req_for_id", "req_islead_id", "req_type_id",
    "req_priority_id", "req_status_id", "req_cat_id", "lead_volunteer_id",
    "beneficiary_id", "req_subj", "req_desc", "submission_date", "last_updated_at",
]
SUBJ_MAX = 125   # req_subj varchar(125)
DESC_MAX = 255   # req_desc varchar(255)
NULLABLE_TEXT = ["req_subj", "req_desc"]          # nullable text columns in requests
NULLABLE_REFS = ["lead_volunteer_id", "beneficiary_id"]

# lookup tables: (file/table name, columns, rows)  -- ids are 1-based unless noted
LOOKUPS = {
    "request_statuses":   (["req_status_id", "req_status"],
                           ["CREATED", "MANAGED", "ASSIGNED", "IN_PROGRESS", "RESOLVED",
                            "CANCELLED", "VOLUNTEER_NOT_FOUND"]),
    "request_priorities": (["req_priority_id", "req_priority"], ["LOW", "MEDIUM", "HIGH", "CRITICAL"]),
    "request_types":      (["req_type_id", "req_type"], ["REMOTE", "IN_PERSON"]),
    "request_for":        (["req_for_id", "req_for"], ["SELF", "OTHER"]),
    # id 0 = not lead, id 1 = has lead (case 10 relies on id 1 meaning "has a lead volunteer")
    "request_isleadvol":  (["req_islead_id", "req_islead"], [(0, "FALSE"), (1, "TRUE")]),
}
# status weights, skewed like a live system; every status still appears at least once
STATUS_WEIGHTS = [30, 25, 15, 15, 8, 4, 3]
PRIORITY_WEIGHTS = [30, 45, 22, 3]
TYPE_WEIGHTS = [60, 40]
FOR_WEIGHTS = [70, 30]

# plausible (not real) category tree: (name, [children])
CATEGORY_TREE = [
    ("Food & Groceries", ["Meal delivery", "Grocery pickup", "Food bank referral"]),
    ("Transportation", ["Ride to appointment", "Airport pickup", "Bus pass help"]),
    ("Housing", ["Rent assistance", "Moving help", "Home repair"]),
    ("Health & Wellness", ["Prescription pickup", "Companionship visit", "Mobility aid"]),
    ("Education", ["Tutoring", "Form filling help", "Language practice"]),
    ("Legal & Paperwork", ["Document translation", "Benefits application", "Notary referral"]),
    ("Technology", ["Phone setup", "Online account help", "Video call setup"]),
    ("Other", ["General help"]),
]
N_USERS = 120
USERS_KEY = "user_id"
# --------------------------------------------------------------------------------------

BOUNDARY_TS = datetime(2025, 6, 15, 12, 0, 0, 123456)   # case 2: shared last_updated_at
TS_START = datetime(2025, 1, 1)
TS_SPAN_SECONDS = 330 * 24 * 3600

FIRST = ["Maria", "José", "Aiko", "Wei", "Fatima", "Olivia", "Nguyễn", "Søren", "Priya", "Ahmed",
         "Chloé", "Dmitri", "Lupita", "Kwame", "Sana", "Zoë"]
LAST = ["García", "Hernández", "Müller", "O'Brien", "Zhang", "Patel", "Okafor", "Nakamura",
        "Kowalski", "Rodríguez", "Ibrahim", "Fernández", "Łukasz", "Dubois"]
STREETS = ["Maple Street", "Calle Mayor", "Oak Ave", "Sunset Blvd", "5th Avenue", "Avenida Juárez"]
DIGIT_WORDS = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
               "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}

PLAIN_EN = [
    "Need help carrying groceries up to my apartment this weekend",
    "Looking for someone to drive my mother to her clinic appointment",
    "Could a volunteer help me set up video calls with my family",
    "Need a ride to the airport early Monday morning",
    "Help filling out a housing assistance form please",
    "Need someone to pick up a prescription from the pharmacy",
]
PLAIN_ES = [
    "Necesito ayuda para llevar la compra a mi casa este fin de semana",
    "¿Alguien puede acompañarme a la cita médica? Gracias de antemano",
    "Busco un voluntario que hable español para traducir unos documentos",
    "Necesito transporte al aeropuerto mañana a las 6 de la mañana, por favor",
    "Mi niño necesita clases de inglés después de la escuela",
]
MULTILINE = [
    'Line one of my request.\nLine two: please call after 5pm.\nThanks, "J" says hi',
    'Items needed:\n- milk, eggs, bread\n- "gluten-free" pasta\n- coffee, black',
    'Dear volunteer,\r\nI said "urgent", not "soon", right?\r\nBest, A.',
]
COMMA_QUOTE = [
    'He said, "please come at noon, not before", and hung up',
    'Pickup at 5th, Main, and Oak; bring ID, "photo" preferred',
    'Contact: "Mrs. Lee", lives upstairs, second door, left',
]


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def spoken(digits):
    return " ".join(DIGIT_WORDS[d] for d in digits)


def fit(text, limit):
    return text[:limit]


def pad_exact(text, limit, fill=" Extra detail about the request."):
    while len(text) < limit:
        text += fill
    return text[:limit]


def write_csv(path, cols, rows):
    """Write CSV so that NULL and empty string stay distinct for Postgres \\copy ... CSV:
    NULL -> bare empty field; '' -> quoted "". Output: UTF-8, LF line endings, no BOM."""
    def cell(v):
        if v is None:
            return ""
        if isinstance(v, str):
            if v == "" or any(c in v for c in ',"\n\r') or v != v.strip():
                return '"' + v.replace('"', '""') + '"'
            return v
        return str(v)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(cell(v) for v in r) + "\n")


def weighted(rng, weights):
    return rng.choices(range(1, len(weights) + 1), weights=weights)[0]


def pii_text(rng, kind):
    first, last = rng.choice(FIRST), rng.choice(LAST)
    area = rng.choice(["480", "602", "214", "704"])
    a, b = str(rng.randint(200, 999)), str(rng.randint(1000, 9999))
    if kind == "phone_digits":
        fmt = rng.choice(["({0}) {1}-{2}", "{0}-{1}-{2}", "{0}.{1}.{2}", "+1 {0} {1} {2}", "{0}{1}{2}"])
        return f"Please call me at {fmt.format(area, a, b)} after work", "phone"
    if kind == "phone_words":
        return f"You can reach me at {spoken(area)} {spoken(a)} {spoken(b)}, mornings are best", "phone_spoken"
    if kind == "email":
        return f"Email me at {first.lower()}.{last.lower()}{rng.randint(1,99)}@example.com if I miss your call", "email"
    if kind == "address":
        return f"I live at {rng.randint(10, 9999)} {rng.choice(STREETS)}, Apt {rng.randint(1, 40)}, Dallas, TX 75{rng.randint(100, 299)}", "address"
    return f"My name is {first} {last} and my neighbor {rng.choice(FIRST)} {rng.choice(LAST)} will meet you", "name"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=587)
    ap.add_argument("--out", default="output")
    ap.add_argument("--n-requests", type=int, default=500)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    n = args.n_requests
    os.makedirs(args.out, exist_ok=True)

    # ---- lookups -------------------------------------------------------------------
    for table, (cols, vals) in LOOKUPS.items():
        rows = [v if isinstance(v, tuple) else (i, v) for i, v in enumerate(vals, start=1)]
        write_csv(os.path.join(args.out, f"{table}.csv"), cols, rows)
    n_status = len(LOOKUPS["request_statuses"][1])
    n_prio = len(LOOKUPS["request_priorities"][1])
    n_type = len(LOOKUPS["request_types"][1])
    n_for = len(LOOKUPS["request_for"][1])

    # ---- users (key only) -----------------------------------------------------------
    user_ids = list(range(1, N_USERS + 1))
    write_csv(os.path.join(args.out, "users.csv"), [USERS_KEY], [(u,) for u in user_ids])

    # ---- category tree --------------------------------------------------------------
    cat_rows, map_rows, leaf_ids, cid = [], [], [], 0
    for parent, children in CATEGORY_TREE:
        cid += 1
        parent_id = cid
        cat_rows.append((parent_id, parent, f"{parent} (top-level category)"))
        for ch in children:
            cid += 1
            cat_rows.append((cid, ch, f"{ch} requests"))
            map_rows.append((cid, parent_id))
            leaf_ids.append(cid)
    write_csv(os.path.join(args.out, "help_categories.csv"), ["cat_id", "cat_name", "cat_desc"], cat_rows)
    write_csv(os.path.join(args.out, "help_categories_map.csv"), ["cat_id", "parent_cat_id"], map_rows)
    all_cat_ids = [r[0] for r in cat_rows]

    # ---- requests: base rows ---------------------------------------------------------
    reqs = []
    for i in range(1, n + 1):
        sub = TS_START + timedelta(seconds=rng.randrange(TS_SPAN_SECONDS), microseconds=rng.randrange(1_000_000))
        upd = sub + timedelta(seconds=rng.randrange(0, 20 * 24 * 3600), microseconds=rng.randrange(1_000_000))
        txt = rng.choice(PLAIN_ES) if rng.random() < 0.12 else rng.choice(PLAIN_EN)
        r = {
            "req_id": i,
            "req_user_id": rng.choice(user_ids),
            "req_for_id": weighted(rng, FOR_WEIGHTS),
            "req_islead_id": 0,
            "req_type_id": weighted(rng, TYPE_WEIGHTS),
            "req_priority_id": weighted(rng, PRIORITY_WEIGHTS),
            "req_status_id": weighted(rng, STATUS_WEIGHTS),
            "req_cat_id": rng.choice(all_cat_ids),
            "lead_volunteer_id": None,
            "beneficiary_id": None,
            "req_subj": fit(txt, 60),
            "req_desc": txt + ".",
            "submission_date": sub,
            "last_updated_at": upd,
        }
        reqs.append(r)
    cases = {i: set() for i in range(1, n + 1)}
    pii = {}

    # ---- case 1: skewed nulls (~1.4% have a lead volunteer, ~96% have a beneficiary) ----
    # real shape: 218/221 no lead, 8/221 no beneficiary. Scaled to n, with minimum counts.
    n_lead = max(3, round(n * 3 / 221))
    n_no_benef = max(8, round(n * 8 / 221))
    ids = list(range(1, n + 1))
    lead_set = set(rng.sample(ids, n_lead))
    no_benef = set(rng.sample(ids, n_no_benef))
    for r in reqs:
        if r["req_id"] in lead_set:
            r["lead_volunteer_id"] = rng.choice(user_ids)
            r["req_islead_id"] = 1
        if r["req_id"] not in no_benef:
            r["beneficiary_id"] = rng.choice(user_ids)
    for i in no_benef:
        cases[i].add(1)
    for i in lead_set:
        cases[i].add(1)

    pool = [i for i in ids if i not in lead_set]  # rows free to take special treatment
    rng.shuffle(pool)

    def take(k):
        out, pool[:] = pool[:k], pool[k:]
        return out

    # ---- case 10: islead=1 but lead_volunteer_id NULL (~9 flagged vs 3 recorded in live data) ----
    for i in take(max(6, round(n * 6 / 221))):
        reqs[i - 1]["req_islead_id"] = 1
        reqs[i - 1]["lead_volunteer_id"] = None
        cases[i].add(10)
    # also keep some rows where islead=0 AND lead present is NOT generated: lead rows are all islead=1.

    # ---- case 2: rows sharing one last_updated_at to the microsecond ------------------
    shared = take(10)
    for i in shared:
        r = reqs[i - 1]
        r["submission_date"] = BOUNDARY_TS - timedelta(days=rng.randint(1, 60), seconds=rng.randrange(86400))
        r["last_updated_at"] = BOUNDARY_TS
        cases[i].add(2)
    # neighbours 1 microsecond either side of the boundary
    for delta, i in zip((-1, +1), take(2)):
        r = reqs[i - 1]
        r["submission_date"] = BOUNDARY_TS - timedelta(days=5)
        r["last_updated_at"] = BOUNDARY_TS + timedelta(microseconds=delta)
        cases[i].add(2)

    # ---- case 3: last_updated_at earlier than submission_date --------------------------
    for i in take(5):
        r = reqs[i - 1]
        r["last_updated_at"] = r["submission_date"] - timedelta(seconds=rng.randint(1, 3 * 86400), microseconds=rng.randrange(1000000))
        cases[i].add(3)

    # ---- case 4: newlines, commas, double quotes --------------------------------------
    for k, i in enumerate(take(9)):
        r = reqs[i - 1]
        src = (MULTILINE + COMMA_QUOTE)[k % 6]
        r["req_desc"] = src
        r["req_subj"] = 'Help, "urgent"' if k % 2 else "Groceries, rides, and more"
        cases[i].add(4)

    # ---- case 5: non-ASCII --------------------------------------------------------------
    nonascii = ["Necesito ayuda: ¿pueden traducir mi carta? ¡Gracias!", "我需要帮助翻译文件，谢谢",
                "Ayuda con el niño – cita médica en español", "Merci de m'aider à remplir le formulaire, très urgent ☺",
                "Мне нужна помощь с продуктами", "Pomóż mi proszę — zakupy dla seniora",
                "Necesito transporte a la clínica; mañana a las 7:30"]
    for k, i in enumerate(take(len(nonascii))):
        r = reqs[i - 1]
        r["req_desc"] = nonascii[k]
        r["req_subj"] = fit(nonascii[k], 40)
        cases[i].add(5)

    # ---- case 6: planted PII (flagged in requests_pii_flags.csv) ------------------------
    kinds = ["phone_digits"] * 5 + ["phone_words"] * 3 + ["email"] * 4 + ["address"] * 4 + ["name"] * 5
    for k, i in enumerate(take(len(kinds))):
        text, tag = pii_text(rng, kinds[k])
        reqs[i - 1]["req_desc"] = text
        pii[i] = tag
        cases[i].add(6)
    # a couple of PII rows with a non-English name, plus one mixing several PII types
    for i in take(2):
        reqs[i - 1]["req_desc"] = "Soy José Hernández Ñúñez, llámame al 480-555-0142 o escribe a jose.hernandez@example.com"
        pii[i] = "name;phone;email"
        cases[i].update({5, 6})
    i = take(1)[0]
    reqs[i - 1]["req_desc"] = f"Call four eight zero five five five 0 1 9 9, I live at 221 Baker Street, Austin TX"
    pii[i] = "phone_spoken;address"
    cases[i].add(6)

    # ---- case 7: empty strings vs NULL in every nullable text column --------------------
    for col in NULLABLE_TEXT:
        for i in take(3):
            reqs[i - 1][col] = ""
            cases[i].add(7)
        for i in take(3):
            reqs[i - 1][col] = None
            cases[i].add(7)

    # ---- case 8: max-length values -------------------------------------------------------
    for i in take(2):
        reqs[i - 1]["req_subj"] = pad_exact("Need a ride to the clinic", SUBJ_MAX, " and back home again.")
        reqs[i - 1]["req_desc"] = pad_exact("Please help with transport and groceries.", DESC_MAX)
        cases[i].add(8)
    for i in take(1):   # multibyte chars at max char length
        reqs[i - 1]["req_subj"] = pad_exact("Ayuda: ", SUBJ_MAX, "ñ")
        reqs[i - 1]["req_desc"] = pad_exact("Necesito ayuda con ", DESC_MAX, "é")
        cases[i].update({5, 8})

    # ---- case 9: every lookup value used by >= 1 request --------------------------------
    for col, count in (("req_status_id", n_status), ("req_priority_id", n_prio),
                       ("req_type_id", n_type), ("req_for_id", n_for)):
        for v in range(1, count + 1):
            if not any(r[col] == v for r in reqs):
                reqs[take(1)[0] - 1][col] = v
        # tag the least-common values so they are findable
    rare = {"req_status_id": [5, 6, 7], "req_priority_id": [4]}
    for col, vals in rare.items():
        for v in vals:
            # pin one dedicated row per rare value (RESOLVED/CANCELLED/VOLUNTEER_NOT_FOUND/CRITICAL)
            i = take(1)[0]
            reqs[i - 1][col] = v
            cases[i].add(9)
    for r in reqs:   # make sure no category ids are unused leaf... (all categories are valid refs)
        pass

    # final guarantee check for case 9
    for col, count in (("req_status_id", n_status), ("req_priority_id", n_prio),
                       ("req_type_id", n_type), ("req_for_id", n_for)):
        assert {r[col] for r in reqs} == set(range(1, count + 1)), col
    assert {r["req_islead_id"] for r in reqs} == {0, 1}

    # ---- write requests ------------------------------------------------------------------
    def row(r):
        out = []
        for c in REQUESTS_COLS:
            v = r[c]
            out.append(fmt_ts(v) if isinstance(v, datetime) else v)
        return out

    write_csv(os.path.join(args.out, "requests.csv"), REQUESTS_COLS, [row(r) for r in reqs])
    write_csv(os.path.join(args.out, "requests_pii_flags.csv"), ["req_id", "pii_types"],
              [(i, pii[i]) for i in sorted(pii)])
    write_csv(os.path.join(args.out, "requests_case_map.csv"), ["req_id", "cases"],
              [(i, ";".join(map(str, sorted(c)))) for i, c in cases.items() if c])

    # ---- case 11: broken-reference fixture (separate file, NOT loadable into Postgres) ----
    broken = []
    base_sub = datetime(2025, 7, 1, 9, 30, 0, 111111)
    for k, (col, bad) in enumerate([("req_user_id", 999999), ("req_cat_id", 999999),
                                    ("req_status_id", 99), ("req_priority_id", 99),
                                    ("beneficiary_id", 999999), ("lead_volunteer_id", 999999)]):
        r = dict(reqs[k])
        r["req_id"] = 900001 + k
        r[col] = bad
        if col == "lead_volunteer_id":
            r["req_islead_id"] = 1
        r["req_subj"] = f"BROKEN REF: {col}={bad}"
        r["req_desc"] = f"Fixture row: {col} points at a row that does not exist"
        r["submission_date"] = base_sub + timedelta(minutes=k)
        r["last_updated_at"] = base_sub + timedelta(minutes=k, hours=1)
        broken.append(row(r))
    write_csv(os.path.join(args.out, "requests_broken_refs.csv"), REQUESTS_COLS, broken)

    # ---- self-check -------------------------------------------------------------------------
    cat_set, user_set = set(all_cat_ids), set(user_ids)
    for r in reqs:
        assert r["req_user_id"] in user_set and r["req_cat_id"] in cat_set
        for c in NULLABLE_REFS:
            assert r[c] is None or r[c] in user_set
        if r["req_subj"] is not None:
            assert len(r["req_subj"]) <= SUBJ_MAX
        if r["req_desc"] is not None:
            assert len(r["req_desc"]) <= DESC_MAX
    print(f"wrote {n} requests, {len(broken)} broken-ref rows to {args.out}/ (seed={args.seed})")


if __name__ == "__main__":
    main()
