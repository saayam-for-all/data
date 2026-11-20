import csv
import random
from datetime import datetime, timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
LOOKUP_DIR = BASE_DIR.parent / "lookup_tables"
OUTPUT_DIR = BASE_DIR / "output_csv_files"

REQUEST_COUNT = 100
USER_COUNT = 150
RANDOM_SEED = 42

REQUEST_FIELDS = [
    "req_id",
    "creator_id",
    "beneficiary_id",
    "lead_volunteer_id",
    "req_cat_id",
    "req_for_id",
    "req_islead_id",
    "req_type_id",
    "req_priority_id",
    "req_status_id",
    "req_subj",
    "req_desc",
    "req_doc_link",
    "audio_req_desc",
    "deletion_reason",
    "req_loc",
    "created_loc",
    "iscalamity",
    "to_public",
    "submission_date",
    "serviced_date",
    "last_updated_at",
]


def read_lookup(filename):
    path = LOOKUP_DIR / filename

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def make_user_id(number):
    digits = f"{number:017d}"
    groups = [
        digits[:2],
        digits[2:5],
        digits[5:8],
        digits[8:11],
        digits[11:14],
        digits[14:17],
    ]
    return "SID-" + "-".join(groups)


def make_request_id(number):
    digits = f"{number:013d}"
    groups = [
        digits[:3],
        digits[3:6],
        digits[6:9],
        digits[9:13],
    ]
    return "REQ-" + "-".join(groups)


def format_timestamp(value):
    return value.strftime("%Y-%m-%d %H:%M:%S")


def make_point():
    # Synthetic coordinates within the contiguous United States.
    longitude = random.uniform(-124.5, -67.0)
    latitude = random.uniform(25.0, 48.5)
    return f"POINT({longitude:.6f} {latitude:.6f})"


def write_csv(filename, rows, fields):
    path = OUTPUT_DIR / filename

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} rows: {path}")


def generate_users(count):
    start_date = datetime(2026, 1, 1, 9, 0, 0)

    return [
        {
            "user_id": make_user_id(i),
            "last_updated_at": format_timestamp(
                start_date + timedelta(days=random.randint(0, 250))
            ),
        }
        for i in range(1, count + 1)
    ]


def generate_requests(count, users):
    request_for = read_lookup("request_for.csv")
    request_islead = read_lookup("request_isleadvol.csv")
    priorities = read_lookup("request_priority.csv")
    statuses = read_lookup("request_status.csv")
    request_types = read_lookup("request_type.csv")
    categories = read_lookup("help_categories.csv")
    category_map = read_lookup("help_categories_map.csv")

    # Select leaf categories, excluding the general root category.
    parent_categories = {
        row["parent_id"]
        for row in category_map
        if row["parent_id"] not in ("", "NULL")
    }

    leaf_categories = [
        row for row in categories
        if row["cat_id"] != "0.0.0.0.0"
        and row["cat_id"] not in parent_categories
    ]

    if not leaf_categories:
        raise ValueError("No usable leaf categories found.")

    user_ids = [user["user_id"] for user in users]
    rows = []
    base_date = datetime(2026, 1, 1, 9, 0, 0)

    for i in range(1, count + 1):
        creator_id = random.choice(user_ids)
        req_for_id = random.choice(request_for)["req_for_id"]

        # SELF requests use the creator as beneficiary.
        # OTHER requests represent someone without a system account.
        beneficiary_id = creator_id if req_for_id == "0" else ""

        req_status_id = random.choice(statuses)["req_status_id"]
        req_type_id = random.choice(request_types)["req_type_id"]
        req_priority_id = random.choice(priorities)["req_priority_id"]
        req_islead_id = random.choice(request_islead)["req_islead_id"]
        category = random.choice(leaf_categories)

        submission_date = base_date + timedelta(
            days=random.randint(0, 300),
            hours=random.randint(0, 12),
            minutes=random.randint(0, 59),
        )

        # Assign a lead volunteer only after a request has progressed
        # beyond initial creation or matching.
        assigned_statuses = {"2", "3", "6", "7"}
        lead_volunteer_id = (
            random.choice(user_ids)
            if req_status_id in assigned_statuses
            else ""
        )

        serviced_date = ""
        if req_status_id in {"3", "6", "7"}:
            serviced_date = format_timestamp(
                submission_date + timedelta(
                    days=random.randint(1, 30),
                    hours=random.randint(1, 8),
                )
            )

        category_name = category["cat_name"].replace("_", " ").title()
        request_type = next(
            item["req_type"]
            for item in request_types
            if item["req_type_id"] == req_type_id
        )

        subject = f"Help needed: {category_name}"
        description = (
            f"Request for assistance with {category_name.lower()}. "
            "Please contact the requester to discuss the details "
            "and coordinate the next steps."
        )

        created_location = make_point()
        request_location = (
            make_point() if req_type_id == "0" else ""
        )

        is_deleted = req_status_id == "5"

        # Ensure the last update is never earlier than the service date.
        latest_event = (
            datetime.strptime(serviced_date, "%Y-%m-%d %H:%M:%S")
            if serviced_date
            else submission_date
        )

        last_updated = max(
            submission_date + timedelta(days=random.randint(0, 10)),
            latest_event + timedelta(hours=random.randint(1, 48))
            if serviced_date else submission_date,
        )

        rows.append({
            "req_id": make_request_id(i),
            "creator_id": creator_id,
            "beneficiary_id": beneficiary_id,
            "lead_volunteer_id": lead_volunteer_id,
            "req_cat_id": category["cat_id"],
            "req_for_id": req_for_id,
            "req_islead_id": req_islead_id,
            "req_type_id": req_type_id,
            "req_priority_id": req_priority_id,
            "req_status_id": req_status_id,
            "req_subj": subject[:125],
            "req_desc": description[:255],
            "req_doc_link": "",
            "audio_req_desc": "",
            "deletion_reason": (
                "Request removed from the system."
                if is_deleted else ""
            ),
            "req_loc": request_location,
            "created_loc": created_location,
            "iscalamity": random.choice(["true", "false"]),
            "to_public": random.choice(["true", "false"]),
            "submission_date": format_timestamp(submission_date),
            "serviced_date": serviced_date,
            "last_updated_at": format_timestamp(last_updated),
        })

    return rows


def main():
    random.seed(RANDOM_SEED)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    users = generate_users(USER_COUNT)
    requests = generate_requests(REQUEST_COUNT, users)

    write_csv(
        "users.csv",
        users,
        ["user_id", "last_updated_at"],
    )
    write_csv(
        "requests.csv",
        requests,
        REQUEST_FIELDS,
    )

    print("\nMock data generation completed.")
    print(f"Users: {len(users)}")
    print(f"Requests: {len(requests)}")


if __name__ == "__main__":
    main()
