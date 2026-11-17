#!/usr/bin/env python3
"""Mock data generator for the `requests` table and the tables it references (issue #587).

Usage:
    python3 generate_mock_data.py [--seed 587] [--out ./output] [--n-requests 500]

Same seed => byte-identical output. No database access, no real or dev data: everything is
generated from the definitions in the SCHEMA section, which mirror saayam_schema.sql (issue #573).
"""
import argparse
import os
import random
from datetime import datetime, timedelta

# --------------------------------------------------------------------------------------
# SCHEMA (mirrors saayam_schema.sql)
# --------------------------------------------------------------------------------------
REQUESTS_COLS = [
    "req_id", "creator_id", "beneficiary_id", "lead_volunteer_id", "req_cat_id",
    "req_for_id", "req_islead_id", "req_type_id", "req_priority_id", "req_status_id",
    "req_subj", "req_desc", "req_doc_link", "audio_req_desc", "deletion_reason",
    "req_loc", "created_loc", "iscalamity", "to_public",
    "submission_date", "serviced_date", "last_updated_at",
]
SUBJ_MAX, DESC_MAX, AUDIO_MAX = 125, 255, 255      # varchar(125), varchar(255), varchar(255)
NULLABLE_TEXT = ["req_doc_link", "audio_req_desc", "deletion_reason"]   # req_subj/req_desc are NOT NULL
NOT_NULL_TEXT = ["req_subj", "req_desc"]
NULLABLE_REFS = ["beneficiary_id", "lead_volunteer_id"]

# lookup tables, 0-based ids exactly as documented in saayam_schema.sql:
# name -> (csv columns, [(id, value, description)], sampling weights by id)
LOOKUPS = {
    "request_for": (["req_for_id", "req_for", "req_for_desc"],
                    [(0, "SELF", "Request is for the requester"), (1, "OTHER", "Request is on behalf of someone else")],
                    [70, 30]),
    "request_isleadvol": (["req_islead_id", "req_islead", "req_islead_desc"],
                          [(0, "NO", "No lead volunteer"), (1, "YES", "Has a lead volunteer")], [0, 0]),
    "request_types": (["req_type_id", "req_type", "req_type_desc"],
                      [(0, "IN_PERSON", "Volunteer helps in person"), (1, "REMOTE", "Volunteer helps remotely")],
                      [40, 60]),
    "request_priorities": (["req_priority_id", "req_priority", "req_priority_desc"],
                           [(0, "LOW", "Low priority"), (1, "MEDIUM", "Medium priority"),
                            (2, "HIGH", "High priority"), (3, "CRITICAL", "Critical priority")],
                           [30, 45, 22, 0]),
    "request_statuses": (["req_status_id", "req_status", "req_status_desc"],
                         [(0, "CREATED", "Request created"), (1, "MATCHING_VOLUNTEER", "Looking for a volunteer"),
                          (2, "IN_PROGRESS", "Volunteer working on it"), (3, "RESOLVED", "Request resolved"),
                          (4, "CANCELLED", "Cancelled by requester"), (5, "DELETED", "Deleted"),
                          (6, "RATED_BY_REQUESTER", "Requester rated the volunteer"),
                          (7, "RATED_BY_VOLUNTEER", "Volunteer rated the requester"),
                          (8, "VOLUNTEER_NOT_FOUND", "No volunteer could be matched")],
                         [40, 25, 15, 0, 0, 4, 3, 3, 0]),
}
# status ids with special handling
S_RESOLVED, S_CANCELLED, S_DELETED, S_RATED_REQ, S_RATED_VOL, S_VNF = 3, 4, 5, 6, 7, 8
P_CRITICAL = 3

N_USERS = 120
def user_id(n): return f"SID-00-000-000-000-000-{n:03d}"
def req_id(n): return f"REQ-000-000-000-{n:04d}"

