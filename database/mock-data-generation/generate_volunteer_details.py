#!/usr/bin/env python3
"""Generate synthetic data for volunteer_details from existing users.csv."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from datetime import datetime, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SCHEMA_PATH = SCRIPT_DIR / "db_info.json"
DEFAULT_USERS_CSV = SCRIPT_DIR.parent / "mock_db" / "users.csv"
DEFAULT_OUTPUT_CSV = SCRIPT_DIR.parent / "mock_db" / "volunteer_details.csv"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
TIME_WINDOWS = [
    "06:00-09:00",
    "09:00-12:00",
    "12:00-15:00",
    "15:00-18:00",
    "18:00-21:00",
]


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for volunteer_details generation.

    Configures command-line interface for customizing:
    - Schema file path (db_info.json)
    - Input users CSV file
    - Output volunteer_details CSV file
    - Volunteer ratio (default 15%)
    - Random seed for deterministic generation
    - Optional cap on volunteer count

    Returns:
        argparse.Namespace: Parsed arguments with all configuration options.
    """
    parser = argparse.ArgumentParser(
        description="Generate synthetic CSV for volunteer_details based on users.csv"
    )
    parser.add_argument(
        "--schema-json",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help=f"Path to db_info.json (default: {DEFAULT_SCHEMA_PATH})",
    )
    parser.add_argument(
        "--users-csv",
        type=Path,
        default=DEFAULT_USERS_CSV,
        help=f"Path to users.csv (default: {DEFAULT_USERS_CSV})",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help=f"Output path for volunteer_details.csv (default: {DEFAULT_OUTPUT_CSV})",
    )
    parser.add_argument(
        "--volunteer-ratio",
        type=float,
        default=0.15,
        help="Share of users to include in volunteer_details (default: 0.15)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=117,
        help="Random seed for deterministic sampling and values (default: 117)",
    )
    parser.add_argument(
        "--max-volunteers",
        type=int,
        default=None,
        help="Optional cap on number of volunteer_details rows",
    )
    return parser.parse_args()


def load_table_columns(schema_path: Path, table_name: str) -> list[str]:
    """Load ordered column names for a table from db_info.json.

    Reads the database schema file and extracts the ordered list of column
    names for a specified table, preserving the order defined in the schema.

    Args:
        schema_path: Path to db_info.json file containing table definitions.
        table_name: Name of the table to extract columns for.

    Returns:
        list[str]: Ordered list of column names for the table.

    Raises:
        ValueError: If the table is not found in the schema or has no columns.
        FileNotFoundError: If schema file cannot be read.
    """
    with schema_path.open("r", encoding="utf-8") as handle:
        db_info = json.load(handle)

    if "tables" not in db_info or table_name not in db_info["tables"]:
        raise ValueError(f"Table '{table_name}' not found in schema file: {schema_path}")

    columns = [column["name"] for column in db_info["tables"][table_name]["columns"]]
    if not columns:
        raise ValueError(f"No columns found for table '{table_name}' in {schema_path}")
    return columns


def load_user_ids(users_csv: Path) -> list[str]:
    """Read and deduplicate user_id values from users.csv.

    Loads all user_ids from the CSV file, handling various formats:
    - With or without a header row
    - user_id column can be named or assumed as first column
    - Empty rows and duplicate user_ids are automatically filtered out

    Args:
        users_csv: Path to the users CSV file.

    Returns:
        list[str]: Deduplicated, non-empty user_id values in order of appearance.

    Raises:
        FileNotFoundError: If users.csv file does not exist.
    """
    if not users_csv.exists():
        raise FileNotFoundError(f"users.csv not found: {users_csv}")

    with users_csv.open("r", encoding="utf-8", newline="") as handle:
        raw_rows = [row for row in csv.reader(handle) if any(cell.strip() for cell in row)]

    if not raw_rows:
        return []

    header = [item.strip().lower() for item in raw_rows[0]]
    if "user_id" in header:
        user_id_idx = header.index("user_id")
        data_rows = raw_rows[1:]
    else:
        user_id_idx = 0
        data_rows = raw_rows

    unique_user_ids: list[str] = []
    seen: set[str] = set()
    for row in data_rows:
        if user_id_idx >= len(row):
            continue
        user_id = row[user_id_idx].strip()
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        unique_user_ids.append(user_id)
    return unique_user_ids


