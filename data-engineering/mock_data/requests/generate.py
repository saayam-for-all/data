"""Deterministic synthetic data for the requests table and every table it references (Issue #587).

Usage:
    python3 data-engineering/mock_data/requests/generate.py [--seed 587] [--out DIR]

Everything is derived from the seed and fixed dates: no clock, no database, no network.
Same seed -> byte-identical files.

CSV convention (matches PostgreSQL `COPY ... WITH (FORMAT csv, HEADER true, NULL '\\N')`):
    SQL NULL      -> \\N   (unquoted)
    empty string  -> an empty field
    booleans      -> true / false
    geometry      -> EWKT, e.g. SRID=4326;POINT(-77.436000 37.540700)
    timestamps    -> YYYY-MM-DD HH:MM:SS.ffffff (UTC by convention, no time zone)
    UTF-8, NFC-normalised, no BOM, rows end with \\n
"""
import argparse
import csv
import random
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOOKUP_DIR = HERE.parents[2] / "database" / "lookup_tables"

DEFAULT_SEED = 587
N_REQUESTS = 500
N_USERS = 150
N_NULL_BENEFICIARY = 18
N_LEAD_VOLUNTEER = 7  # 493 of 500 have no lead volunteer

NULL_TOKEN = "\\N"
LOOKUP_TS = datetime(2026, 1, 1)
SUBMISSION_START = datetime(2026, 1, 1)

# Identical-timestamp clusters (case 2). The first two sit on a day boundary.
TIE_DAY_END = datetime(2026, 9, 30, 23, 59, 59, 999999)
TIE_MIDNIGHT = datetime(2026, 10, 1, 0, 0, 0, 0)
TIE_MID = datetime(2026, 8, 15, 12, 34, 56, 123456)

SUBJ_MAX = 125
DESC_MAX = 255
AUDIO_MAX = 255

CASE_NAMES = {
    1: "skewed null references",
    2: "identical last_updated_at",
    3: "updated before submitted",
    4: "csv special characters",
    5: "unicode and spanish",
    6: "synthetic personal details",
    7: "empty string vs null",
    8: "exact max length",
    9: "rare lookup values",
    10: "islead yes with null lead",
    11: "broken foreign key",
}

# Columns in schema order. users is the key column only.
TABLES = {
    "help_categories": ["cat_id", "cat_name", "cat_desc", "last_updated_at"],
    "help_categories_map": ["parent_id", "child_id", "last_updated_at"],
    "request_for": ["req_for_id", "req_for", "req_for_desc", "last_updated_at"],
    "request_isleadvol": ["req_islead_id", "req_islead", "req_islead_desc", "last_updated_at"],
    "request_types": ["req_type_id", "req_type", "req_type_desc", "last_updated_at"],
    "request_priorities": ["req_priority_id", "req_priority", "req_priority_desc", "last_updated_at"],
    "request_statuses": ["req_status_id", "req_status", "req_status_desc", "last_updated_at"],
    "users": ["user_id"],
    "requests": [
        "req_id", "creator_id", "beneficiary_id", "lead_volunteer_id", "req_cat_id", "req_for_id",
        "req_islead_id", "req_type_id", "req_priority_id", "req_status_id", "req_subj", "req_desc",
        "req_doc_link", "audio_req_desc", "deletion_reason", "req_loc", "created_loc", "iscalamity",
        "to_public", "submission_date", "serviced_date", "last_updated_at",
    ],
}

# Fixed lookup rows come from the repo's lookup CSVs (table, file, column prefix).
LOOKUP_FILES = [
    ("request_for", "request_for.csv", "req_for"),
    ("request_isleadvol", "request_isleadvol.csv", "req_islead"),
    ("request_types", "request_type.csv", "req_type"),
    ("request_priorities", "request_priority.csv", "req_priority"),
    ("request_statuses", "request_status.csv", "req_status"),
]
STATUS_VOLUNTEER_NOT_FOUND = (8, "VOLUNTEER_NOT_FOUND")  # in the schema, absent from the lookup CSV
STATUS_SERVICED = (3, 6, 7)  # RESOLVED, RATED_BY_REQUESTER, RATED_BY_VOLUNTEER
STATUS_DELETED = 5