# category tree: keys are hierarchy paths ('1', '1.3', '1.3.1') like the live table
CATEGORY_TREE = [
    ("Food & Groceries", [("Meal delivery", ["Hot meals", "Meal kits"]), ("Grocery pickup", []),
                          ("Food bank referral", [])]),
    ("Transportation", [("Ride to appointment", ["Medical", "Legal"]), ("Airport pickup", []), ("Bus pass help", [])]),
    ("Housing", [("Rent assistance", []), ("Moving help", ["Packing", "Lifting"]), ("Home repair", [])]),
    ("Health & Wellness", [("Prescription pickup", []), ("Companionship visit", []), ("Mobility aid", [])]),
    ("Education", [("Tutoring", ["Math", "English"]), ("Form filling help", []), ("Language practice", [])]),
    ("Legal & Paperwork", [("Document translation", []), ("Benefits application", []), ("Notary referral", [])]),
    ("Technology", [("Phone setup", []), ("Online account help", []), ("Video call setup", [])]),
    ("Other", [("General help", [])]),
]
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
DELETION_REASONS = ["Duplicate request", "Requester no longer needs help", "Entered by mistake"]


def fmt_ts(dt): return dt.strftime("%Y-%m-%d %H:%M:%S.%f")
def spoken(d): return " ".join(DIGIT_WORDS[c] for c in d)


def pad_exact(text, limit, fill=" Extra detail about the request."):
    while len(text) < limit:
        text += fill
    return text[:limit]


