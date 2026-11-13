
import csv
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# All names, addresses, emails, and phone numbers are synthetic.
# Each entry is (description, [(PII type, exact sensitive text), ...]).
pii_cases = [
    ("Call me at 312-555-0142 for grocery help.",
     [("PHONE", "312-555-0142")]),

    ("Email maya@example.com about transportation.",
     [("EMAIL", "maya@example.com")]),

    ("My name is Priya Sharma.",
     [("NAME", "Priya Sharma")]),

    ("Deliver food to 123 Oak Street, Chicago.",
     [("ADDRESS", "123 Oak Street")]),

    ("My phone number is (312) 555-0188.",
     [("PHONE", "(312) 555-0188")]),

    ("Reach me at 312.555.0174.",
     [("PHONE", "312.555.0174")]),

    ("Email rahul@example.org.",
     [("EMAIL", "rahul@example.org")]),

    ("I am Ahmed Khan and need medicine.",
     [("NAME", "Ahmed Khan")]),

    ("My address is 45 Maple Avenue.",
     [("ADDRESS", "45 Maple Avenue")]),

    ("Call three one two five five five zero one four two.",
     [("PHONE", "three one two five five five zero one four two")]),

    ("Please help María García.",
     [("NAME", "María García")]),

    ("Contact aisha.test@example.net.",
     [("EMAIL", "aisha.test@example.net")]),

    ("I live at 800 Pine Road.",
     [("ADDRESS", "800 Pine Road")]),

    ("Call +1 312 555 0119.",
     [("PHONE", "+1 312 555 0119")]),

    ("I am 李明 and need transportation.",
     [("NAME", "李明")]),

    ("My name is Fatima Al-Hassan.",
     [("NAME", "Fatima Al-Hassan")]),

    ("Email ravi.k@example.com.",
     [("EMAIL", "ravi.k@example.com")]),

    ("Please visit 22 Cedar Lane.",
     [("ADDRESS", "22 Cedar Lane")]),

    ("My number is 3125550165.",
     [("PHONE", "3125550165")]),

    ("I am Nguyễn Văn An.",
     [("NAME", "Nguyễn Văn An")]),

    ("Call me at 773-555-0102.",
     [("PHONE", "773-555-0102")]),

    ("My name is José Martínez.",
     [("NAME", "José Martínez")]),

    ("I need help at 14 Elm Street.",
     [("ADDRESS", "14 Elm Street")]),

    ("Contact test.person@example.com.",
     [("EMAIL", "test.person@example.com")]),

    ("My phone is seven seven three five five five zero one two three.",
     [("PHONE", "seven seven three five five five zero one two three")]),

    ("Please assist Ananya Patel.",
     [("NAME", "Ananya Patel")]),

    ("Deliver supplies to 90 Lake Avenue.",
     [("ADDRESS", "90 Lake Avenue")]),

    ("Reach me at 630-555-0134.",
     [("PHONE", "630-555-0134")]),

    ("I am 김민수 and need food.",
     [("NAME", "김민수")]),

    ("Email help.request@example.org.",
     [("EMAIL", "help.request@example.org")]),

    ("Please call 847-555-0112.",
     [("PHONE", "847-555-0112")]),

    ("My name is Olúwáṣẹun Adeyemi.",
     [("NAME", "Olúwáṣẹun Adeyemi")]),

    ("Deliver food to 61 Birch Street.",
     [("ADDRESS", "61 Birch Street")]),

    ("Contact care.team@example.net.",
     [("EMAIL", "care.team@example.net")]),

    ("I am Sofia Rossi.",
     [("NAME", "Sofia Rossi")]),

    ("My number is 224-555-0191.",
     [("PHONE", "224-555-0191")]),

    ("My address is 77 Walnut Drive.",
     [("ADDRESS", "77 Walnut Drive")]),

    ("Please contact Yuki Tanaka.",
     [("NAME", "Yuki Tanaka")]),

    ("Email samira@example.com.",
     [("EMAIL", "samira@example.com")]),

    ("Call me at (708) 555-0127.",
     [("PHONE", "(708) 555-0127")]),
]

clean_cases = [
    "I need groceries this weekend.",
    "Looking for transportation to a clinic.",
    "Please help with winter clothing.",
    "I need information about food pantries.",
    "Can a volunteer help move boxes?",
    "Requesting community resources.",
    "I need a ride to an appointment.",
    "Looking for school supplies.",
    "Please arrange grocery delivery.",
    "I need household cleaning assistance.",
    "Can someone help fill out forms?",
    "I need help applying for jobs.",
    "Looking for volunteer programs.",
    "Please provide food assistance information.",
    "I need help scheduling transportation.",
    "Requesting support for an appointment.",
    "Can a volunteer deliver clothes?",
    "I need help accessing community services.",
    "Looking for basic computer lessons.",
    "Please connect me with volunteers.",
]