FK_COLUMNS = [  # requests foreign keys, with a value that matches no row
    ("creator_id", "SID-00-000-000-000-999-999"),
    ("beneficiary_id", "SID-00-000-000-000-999-998"),
    ("lead_volunteer_id", "SID-00-000-000-000-999-997"),
    ("req_cat_id", "99.99.99"),
    ("req_for_id", 99),
    ("req_islead_id", 99),
    ("req_type_id", 99),
    ("req_priority_id", 99),
    ("req_status_id", 99),
]

CITIES = [
    ("Richmond, VA", -77.4360, 37.5407), ("Norfolk, VA", -76.2859, 36.8508),
    ("Austin, TX", -97.7431, 30.2672), ("Denver, CO", -104.9903, 39.7392),
    ("Chicago, IL", -87.6298, 41.8781), ("Seattle, WA", -122.3321, 47.6062),
    ("Phoenix, AZ", -112.0740, 33.4484), ("Atlanta, GA", -84.3880, 33.7490),
    ("Boston, MA", -71.0589, 42.3601), ("Miami, FL", -80.1918, 25.7617),
    ("San Jose, CA", -121.8863, 37.3382), ("Columbus, OH", -82.9988, 39.9612),
]

SUBJ_EN = [
    "Need groceries for my family this week", "Looking for a ride to a medical appointment",
    "Help filling out housing paperwork", "Winter coats needed for two children",
    "Help moving furniture on Saturday", "Tutoring for high school math",
    "Assistance setting up utilities", "Companionship visit for an elderly neighbor",
]
DESC_EN_A = [
    "We recently lost our main source of income.", "I recently moved to the area and do not know anyone yet.",
    "My car is in the shop and I cannot travel on my own.", "There is an urgent deadline coming up this week.",
]
DESC_EN_B = [
    "Any amount of help would be appreciated.", "I can be reached through the app at any time.",
    "A weekend visit would work best for us.",
]
SUBJ_ES = [
    "Necesito comida para mi familia esta semana", "Busco transporte a una cita médica",
    "Ayuda con papeles de vivienda", "Abrigos de invierno para dos niños",
    "Ayuda para mudar muebles el sábado", "Clases de matemáticas para secundaria",
    "Ayuda para contratar servicios públicos", "Visita de compañía para un vecino mayor",
]
DESC_ES_A = [
    "Perdimos nuestra principal fuente de ingresos.", "Me mudé hace poco y no conozco a nadie.",
    "Mi carro está en el taller y no puedo moverme sola.", "Hay una fecha límite urgente esta semana.",
]
DESC_ES_B = [
    "Cualquier ayuda será bienvenida.", "Pueden contactarme por la aplicación a cualquier hora.",
    "Preferimos una visita el fin de semana.",
]
DELETION_REASONS = [
    "Duplicate request submitted by mistake", "Requester no longer needs help",
    "Entered in error; see follow-up request", "Solicitud duplicada por error",
]

# Case 4: embedded newlines, commas, quotes.
CSV_SPECIAL = [
    {"desc": "Need help this week.\nPlease call after 5 pm."},
    {"desc": "Need a ride on Monday.\r\nPlease confirm by message."},
    {"desc": "Rice, beans, milk, eggs, and bread for a family of four, if possible."},
    {"desc": 'My landlord said "pay by Friday or leave" and I need advice.'},
    {"desc": 'He wrote: "Hi, I\'m stuck,\nplease help", then left.'},
    {"subj": 'Re: "Urgent", need ride to clinic, 9 am'},
    {"subj": "NULL", "desc": "C:\\Users\\temp\\new folder; it's 'quoted'; semicolon; --dash"},
]