def write_csv(path, cols, rows):
    """NULL -> bare empty field; '' -> quoted "" (Postgres COPY CSV keeps them distinct).
    UTF-8, LF line endings, no BOM."""
    def cell(v):
        if v is None:
            return ""
        if isinstance(v, bool):
            return "t" if v else "f"
        if isinstance(v, str):
            if v == "" or any(c in v for c in ',"\n\r') or v != v.strip():
                return '"' + v.replace('"', '""') + '"'
            return v
        return str(v)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(cols) + "\n")
        for r in rows:
            f.write(",".join(cell(v) for v in r) + "\n")


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
        return f"Email me at {first.lower()}.{last.lower()}{rng.randint(1, 99)}@example.com if I miss your call", "email"
    if kind == "address":
        return (f"I live at {rng.randint(10, 9999)} {rng.choice(STREETS)}, Apt {rng.randint(1, 40)}, "
                f"Dallas, TX 75{rng.randint(100, 299)}"), "address"
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

    # ---- lookups ---------------------------------------------------------------------
    for table, (cols, vals, _) in LOOKUPS.items():
        write_csv(os.path.join(args.out, f"{table}.csv"), cols, vals)

    def pick(table):
        _, vals, w = LOOKUPS[table]
        return rng.choices([v[0] for v in vals], weights=w)[0]

    # ---- users (key column only) ------------------------------------------------------
    users = [user_id(i) for i in range(1, N_USERS + 1)]
    write_csv(os.path.join(args.out, "users.csv"), ["user_id"], [(u,) for u in users])

    # ---- category tree ----------------------------------------------------------------
    cat_rows, map_rows = [], []
    for i, (name, kids) in enumerate(CATEGORY_TREE, start=1):
        cat_rows.append((str(i), name, f"{name} (top-level category)"))
        map_rows.append((None, str(i)))
        for j, (kname, grandkids) in enumerate(kids, start=1):
            kp = f"{i}.{j}"
            cat_rows.append((kp, kname, f"{kname} requests"))
            map_rows.append((str(i), kp))
            for k, gname in enumerate(grandkids, start=1):
                gp = f"{kp}.{k}"
                cat_rows.append((gp, f"{kname}: {gname}", f"{gname} help within {kname}"))
                map_rows.append((kp, gp))
    write_csv(os.path.join(args.out, "help_categories.csv"), ["cat_id", "cat_name", "cat_desc"], cat_rows)
    write_csv(os.path.join(args.out, "help_categories_map.csv"), ["parent_id", "child_id"], map_rows)
    cat_ids = [r[0] for r in cat_rows]

    # ---- requests: base rows ----------------------------------------------------------
    reqs = []
    for i in range(1, n + 1):
        sub = TS_START + timedelta(seconds=rng.randrange(TS_SPAN_SECONDS), microseconds=rng.randrange(1_000_000))
        upd = sub + timedelta(seconds=rng.randrange(0, 20 * 24 * 3600), microseconds=rng.randrange(1_000_000))
        txt = rng.choice(PLAIN_ES) if rng.random() < 0.12 else rng.choice(PLAIN_EN)
        loc = (lambda: f"SRID=4326;POINT({-97.2 + rng.random() * 0.8:.6f} {32.5 + rng.random() * 0.6:.6f})")
        reqs.append({
            "req_id": req_id(i), "creator_id": rng.choice(users), "beneficiary_id": None,
            "lead_volunteer_id": None, "req_cat_id": rng.choice(cat_ids),
            "req_for_id": pick("request_for"), "req_islead_id": 0, "req_type_id": pick("request_types"),
            "req_priority_id": pick("request_priorities"), "req_status_id": pick("request_statuses"),
            "req_subj": txt[:60], "req_desc": txt + ".",
            "req_doc_link": f"https://example.com/docs/{i:04d}.pdf" if rng.random() < 0.15 else None,
            "audio_req_desc": "Audio note: " + txt[:50] if rng.random() < 0.05 else None,
            "deletion_reason": None,
            "req_loc": loc() if rng.random() < 0.9 else None,
            "created_loc": loc() if rng.random() < 0.9 else None,
            "iscalamity": rng.choice([True, False, None]) if rng.random() < 0.3 else False,
            "to_public": rng.random() < 0.2,
            "submission_date": sub, "serviced_date": None, "last_updated_at": upd,
        })
    cases = {i: set() for i in range(1, n + 1)}
    pii = {}
    idx = lambda i: reqs[i - 1]

    # ---- case 1: skewed nulls (live: 218/221 no lead, 8/221 no beneficiary) -------------
    n_lead = max(3, round(n * 3 / 221))
    n_no_benef = max(8, round(n * 8 / 221))
    ids = list(range(1, n + 1))
    lead_set = set(rng.sample(ids, n_lead))
    no_benef = set(rng.sample(ids, n_no_benef))
    for r in reqs:
        i = int(r["req_id"][-4:])
        if i in lead_set:
            r["lead_volunteer_id"] = rng.choice(users)
            r["req_islead_id"] = 1
            cases[i].add(1)
        if i not in no_benef:
            r["beneficiary_id"] = rng.choice(users)
        else:
            cases[i].add(1)

    pool = [i for i in ids if i not in lead_set]
    rng.shuffle(pool)

    def take(k):
        out = pool[:k]
        del pool[:k]
        return out

    # ---- case 10: islead = 1 (YES) but lead_volunteer_id NULL ---------------------------
    for i in take(max(6, round(n * 6 / 221))):
        idx(i)["req_islead_id"] = 1
        cases[i].add(10)

    # ---- case 2: rows sharing one last_updated_at to the microsecond ---------------------
    for i in take(10):
        r = idx(i)
        r["submission_date"] = BOUNDARY_TS - timedelta(days=rng.randint(1, 60), seconds=rng.randrange(86400))
        r["last_updated_at"] = BOUNDARY_TS
        cases[i].add(2)
    for delta, i in zip((-1, +1), take(2)):      # one row 1 microsecond either side
        r = idx(i)
        r["submission_date"] = BOUNDARY_TS - timedelta(days=5)
        r["last_updated_at"] = BOUNDARY_TS + timedelta(microseconds=delta)
        cases[i].add(2)

    # ---- case 3: last_updated_at earlier than submission_date ----------------------------
    for i in take(5):
        r = idx(i)
        r["last_updated_at"] = r["submission_date"] - timedelta(seconds=rng.randint(1, 3 * 86400),
                                                                microseconds=rng.randrange(1_000_000))
        cases[i].add(3)

    # ---- case 4: embedded newlines, commas, double quotes --------------------------------
    for k, i in enumerate(take(9)):
        r = idx(i)
        r["req_desc"] = (MULTILINE + COMMA_QUOTE)[k % 6]
        r["req_subj"] = 'Help, "urgent"' if k % 2 else "Groceries, rides, and more"
        cases[i].add(4)

    # ---- case 5: non-ASCII ---------------------------------------------------------------
    nonascii = ["Necesito ayuda: ¿pueden traducir mi carta? ¡Gracias!", "我需要帮助翻译文件，谢谢",
                "Ayuda con el niño – cita médica en español", "Merci de m'aider à remplir le formulaire, très urgent ☺",
                "Мне нужна помощь с продуктами", "Pomóż mi proszę — zakupy dla seniora",
                "Necesito transporte a la clínica; mañana a las 7:30"]
    for k, i in enumerate(take(len(nonascii))):
        idx(i)["req_desc"] = nonascii[k]
        idx(i)["req_subj"] = nonascii[k][:40]
        cases[i].add(5)

    # ---- case 6: planted PII (listed in requests_pii_flags.csv) ---------------------------
    kinds = ["phone_digits"] * 5 + ["phone_words"] * 3 + ["email"] * 4 + ["address"] * 4 + ["name"] * 5
    for k, i in enumerate(take(len(kinds))):
        text, tag = pii_text(rng, kinds[k])
        idx(i)["req_desc"] = text
        pii[i] = tag
        cases[i].add(6)
    for i in take(2):
        idx(i)["req_desc"] = "Soy José Hernández Ñúñez, llámame al 480-555-0142 o escribe a jose.hernandez@example.com"
        pii[i] = "name;phone;email"
        cases[i].update({5, 6})
    i = take(1)[0]
    idx(i)["req_desc"] = "Call four eight zero five five five 0 1 9 9, I live at 221 Baker Street, Austin TX"
    pii[i] = "phone_spoken;address"
    cases[i].add(6)

    # ---- case 7: empty string vs NULL in every nullable text column ------------------------
    # nullable text columns: req_doc_link, audio_req_desc, deletion_reason  (NULL is the common
    # value everywhere else). req_subj/req_desc are NOT NULL, so they get empty strings only.
    for col in NULLABLE_TEXT + NOT_NULL_TEXT:
        for i in take(3 if col in NULLABLE_TEXT else 2):
            idx(i)[col] = ""
            cases[i].add(7)

    # ---- case 8: values at the maximum column length --------------------------------------
    for i in take(2):
        idx(i)["req_subj"] = pad_exact("Need a ride to the clinic", SUBJ_MAX, " and back home again.")
        idx(i)["req_desc"] = pad_exact("Please help with transport and groceries.", DESC_MAX)
        idx(i)["audio_req_desc"] = pad_exact("Audio note: ", AUDIO_MAX)
        cases[i].add(8)
    i = take(1)[0]    # multibyte characters filling the limit (length is in characters)
    idx(i)["req_subj"] = pad_exact("Ayuda: ", SUBJ_MAX, "ñ")
    idx(i)["req_desc"] = pad_exact("Necesito ayuda con ", DESC_MAX, "é")
    cases[i].update({5, 8})

    # ---- case 9: every lookup value used by at least one request ---------------------------
    for col, s in (("req_status_id", S_RESOLVED), ("req_status_id", S_CANCELLED),
                   ("req_status_id", S_VNF), ("req_priority_id", P_CRITICAL)):
        i = take(1)[0]
        idx(i)[col] = s
        cases[i].add(9)
    for col, table in (("req_status_id", "request_statuses"), ("req_priority_id", "request_priorities"),
                       ("req_type_id", "request_types"), ("req_for_id", "request_for"),
                       ("req_islead_id", "request_isleadvol")):
        for v in (x[0] for x in LOOKUPS[table][1]):
            if not any(r[col] == v for r in reqs):
                i = take(1)[0]
                idx(i)[col] = v
                cases[i].add(9)

    # ---- derived columns (after all status changes) ---------------------------------------
    for r in reqs:
        i = int(r["req_id"][-4:])
        if r["req_status_id"] in (S_RESOLVED, S_RATED_REQ, S_RATED_VOL):
            r["serviced_date"] = r["submission_date"] + timedelta(days=rng.randint(1, 15), seconds=rng.randrange(86400),
                                                                  microseconds=rng.randrange(1_000_000))
        if r["req_status_id"] == S_DELETED and r["deletion_reason"] is None:
            r["deletion_reason"] = rng.choice(DELETION_REASONS)

    for col, table in (("req_status_id", "request_statuses"), ("req_priority_id", "request_priorities"),
                       ("req_type_id", "request_types"), ("req_for_id", "request_for"),
                       ("req_islead_id", "request_isleadvol")):
        assert {r[col] for r in reqs} == {x[0] for x in LOOKUPS[table][1]}, col

    # ---- write requests --------------------------------------------------------------------
    def row(r):
        return [fmt_ts(r[c]) if isinstance(r[c], datetime) else r[c] for c in REQUESTS_COLS]

    write_csv(os.path.join(args.out, "requests.csv"), REQUESTS_COLS, [row(r) for r in reqs])
    write_csv(os.path.join(args.out, "requests_pii_flags.csv"), ["req_id", "pii_types"],
              [(req_id(i), pii[i]) for i in sorted(pii)])
    write_csv(os.path.join(args.out, "requests_case_map.csv"), ["req_id", "cases"],
              [(req_id(i), ";".join(map(str, sorted(c)))) for i, c in cases.items() if c])

    # ---- case 11: broken-reference fixture (separate file; NOT loadable into the schema) ----
    broken, base_sub = [], datetime(2025, 7, 1, 9, 30, 0, 111111)
    for k, (col, bad) in enumerate([("creator_id", "SID-99-999-999-999-999-999"), ("req_cat_id", "99.99"),
                                    ("req_status_id", 99), ("req_priority_id", 99),
                                    ("beneficiary_id", "SID-99-999-999-999-999-998"),
                                    ("lead_volunteer_id", "SID-99-999-999-999-999-997")]):
        r = dict(reqs[k])
        r["req_id"] = f"REQ-999-999-999-{k + 1:04d}"
        r[col] = bad
        if col == "lead_volunteer_id":
            r["req_islead_id"] = 1
        r["req_subj"] = f"BROKEN REF: {col}={bad}"
        r["req_desc"] = f"Fixture row: {col} points at a row that does not exist"
        r["submission_date"] = base_sub + timedelta(minutes=k)
        r["last_updated_at"] = base_sub + timedelta(minutes=k, hours=1)
        broken.append(row(r))
    write_csv(os.path.join(args.out, "requests_broken_refs.csv"), REQUESTS_COLS, broken)

    # ---- self-check against the schema ------------------------------------------------------
    uset, cset = set(users), set(cat_ids)
    for r in reqs:
        assert r["creator_id"] in uset and r["req_cat_id"] in cset
        for c in NULLABLE_REFS:
            assert r[c] is None or r[c] in uset
        assert r["req_subj"] is not None and len(r["req_subj"]) <= SUBJ_MAX
        assert r["req_desc"] is not None and len(r["req_desc"]) <= DESC_MAX
        assert r["audio_req_desc"] is None or len(r["audio_req_desc"]) <= AUDIO_MAX
        assert len(r["req_id"]) <= 255 and len(r["req_cat_id"]) <= 50
    assert any(len(r["req_subj"]) == SUBJ_MAX for r in reqs) and any(len(r["req_desc"]) == DESC_MAX for r in reqs)
    print(f"wrote {n} requests, {len(broken)} broken-ref rows to {args.out}/ (seed={args.seed})")


if __name__ == "__main__":
    main()
