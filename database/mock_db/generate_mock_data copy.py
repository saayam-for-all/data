import json
import random
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd


# ----------------------------
# Config
# ----------------------------
BASE_DIR = Path(__file__).resolve().parent
PROJECT_DB_DIR = BASE_DIR.parent
MOCK_DB_DIR = PROJECT_DB_DIR / "mock_db"

USERS_FILE = BASE_DIR / "users.csv"
REQUEST_FILE = BASE_DIR / "request.csv"
VOLUNTEER_APPLICATIONS_FILE = BASE_DIR / "volunteer_applications.csv"

VOLUNTEER_DETAILS_OUTPUT = MOCK_DB_DIR / "volunteer_details.csv"
VOLUNTEERS_ASSIGNED_OUTPUT = MOCK_DB_DIR / "volunteers_assigned.csv"

# Keep small first for testing
VOLUNTEER_DETAILS_COUNT = 100
VOLUNTEERS_ASSIGNED_COUNT = 100

SEED = 42


# ----------------------------
# Helpers
# ----------------------------
def set_seed(seed: int = 42) -> None:
    random.seed(seed)


def ensure_output_dir() -> None:
    MOCK_DB_DIR.mkdir(parents=True, exist_ok=True)


def format_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def random_datetime_between(start: datetime, end: datetime) -> datetime:
    if start >= end:
        return start
    total_seconds = int((end - start).total_seconds())
    rand_seconds = random.randint(0, total_seconds)
    return start + timedelta(seconds=rand_seconds)


def sample_days():
    all_days = [
        "Monday", "Tuesday", "Wednesday",
        "Thursday", "Friday", "Saturday", "Sunday"
    ]
    k = random.randint(1, 4)
    return json.dumps(sorted(random.sample(all_days, k)))


def sample_time_slot():
    slots = [
        ("08:00", "12:00"),
        ("09:00", "13:00"),
        ("10:00", "16:00"),
        ("12:00", "18:00"),
        ("14:00", "20:00"),
        ("18:00", "21:00"),
    ]
    start, end = random.choice(slots)
    return json.dumps({"start": start, "end": end})


def sample_volunteer_type():
    return random.choice(["local", "support", "remote", "field"])


def safe_datetime_from_str(value, fallback_start, fallback_end):
    if pd.isna(value):
        return random_datetime_between(fallback_start, fallback_end)
    try:
        parsed = pd.to_datetime(value)
        return parsed.to_pydatetime()
    except Exception:
        return random_datetime_between(fallback_start, fallback_end)


# ----------------------------
# Load sources
# ----------------------------
def load_source_data():
    print("USERS_FILE =", USERS_FILE)
    print("REQUEST_FILE =", REQUEST_FILE)
    print("VOLUNTEER_APPLICATIONS_FILE =", VOLUNTEER_APPLICATIONS_FILE)
    print("MOCK_DB_DIR =", MOCK_DB_DIR)

    users_df = pd.read_csv(USERS_FILE)
    request_df = pd.read_csv(REQUEST_FILE)
    volunteer_app_df = pd.read_csv(VOLUNTEER_APPLICATIONS_FILE)

    if "user_id" not in users_df.columns:
        raise ValueError("users.csv must contain column: user_id")

    if "req_id" not in request_df.columns:
        raise ValueError("request.csv must contain column: req_id")

    if "user_id" not in volunteer_app_df.columns:
        raise ValueError("volunteer_applications.csv must contain column: user_id")

    return users_df, request_df, volunteer_app_df


# ----------------------------
# volunteer_details generator
# Uses users.csv for valid user_id
# Uses volunteer_applications.csv only as a pattern/template source
# ----------------------------
def generate_volunteer_details(
    users_df: pd.DataFrame,
    volunteer_app_df: pd.DataFrame,
    count: int
) -> pd.DataFrame:
    user_ids = users_df["user_id"].dropna().astype(str).unique().tolist()

    if not user_ids:
        raise ValueError("No valid user_id values found in users.csv")

    if volunteer_app_df.empty:
        raise ValueError("volunteer_applications.csv is empty")

    app_records = volunteer_app_df.to_dict(orient="records")

    rows = []
    fallback_start = datetime(2025, 1, 1, 8, 0)
    fallback_end = datetime(2026, 4, 1, 20, 0)

    for i in range(count):
        valid_user_id = user_ids[i % len(user_ids)]
        app = app_records[i % len(app_records)]

        created_at = safe_datetime_from_str(
            app.get("created_at"), fallback_start, fallback_end
        )
        terms_accepted_at = safe_datetime_from_str(
            app.get("terms_accepted_at"), created_at, created_at + timedelta(days=5)
        )
        path_updated_at = safe_datetime_from_str(
            app.get("path_updated_at"), terms_accepted_at, terms_accepted_at + timedelta(days=10)
        )
        last_updated_at = safe_datetime_from_str(
            app.get("last_updated_at"), path_updated_at, path_updated_at + timedelta(days=15)
        )

        govt_id_path = app.get("govt_id_path", f"/mock/ids/{valid_user_id}.pdf")
        if pd.isna(govt_id_path) or str(govt_id_path).strip() == "":
            govt_id_path = f"/mock/ids/{valid_user_id}.pdf"

        availability_raw = app.get("availability")
        availability_days = sample_days()
        availability_times = sample_time_slot()

        if pd.notna(availability_raw):
            availability_text = str(availability_raw).lower()
            if "weekdays" in availability_text:
                availability_days = json.dumps(
                    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
                )
            elif "weekend" in availability_text:
                availability_days = json.dumps(["Saturday", "Sunday"])

            if "morning" in availability_text:
                availability_times = json.dumps({"start": "08:00", "end": "12:00"})
            elif "afternoon" in availability_text:
                availability_times = json.dumps({"start": "12:00", "end": "17:00"})
            elif "evening" in availability_text:
                availability_times = json.dumps({"start": "17:00", "end": "21:00"})

        rows.append({
            "user_id": valid_user_id,
            "terms_and_conditions": bool(app.get("terms_and_conditions", True)),
            "terms_accepted_at": format_dt(terms_accepted_at),
            "govt_id_path1": str(govt_id_path),
            "govt_id_path2": f"/mock/ids/{valid_user_id}_alt.pdf",
            "path1_updated_at": format_dt(path_updated_at),
            "path2_updated_at": format_dt(path_updated_at + timedelta(days=random.randint(0, 10))),
            "availability_days": availability_days,
            "availability_times": availability_times,
            "created_at": format_dt(created_at),
            "last_updated_at": format_dt(last_updated_at),
        })

    df = pd.DataFrame(rows)

    ordered_cols = [
        "user_id",
        "terms_and_conditions",
        "terms_accepted_at",
        "govt_id_path1",
        "govt_id_path2",
        "path1_updated_at",
        "path2_updated_at",
        "availability_days",
        "availability_times",
        "created_at",
        "last_updated_at",
    ]
    return df[ordered_cols]