# Case 5: Unicode and Spanish.
UNICODE_PAIRS = [
    ("Necesito ayuda: ¿quién puede acompañarme?",
     "Mi niña tiene fiebre y necesito llevarla al médico mañana. ¡Gracias por su ayuda!"),
    ("Ayuda con trámites — señor mayor",
     "Soy un señor mayor y no entiendo los papeles del alquiler; necesito orientación."),
    ("मदद चाहिए: राशन", "हमें इस हफ्ते परिवार के लिए राशन की ज़रूरत है।"),
    ("نحتاج إلى مساعدة", "نحتاج إلى مساعدة في الحصول على الطعام لعائلتنا هذا الأسبوع."),
    ("需要帮助：食物", "我们这周需要食物和去医院的交通。"),
    ("Café & niños 🙏", "Necesitamos ayuda con la comida 🍞 y transporte 🚌 para los niños, por favor 🙏."),
    ("Ça fait mal — besoin d'aide", "Naïve question: où puis-je trouver de l'aide? Déjà essayé plusieurs fois."),
    ("Привет, нужна помощь", "Нам нужна помощь с продуктами и одеждой для детей на этой неделе."),
]

# Case 6: synthetic personal details (reserved 555-01xx numbers, example.test emails, placeholder names).
PII_CASES = [
    {"text": "Please call me at {0} after 6 pm, my phone is the best way to reach me.",
     "items": [("phone", fmt, v)]}
    for fmt, v in [
        ("parenthesized", "(202) 555-0143"), ("dashed", "202-555-0144"), ("dotted", "202.555.0145"),
        ("e164_spaced", "+1 202 555 0146"), ("digits_only", "2025550147"),
        ("e164_dashed", "+1-202-555-0148"), ("leading_one", "1 (202) 555-0149"),
    ]
] + [
    {"text": text, "items": [("phone", fmt, v)]}
    for text, fmt, v in [
        ("You can reach me at {0}.", "words_en", "two zero two, five five five, zero one five zero"),
        ("You can reach me at {0}.", "words_en_compact", "two oh two five five five oh one five one"),
        ("Pueden llamarme al {0}.", "words_es", "dos cero dos, cinco cinco cinco, cero uno cinco dos"),
        ("You can reach me at {0}.", "words_en_hyphen", "two zero two - five five five - zero one five three"),
    ]
] + [
    {"text": "Write to me at {0} please.", "items": [("email", "plain", v)]}
    for v in ["maria.testpersona@example.test", "alex_testperson+help@example.test",
              "j.doe.synthetic@mail.example.test"]
] + [
    {"text": "My name is {0} and I live at {1}.",
     "items": [("name", "full_name", name), ("address", "street_address", addr)]}
    for name, addr in [
        ("Alex Testperson", "100 Placeholder Street, Exampleville, VA 00000"),
        ("María Testpersona", "22 Muestra Avenida, Ejemplo City, TX 00000"),
        ("Sam Q. Syntheticson", "7 Fixture Road, Apt 3B, Sampleton, CO 00000"),
        ("Priya Testkumar", "15 Dummy Lane, Mockville, WA 00000"),
    ]
] + [
    {"text": "{0} here, phone {1}, email {2}.",
     "items": [("name", "full_name", name), ("phone", fmt, phone), ("email", "plain", email)]}
    for name, fmt, phone, email in [
        ("Jordan Placeholder", "dashed", "206-555-0150", "jordan.placeholder@example.test"),
        ("Lucía Ejemplo", "parenthesized", "(512) 555-0151", "lucia.ejemplo@example.test"),
        ("Chris Mockson", "dotted", "303.555.0152", "chris.mockson@example.test"),
    ]
]