def calculate_target_count(total_users: int, ratio: float, max_volunteers: int | None) -> int:
    """Calculate target volunteer row count based on total users and ratio.

    Computes how many volunteer records should be generated given the total
    user count and desired volunteer ratio. Respects optional caps and ensures
    the result doesn't exceed available users.

    Args:
        total_users: Total number of users available as candidates.
        ratio: Fraction of users to convert to volunteers (0.0 to 1.0).
        max_volunteers: Optional ceiling on volunteer count. If None, no cap applied.

    Returns:
        int: Target number of volunteer records to generate.

    Raises:
        ValueError: If ratio is outside [0, 1] or max_volunteers is negative.
    """
    if ratio < 0:
        raise ValueError("volunteer-ratio must be >= 0")
    if ratio > 1:
        raise ValueError("volunteer-ratio must be <= 1")

    if total_users == 0 or ratio == 0:
        return 0

    target_count = round(total_users * ratio)
    if target_count == 0:
        target_count = 1

    target_count = min(target_count, total_users)
    if max_volunteers is not None:
        if max_volunteers < 0:
            raise ValueError("max-volunteers must be >= 0")
        target_count = min(target_count, max_volunteers)
    return target_count


def load_existing_volunteer_user_ids(output_csv: Path) -> set[str]:
    """Read existing volunteer user_id values from volunteer_details.csv.

    Checks if the output CSV file exists and has content, then extracts all
    user_ids to avoid re-generating volunteer records that already exist.
    Allows for safe incremental updates to the volunteer_details file.

    Args:
        output_csv: Path to the volunteer_details CSV file.

    Returns:
        set[str]: Set of existing user_ids (empty set if file doesn't exist or is empty).

    Raises:
        ValueError: If user_id column is missing from existing CSV file.
    """
    if not output_csv.exists() or output_csv.stat().st_size == 0:
        return set()

    with output_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return set()
        if "user_id" not in [name.strip() for name in reader.fieldnames]:
            raise ValueError(f"'user_id' column not found in existing file: {output_csv}")
        user_ids = {row.get("user_id", "").strip() for row in reader}
    user_ids.discard("")
    return user_ids


def select_new_volunteer_user_ids(
    candidate_user_ids: list[str], required_count: int, seed: int
) -> list[str]:
    """Select new volunteer user IDs to append without duplicates.

    Randomly samples from candidate user_ids using a seeded RNG to ensure
    deterministic but varied selection. Returns selected IDs in sorted order
    for consistency.

    Args:
        candidate_user_ids: List of user_ids available for selection.
        required_count: Number of user_ids to select.
        seed: Random seed for reproducible selection.

    Returns:
        list[str]: Sorted list of selected user_ids. Empty list if required_count <= 0.
                   Returns all candidates if required_count >= len(candidate_user_ids).
    """
    if required_count <= 0:
        return []
    if required_count >= len(candidate_user_ids):
        return sorted(candidate_user_ids)

    sampler = random.Random(seed)
    selected = sampler.sample(candidate_user_ids, required_count)
    selected.sort()
    return selected