# Extra cases for checking partial masking.
# Kept separate so the original 60-request benchmark is reproducible.
mixed_pii_cases = [
    (
        "I am Priya Sharma. Call 312-555-0142.",
        [("NAME", "Priya Sharma"), ("PHONE", "312-555-0142")],
    ),
    (
        "Ahmed Khan needs help at 45 Maple Avenue.",
        [("NAME", "Ahmed Khan"), ("ADDRESS", "45 Maple Avenue")],
    ),
    (
        "Contact José Martínez at jose@example.com.",
        [("NAME", "José Martínez"), ("EMAIL", "jose@example.com")],
    ),
    (
        "Please call 773-555-0102 or email help@example.org.",
        [("PHONE", "773-555-0102"), ("EMAIL", "help@example.org")],
    ),
    (
        "Yuki Tanaka lives at 61 Birch Street.",
        [("NAME", "Yuki Tanaka"), ("ADDRESS", "61 Birch Street")],
    ),
    (
        "My card number is 4111 1111 1111 1111.",
        [("CREDIT_CARD", "4111 1111 1111 1111")],
    ),
    (
        "My SSN is 123-45-6789.",
        [("SSN", "123-45-6789")],
    ),
    (
        "Priya Sharma needs help. Card number is 4111-1111-1111-1111.",
        [
            ("NAME", "Priya Sharma"),
            ("CREDIT_CARD", "4111-1111-1111-1111"),
        ],
    ),
    (
        "Please contact me at maya@example.com. SSN: 123-45-6789.",
        [
            ("EMAIL", "maya@example.com"),
            ("SSN", "123-45-6789"),
        ],
    ),
]


def create_records(pii_examples, clean_examples):
    records = []
    annotations = []

    for description, entities in pii_examples:
        request_id = len(records) + 1

        records.append({
            "id": request_id,
            "description": description,
            "contains_pii": 1,
            "pii_type": "|".join(sorted({kind for kind, _ in entities})),
        })

        for kind, value in entities:
            start = description.find(value)

            if start < 0:
                raise ValueError(
                    f"Annotation not found in request {request_id}: {value}"
                )

            annotations.append({
                "request_id": request_id,
                "pii_type": kind,
                "pii_value": value,
                "start": start,
                "end": start + len(value),
            })

    for description in clean_examples:
        records.append({
            "id": len(records) + 1,
            "description": description,
            "contains_pii": 0,
            "pii_type": "NONE",
        })

    return records, annotations


def write_csv(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


records, annotations = create_records(pii_cases, clean_cases)

write_csv(
    DATA_DIR / "test_requests.csv",
    records,
    ["id", "description", "contains_pii", "pii_type"],
)

write_csv(
    DATA_DIR / "pii_annotations.csv",
    annotations,
    ["request_id", "pii_type", "pii_value", "start", "end"],
)

# Additional test set: original cases plus mixed-PII examples.
extended_records, extended_annotations = create_records(
    pii_cases + mixed_pii_cases,
    clean_cases,
)

write_csv(
    DATA_DIR / "extended_requests.csv",
    extended_records,
    ["id", "description", "contains_pii", "pii_type"],
)

write_csv(
    DATA_DIR / "extended_annotations.csv",
    extended_annotations,
    ["request_id", "pii_type", "pii_value", "start", "end"],
)

# Only six names are registered in the mock users table.
# Other names intentionally remain unknown.
names = [
    "Priya Sharma",
    "Ahmed Khan",
    "María García",
    "Fatima Al-Hassan",
    "Ananya Patel",
    "Sofia Rossi",
]

with (DATA_DIR / "mock_users.csv").open(
    "w", newline="", encoding="utf-8-sig"
) as file:
    writer = csv.writer(file)
    writer.writerow(["user_id", "full_name"])

    for index, name in enumerate(names, start=1):
        writer.writerow([index, name])

# Validate annotation offsets.
for annotation in annotations:
    text = records[int(annotation["request_id"]) - 1]["description"]
    extracted = text[annotation["start"]:annotation["end"]]

    assert extracted == annotation["pii_value"], (
        f"Invalid annotation: {annotation}"
    )

assert len(records) == 60
assert sum(row["contains_pii"] for row in records) == 40
assert len(clean_cases) == 20

print(f"Created {len(records)} original mock requests.")
print(f"PII cases: {len(pii_cases)}")
print(f"Clean cases: {len(clean_cases)}")
print(f"Exact PII annotations: {len(annotations)}")
print(f"Extended test requests: {len(extended_records)}")
print(f"Extended annotations: {len(extended_annotations)}")
print(f"Mock users: {len(names)}")
print("All annotation offsets validated successfully.")