# ----------------------------
# volunteers_assigned generator
# ----------------------------
def generate_volunteers_assigned(
    users_df: pd.DataFrame,
    request_df: pd.DataFrame,
    count: int
) -> pd.DataFrame:
    user_ids = users_df["user_id"].dropna().astype(str).unique().tolist()
    request_ids = request_df["req_id"].dropna().astype(str).unique().tolist()

    if not user_ids:
        raise ValueError("No valid user_id values found in users.csv")
    if not request_ids:
        raise ValueError("No valid req_id values found in request.csv")

    rows = []

    for i in range(count):
        rows.append({
            "volunteers_assigned_id": i + 1,
            "request_id": random.choice(request_ids),
            "volunteer_id": random.choice(user_ids),
            "volunteer_type": sample_volunteer_type(),
            "last_update_date": format_dt(
                random_datetime_between(
                    datetime(2025, 1, 1, 0, 0),
                    datetime(2026, 4, 1, 23, 59)
                )
            ),
        })

    df = pd.DataFrame(rows)

    ordered_cols = [
        "volunteers_assigned_id",
        "request_id",
        "volunteer_id",
        "volunteer_type",
        "last_update_date",
    ]
    return df[ordered_cols]


# ----------------------------
# Validation
# ----------------------------
def validate_volunteer_details(df: pd.DataFrame, users_df: pd.DataFrame) -> None:
    valid_users = set(users_df["user_id"].dropna().astype(str))
    invalid_users = set(df["user_id"].astype(str)) - valid_users

    if invalid_users:
        raise ValueError(f"Invalid user_id values in volunteer_details: {list(invalid_users)[:10]}")


def validate_volunteers_assigned(
    df: pd.DataFrame,
    users_df: pd.DataFrame,
    request_df: pd.DataFrame
) -> None:
    valid_users = set(users_df["user_id"].dropna().astype(str))
    valid_requests = set(request_df["req_id"].dropna().astype(str))

    invalid_users = set(df["volunteer_id"].astype(str)) - valid_users
    invalid_requests = set(df["request_id"].astype(str)) - valid_requests

    if invalid_users:
        raise ValueError(f"Invalid volunteer_id values: {list(invalid_users)[:10]}")
    if invalid_requests:
        raise ValueError(f"Invalid request_id values: {list(invalid_requests)[:10]}")


# ----------------------------
# Write outputs
# ----------------------------
def write_csv(df: pd.DataFrame, output_path: Path) -> None:
    df.to_csv(output_path, index=False)


# ----------------------------
# Main
# ----------------------------
def main():
    set_seed(SEED)
    ensure_output_dir()

    users_df, request_df, volunteer_app_df = load_source_data()

    volunteer_details_df = generate_volunteer_details(
        users_df=users_df,
        volunteer_app_df=volunteer_app_df,
        count=VOLUNTEER_DETAILS_COUNT
    )

    volunteers_assigned_df = generate_volunteers_assigned(
        users_df=users_df,
        request_df=request_df,
        count=VOLUNTEERS_ASSIGNED_COUNT
    )

    validate_volunteer_details(volunteer_details_df, users_df)
    validate_volunteers_assigned(volunteers_assigned_df, users_df, request_df)

    write_csv(volunteer_details_df, VOLUNTEER_DETAILS_OUTPUT)
    write_csv(volunteers_assigned_df, VOLUNTEERS_ASSIGNED_OUTPUT)

    print(f"Generated: {VOLUNTEER_DETAILS_OUTPUT} -> {len(volunteer_details_df)} rows")
    print(f"Generated: {VOLUNTEERS_ASSIGNED_OUTPUT} -> {len(volunteers_assigned_df)} rows")
    print("Done.")


if __name__ == "__main__":
    main()