def seeded_rng(seed: int, user_id: str) -> random.Random:
    """Create a deterministic RNG for a specific user.

    Generates a unique but reproducible random number generator for each user
    by hashing the seed and user_id together. Ensures that the same user always
    gets the same random values across runs, but different users get different
    random values.

    Args:
        seed: Base random seed (e.g., 117).
        user_id: Unique user identifier to incorporate into the seed.

    Returns:
        random.Random: Seeded RNG instance unique to this user_id.
    """
    digest = hashlib.sha256(f"{seed}:{user_id}".encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def random_datetime(rng: random.Random, start_dt: datetime, end_dt: datetime) -> datetime:
    """Generate a random datetime between start_dt and end_dt (inclusive).

    Creates a random timestamp within the specified range using the provided RNG.
    Returns start_dt if the range is invalid (end_dt <= start_dt).

    Args:
        rng: Random number generator instance (typically from seeded_rng).
        start_dt: Beginning of the datetime range (inclusive).
        end_dt: End of the datetime range (inclusive).

    Returns:
        datetime: Random datetime between start_dt and end_dt, or start_dt if range is invalid.
    """
    total_seconds = int((end_dt - start_dt).total_seconds())
    if total_seconds <= 0:
        return start_dt
    return start_dt + timedelta(seconds=rng.randint(0, total_seconds))


def format_ts(value: datetime) -> str:
    """Format datetime as timestamp string compatible with CSV mock data.

    Converts a datetime object to a string in the format 'YYYY-MM-DD HH:MM:SS'
    for consistency with CSV import and database expectations.

    Args:
        value: datetime object to format.

    Returns:
        str: Formatted timestamp string in TIMESTAMP_FORMAT.
    """
    return value.strftime(TIMESTAMP_FORMAT)


def generate_availability(rng: random.Random) -> tuple[str, str]:
    """Generate availability JSON strings for days and time windows.

    Creates realistic volunteer availability by randomly selecting 2-6 days
    and assigning 1-2 time windows per day. Returns JSON-serialized strings
    for direct insertion into CSV.

    Args:
        rng: Random number generator instance (typically from seeded_rng).

    Returns:
        tuple[str, str]: Two JSON strings:
            - availability_days: Array of day names (e.g. '["Monday","Wednesday","Friday"]')
            - availability_times: Object mapping days to time windows
              (e.g. '{"Monday":["09:00-12:00"],"Wednesday":["15:00-18:00"]}')
    """
    selected_days = sorted(rng.sample(DAY_NAMES, rng.randint(2, 6)), key=DAY_NAMES.index)
    day_to_windows: dict[str, list[str]] = {}
    for day in selected_days:
        slots = sorted(rng.sample(TIME_WINDOWS, rng.randint(1, 2)), key=TIME_WINDOWS.index)
        day_to_windows[day] = slots
    return (
        json.dumps(selected_days, separators=(",", ":")),
        json.dumps(day_to_windows, separators=(",", ":")),
    )


def generate_volunteer_row(user_id: str, seed: int, now_dt: datetime) -> dict[str, str]:
    """Generate one volunteer_details row for a user.

    Creates a complete volunteer record with realistic synthetic data including:
    - Timestamps (creation, terms acceptance, last update, doc uploads)
    - Government ID file paths (65% chance of secondary document)
    - Availability (days and time windows)

    All randomization is deterministic based on the user_id and seed, so the
    same user always gets the same volunteer details across runs.

    Args:
        user_id: Unique user identifier to generate record for.
        seed: Random seed used to derive user-specific RNG.
        now_dt: Current datetime reference point for relative date generation.

    Returns:
        dict[str, str]: Volunteer record with all fields as strings, ready for CSV output.
    """
    rng = seeded_rng(seed, user_id)

    created_at = random_datetime(rng, now_dt - timedelta(days=730), now_dt - timedelta(days=7))
    terms_accepted_at = random_datetime(
        rng, created_at - timedelta(days=45), created_at - timedelta(hours=1)
    )
    last_updated_at = random_datetime(rng, created_at, now_dt)
    path1_updated_at = random_datetime(rng, created_at, last_updated_at)

    has_second_doc = rng.random() < 0.65
    if has_second_doc:
        path2_updated_at = random_datetime(rng, path1_updated_at, last_updated_at)
        govt_id_path2 = f"/mock-storage/kyc/{user_id}/govt_id_back_{rng.randint(1000, 9999)}.pdf"
        path2_updated_at_str = format_ts(path2_updated_at)
    else:
        govt_id_path2 = ""
        path2_updated_at_str = ""

    availability_days, availability_times = generate_availability(rng)

    return {
        "user_id": user_id,
        "terms_and_conditions": "true",
        "terms_accepted_at": format_ts(terms_accepted_at),
        "govt_id_path1": f"/mock-storage/kyc/{user_id}/govt_id_front_{rng.randint(1000, 9999)}.pdf",
        "govt_id_path2": govt_id_path2,
        "path1_updated_at": format_ts(path1_updated_at),
        "path2_updated_at": path2_updated_at_str,
        "availability_days": availability_days,
        "availability_times": availability_times,
        "created_at": format_ts(created_at),
        "last_updated_at": format_ts(last_updated_at),
    }


def ensure_output_header(output_csv: Path, columns: list[str]) -> bool:
    """Ensure output CSV exists with header; return True if header was created.

    Checks if the output CSV file exists with content. If not, creates the file
    with the header row containing the schema column names. Handles directory
    creation if needed.

    Args:
        output_csv: Path to the output volunteer_details CSV file.
        columns: List of column names to write as header.

    Returns:
        bool: True if header was just created, False if file already existed with content.
    """
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if output_csv.exists() and output_csv.stat().st_size > 0:
        return False
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
    return True


def append_rows(output_csv: Path, columns: list[str], rows: list[dict[str, str]]) -> int:
    """Append generated volunteer rows to CSV using schema column order.

    Writes volunteer records to the output CSV file in append mode, respecting
    the column order defined in the schema. Extra fields in the row dicts are
    ignored if present.

    Args:
        output_csv: Path to the volunteer_details CSV file.
        columns: Ordered list of column names from the schema.
        rows: List of volunteer record dictionaries to append.

    Returns:
        int: Number of rows actually written to the file.
    """
    if not rows:
        return 0
    with output_csv.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    """Entry point for volunteer_details CSV generation.

    Orchestrates the complete workflow:
    1. Parse CLI arguments and load configuration
    2. Read users from input CSV and schema from db_info.json
    3. Calculate target volunteer count based on ratio
    4. Identify existing volunteers (to avoid duplicates)
    5. Select and generate new volunteer records
    6. Write results to output CSV with appropriate headers
    7. Print summary statistics to stdout

    All operations are safe for repeated runs (idempotent) - existing
    volunteer records are preserved and only missing records are appended.
    """
    args = parse_args()
    now_dt = datetime.now().replace(microsecond=0)
    columns = load_table_columns(args.schema_json, "volunteer_details")
    user_ids = load_user_ids(args.users_csv)
    users_set = set(user_ids)
    target_count = calculate_target_count(
        total_users=len(user_ids),
        ratio=args.volunteer_ratio,
        max_volunteers=args.max_volunteers,
    )

    existing_volunteer_user_ids = load_existing_volunteer_user_ids(args.output_csv)
    existing_valid_volunteer_ids = existing_volunteer_user_ids.intersection(users_set)

    # Preserve existing rows; append only missing volunteers from users.csv.
    needed_count = max(0, target_count - len(existing_valid_volunteer_ids))
    candidate_user_ids = sorted(users_set.difference(existing_volunteer_user_ids))
    selected_new_user_ids = select_new_volunteer_user_ids(
        candidate_user_ids=candidate_user_ids,
        required_count=needed_count,
        seed=args.seed,
    )
    rows = [generate_volunteer_row(user_id, args.seed, now_dt) for user_id in selected_new_user_ids]

    header_created = ensure_output_header(args.output_csv, columns)
    rows_appended = append_rows(args.output_csv, columns, rows)

    ratio_pct = args.volunteer_ratio * 100
    print(f"users_found={len(user_ids)}")
    print(f"volunteer_ratio={ratio_pct:.2f}%")
    print(f"target_rows={target_count}")
    print(f"existing_rows_considered={len(existing_valid_volunteer_ids)}")
    print(f"rows_appended={rows_appended}")
    print(f"header_created={str(header_created).lower()}")
    print(f"output_csv={args.output_csv}")


if __name__ == "__main__":
    main()