MAX_SUBJ_SEEDS = [
    "Need urgent help with groceries and transport this week ",
    "Ñandú: necesito ayuda con comida, transporte y medicinas — gracias ",
    "请帮助我们 需要食物和交通 ",
    "Need a ride to the clinic ",
    "Rice, beans, milk ",
    "🙏 Please help ",
]
MAX_DESC_SEEDS = [
    "We need help with food, transport and medicine for the whole week. ",
    "Necesitamos ayuda urgente: comida, transporte, medicinas y ropa para los niños. ",
    "我们需要食物、交通和药品方面的帮助。 ",
    "He said \"call back later\", then hung up. ",
    "Line one\nLine two\n",
    "🍞🚌🙏 Gracias por todo. ",
]
MAX_AUDIO_SEEDS = [
    "s3://example-synthetic-audio/requests/voice-note-",
    "s3://example-synthetic-audio/solicitudes/nota-de-voz-ñ-",
    "s3://example-synthetic-audio/requests/voice-note-请-",
    "s3://example-synthetic-audio/requests/voice,note-\"q\"-",
]


# ----------------------------------------------------------------------------- CSV output

def _cell(value):
    if value is None:
        return NULL_TOKEN
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="microseconds")
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    return str(value)


def write_csv(path, columns, rows):
    """rows are dicts keyed by column name (extra keys ignored)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_cell(row[c]) for c in columns])


# ----------------------------------------------------------------------------- helpers

def _read_lookup(filename):
    with open(LOOKUP_DIR / filename, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _null(value):
    return None if value in ("NULL", "") else value


def _fit(seed_text, length):
    """Repeat seed_text and cut it to exactly `length` characters (not bytes)."""
    text = (seed_text * (length // len(seed_text) + 2))[:length]
    return text[:-1] + "." if text.endswith((" ", "\n")) else text


def req_id(n):
    return f"REQ-000-000-{n // 10000:03d}-{n % 10000:04d}"


def user_id(n):
    return f"SID-00-000-000-000-000-{n:03d}"


def build_lookups():
    tables = {
        "help_categories": [
            {"cat_id": r["cat_id"], "cat_name": r["cat_name"], "cat_desc": r["cat_desc"],
             "last_updated_at": LOOKUP_TS}
            for r in _read_lookup("help_categories.csv")
        ],
        "help_categories_map": [
            {"parent_id": _null(r["parent_id"]), "child_id": r["child_id"], "last_updated_at": LOOKUP_TS}
            for r in _read_lookup("help_categories_map.csv")
        ],
    }
    for table, filename, prefix in LOOKUP_FILES:
        tables[table] = [
            {f"{prefix}_id": int(r[f"{prefix}_id"]), prefix: r[prefix],
             f"{prefix}_desc": _null(r[f"{prefix}_desc"]), "last_updated_at": LOOKUP_TS}
            for r in _read_lookup(filename)
        ]
    status_id, status_name = STATUS_VOLUNTEER_NOT_FOUND
    statuses = tables["request_statuses"]
    assert status_id not in {r["req_status_id"] for r in statuses}
    statuses.append({"req_status_id": status_id, "req_status": status_name, "req_status_desc": None,
                     "last_updated_at": LOOKUP_TS})
    return tables


def _point(rng, city):
    _, lon, lat = city
    return f"SRID=4326;POINT({lon + rng.uniform(-0.05, 0.05):.6f} {lat + rng.uniform(-0.05, 0.05):.6f})"


def _general_text(rng, city, spanish):
    if spanish:
        subj, a, b = rng.choice(SUBJ_ES), rng.choice(DESC_ES_A), rng.choice(DESC_ES_B)
    else:
        subj, a, b = rng.choice(SUBJ_EN), rng.choice(DESC_EN_A), rng.choice(DESC_EN_B)
    return subj, f"{a} {b} ({city[0]})."


def _micro(rng):
    return rng.randrange(1_000_000)


# ----------------------------------------------------------------------------- requests

def build_requests(rng, users, cat_ids):
    n = N_REQUESTS
    manifest = []

    def note(case_no, rid, column, detail, file="csv/requests.csv"):
        manifest.append({"case_no": case_no, "case_name": CASE_NAMES[case_no], "file": file,
                         "req_id": rid, "column": column, "detail": detail})

    def balanced(k, weights):  # every value appears at least once
        values = list(range(k)) + rng.choices(range(k), weights=weights, k=n - k)
        rng.shuffle(values)
        return values

    for_ids = balanced(2, [70, 30])
    type_ids = balanced(2, [55, 45])
    priority_ids = balanced(4, [30, 40, 22, 8])
    status_ids = balanced(9, [10, 10, 12, 40, 8, 1, 6, 6, 1])
    cats = list(cat_ids) + rng.choices(cat_ids, k=n - len(cat_ids))
    rng.shuffle(cats)

    # Disjoint row sets for the timestamp and text edge cases.
    slots = iter(rng.sample(range(n), 92))

    def take(k):
        return [next(slots) for _ in range(k)]

    tie_day_end, tie_midnight, tie_mid = take(6), take(6), take(5)
    early = take(8)
    csv_special, unicode_rows, pii_rows = take(14), take(16), take(21)
    max_subj, max_desc, max_audio = take(6), take(6), take(4)

    null_beneficiary = set(rng.sample(range(n), N_NULL_BENEFICIARY))
    lead_rows = rng.sample(range(n), N_LEAD_VOLUNTEER)
    lead_set = set(lead_rows)
    yes_without_lead = set(rng.sample([i for i in range(n) if i not in lead_set], 10))

    rows = []
    spanish_rows = set()
    for i in range(n):
        rid = req_id(i + 1)
        creator = rng.choice(users)
        for_id = for_ids[i]
        if i in null_beneficiary:
            beneficiary = None
        elif for_id == 0:  # SELF
            beneficiary = creator
        else:  # OTHER
            beneficiary = rng.choice([u for u in users if u != creator])
        lead = rng.choice([u for u in users if u != creator]) if i in lead_set else None
        if i in lead_set:
            islead = 1 if lead_rows.index(i) < 4 else 0
        else:
            islead = 1 if i in yes_without_lead else 0

        city = rng.choice(CITIES)
        spanish = rng.random() < 0.15
        if spanish:
            spanish_rows.add(i)
        subj, desc = _general_text(rng, city, spanish)

        status = status_ids[i]
        submitted = SUBMISSION_START + timedelta(seconds=rng.randrange(265 * 86400), microseconds=_micro(rng))
        serviced = None
        if status in STATUS_SERVICED:
            serviced = submitted + timedelta(days=rng.randrange(1, 15), seconds=rng.randrange(86400))
        updated = max(submitted, serviced or submitted) + timedelta(
            seconds=rng.randrange(1, 10 * 86400), microseconds=_micro(rng))

        rows.append({
            "req_id": rid, "creator_id": creator, "beneficiary_id": beneficiary, "lead_volunteer_id": lead,
            "req_cat_id": cats[i], "req_for_id": for_id, "req_islead_id": islead,
            "req_type_id": type_ids[i], "req_priority_id": priority_ids[i], "req_status_id": status,
            "req_subj": subj, "req_desc": desc,
            "req_doc_link": None, "audio_req_desc": None, "deletion_reason": None,
            "req_loc": _point(rng, city), "created_loc": _point(rng, city),
            "iscalamity": rng.random() < 0.1, "to_public": rng.random() < 0.6,
            "submission_date": submitted, "serviced_date": serviced, "last_updated_at": updated,
        })

    # Nullable columns that are not always present.
    for i in rng.sample(range(n), 25):
        rows[i]["req_loc"] = None
    for i in rng.sample(range(n), 40):
        rows[i]["created_loc"] = None
    for i in rng.sample(range(n), 10):
        rows[i]["iscalamity"] = None
    for i in rng.sample(range(n), 10):
        rows[i]["to_public"] = None

    # Case 7: both '' and NULL in each nullable text column; most rows stay NULL.
    pool = rng.sample(range(n), 125)
    for i in pool[:110]:
        rows[i]["req_doc_link"] = f"https://example.test/docs/{rows[i]['req_id']}.pdf"
    for i in pool[110:]:
        rows[i]["req_doc_link"] = ""
        note(7, rows[i]["req_id"], "req_doc_link", "empty string (other rows are NULL)")
    pool = rng.sample([i for i in range(n) if i not in set(max_audio)], 50)
    for i in pool[:35]:
        rows[i]["audio_req_desc"] = f"s3://example-synthetic-audio/requests/{rows[i]['req_id']}/audio.mp3"
    for i in pool[35:]:
        rows[i]["audio_req_desc"] = ""
        note(7, rows[i]["req_id"], "audio_req_desc", "empty string (other rows are NULL)")
    deleted = [i for i in range(n) if rows[i]["req_status_id"] == STATUS_DELETED]
    for k, i in enumerate(deleted):
        rows[i]["deletion_reason"] = "" if k == 0 else DELETION_REASONS[k % len(DELETION_REASONS)]
    note(7, rows[deleted[0]]["req_id"], "deletion_reason", "empty string on a DELETED request")
    others = [i for i in range(n) if i not in set(deleted)]
    for i in rng.sample(others, 12):
        rows[i]["deletion_reason"] = ""
        note(7, rows[i]["req_id"], "deletion_reason", "empty string (other rows are NULL)")

    # Case 2: identical microsecond last_updated_at.
    for group, stamp in [(tie_day_end, TIE_DAY_END), (tie_midnight, TIE_MIDNIGHT), (tie_mid, TIE_MID)]:
        for i in group:
            row = rows[i]
            submitted = stamp - timedelta(seconds=rng.randrange(3600, 60 * 86400), microseconds=_micro(rng))
            row["submission_date"] = submitted
            row["serviced_date"] = (submitted + (stamp - submitted) / 2
                                    if row["req_status_id"] in STATUS_SERVICED else None)
            row["last_updated_at"] = stamp
            note(2, row["req_id"], "last_updated_at", stamp.isoformat(sep=" ", timespec="microseconds"))

    # Case 3: updated before submitted; the first is off by exactly one microsecond.
    for k, i in enumerate(early):
        row = rows[i]
        if k == 0:
            row["last_updated_at"] = row["submission_date"] - timedelta(microseconds=1)
        else:
            row["last_updated_at"] = row["submission_date"] - timedelta(
                seconds=rng.randrange(1, 3 * 86400), microseconds=_micro(rng))
        note(3, row["req_id"], "last_updated_at", "earlier than submission_date")

    # Case 4: embedded newlines, commas and quotes.
    for k, i in enumerate(csv_special):
        spec = CSV_SPECIAL[k % len(CSV_SPECIAL)]
        if "subj" in spec:
            rows[i]["req_subj"] = spec["subj"]
        if "desc" in spec:
            rows[i]["req_desc"] = ("Follow-up: " if k >= len(CSV_SPECIAL) else "") + spec["desc"]
        note(4, rows[i]["req_id"], "req_subj" if "subj" in spec else "req_desc", "newline, comma or quote")

    # Case 5: Unicode and Spanish.
    for k, i in enumerate(unicode_rows):
        subj, desc = UNICODE_PAIRS[k % len(UNICODE_PAIRS)]
        rows[i]["req_subj"] = subj
        rows[i]["req_desc"] = desc if k < len(UNICODE_PAIRS) else f"{desc} ({CITIES[k % len(CITIES)][0]})"
        note(5, rows[i]["req_id"], "req_subj", "unicode")
    spanish_rows -= set(unicode_rows) | set(csv_special) | set(pii_rows) | set(max_subj) | set(max_desc)
    for i in sorted(spanish_rows):
        note(5, rows[i]["req_id"], "req_desc", "spanish")

    # Case 6: synthetic personal details in req_desc.
    for k, i in enumerate(pii_rows):
        spec = PII_CASES[k]
        rows[i]["req_desc"] = spec["text"].format(*[v for _, _, v in spec["items"]])
        for pii_type, fmt, value in spec["items"]:
            note(6, rows[i]["req_id"], "req_desc", f"{pii_type}/{fmt}: {value}")

    # Case 8: exact maximum lengths, counted in characters.
    for k, i in enumerate(max_subj):
        rows[i]["req_subj"] = _fit(MAX_SUBJ_SEEDS[k], SUBJ_MAX)
        note(8, rows[i]["req_id"], "req_subj", f"length={SUBJ_MAX}")
    for k, i in enumerate(max_desc):
        rows[i]["req_desc"] = _fit(MAX_DESC_SEEDS[k], DESC_MAX)
        note(8, rows[i]["req_id"], "req_desc", f"length={DESC_MAX}")
    for k, i in enumerate(max_audio):
        rows[i]["audio_req_desc"] = _fit(MAX_AUDIO_SEEDS[k], AUDIO_MAX)
        note(8, rows[i]["req_id"], "audio_req_desc", f"length={AUDIO_MAX}")

    # Cases 1, 9, 10: derived from the generated columns.
    for row in rows:
        if row["beneficiary_id"] is None:
            note(1, row["req_id"], "beneficiary_id", "NULL")
        if row["lead_volunteer_id"] is not None:
            note(1, row["req_id"], "lead_volunteer_id", "not NULL")
        if row["req_status_id"] in (STATUS_DELETED, STATUS_VOLUNTEER_NOT_FOUND[0]):
            note(9, row["req_id"], "req_status_id", str(row["req_status_id"]))
        if row["req_priority_id"] == 3:
            note(9, row["req_id"], "req_priority_id", "3 (CRITICAL)")
        if row["req_islead_id"] == 1 and row["lead_volunteer_id"] is None:
            note(10, row["req_id"], "req_islead_id", "1 with NULL lead_volunteer_id")

    return rows, manifest


def build_broken_fk(requests):
    """One row per foreign key column, each pointing at a value that does not exist."""
    template = next(r for r in requests if r["beneficiary_id"] and r["lead_volunteer_id"])
    rows, manifest = [], []
    for k, (column, bad_value) in enumerate(FK_COLUMNS):
        row = dict(template)
        row["req_id"] = req_id(9001 + k)
        row["beneficiary_id"] = template["beneficiary_id"]
        row["lead_volunteer_id"] = template["lead_volunteer_id"]
        row[column] = bad_value
        rows.append(row)
        manifest.append({"case_no": 11, "case_name": CASE_NAMES[11],
                         "file": "fixtures/broken_fk/requests_broken_fk.csv", "req_id": row["req_id"],
                         "column": column, "detail": f"{bad_value} matches no row"})
    return rows, manifest


# ----------------------------------------------------------------------------- entry point

def generate(out_dir, seed=DEFAULT_SEED):
    out_dir = Path(out_dir)
    rng = random.Random(seed)
    tables = build_lookups()
    users = [user_id(n) for n in range(1, N_USERS + 1)]
    tables["users"] = [{"user_id": u} for u in users]
    tables["requests"], manifest = build_requests(rng, users, [r["cat_id"] for r in tables["help_categories"]])
    broken, broken_manifest = build_broken_fk(tables["requests"])

    for table, columns in TABLES.items():
        write_csv(out_dir / "csv" / f"{table}.csv", columns, tables[table])
    write_csv(out_dir / "fixtures" / "broken_fk" / "requests_broken_fk.csv", TABLES["requests"], broken)

    manifest = sorted(manifest + broken_manifest,
                      key=lambda m: (m["case_no"], m["file"], m["req_id"], m["column"], m["detail"]))
    write_csv(out_dir / "special_cases_manifest.csv",
              ["case_no", "case_name", "file", "req_id", "column", "detail"], manifest)
    return tables


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", default=str(HERE), help="output directory (default: next to this script)")
    args = parser.parse_args()
    tables = generate(args.out, args.seed)
    for table in TABLES:
        print(f"{table}.csv: {len(tables[table])} rows")
    print(f"written under {args.out}")


if __name__ == "__main__":
    main()
