#!/usr/bin/env python3
"""Generate synthetic data for volunteers_assigned from existing requests and volunteers."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SCHEMA_PATH = SCRIPT_DIR / "db_info.json"
DEFAULT_REQUESTS_CSV = SCRIPT_DIR.parent / "mock_db" / "request.csv"
DEFAULT_VOLUNTEER_DETAILS_CSV = SCRIPT_DIR.parent / "mock_db" / "volunteer_details.csv"
DEFAULT_OUTPUT_CSV = SCRIPT_DIR.parent / "mock_db" / "volunteers_assigned.csv"
DEFAULT_LOOKUP_DIR = SCRIPT_DIR.parent / "lookup_tables"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
VOLUNTEER_TYPES = ["IN_PERSON", "REMOTE"]


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for volunteers_assigned generation.

    Configures command-line interface for customizing:
    - Schema file path (db_info.json)
    - Input requests CSV file
    - Input volunteer_details CSV file
    - Output volunteers_assigned CSV file
    - Number of assignments to generate (default 25,000)
    - Random seed for deterministic generation
    - Lookup tables directory

    Returns:
        argparse.Namespace: Parsed arguments with all configuration options.
    """
    parser = argparse.ArgumentParser(
        description="Generate synthetic CSV for volunteers_assigned based on requests and volunteer_details"
    )
    parser.add_argument(
        "--schema-json",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help=f"Path to db_info.json (default: {DEFAULT_SCHEMA_PATH})",
    )
    parser.add_argument(
        "--requests-csv",
        type=Path,
        default=DEFAULT_REQUESTS_CSV,
        help=f"Path to request.csv (default: {DEFAULT_REQUESTS_CSV})",
    )
    parser.add_argument(
        "--volunteer-details-csv",
        type=Path,
        default=DEFAULT_VOLUNTEER_DETAILS_CSV,
        help=f"Path to volunteer_details.csv (default: {DEFAULT_VOLUNTEER_DETAILS_CSV})",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help=f"Output path for volunteers_assigned.csv (default: {DEFAULT_OUTPUT_CSV})",
    )
    parser.add_argument(
        "--num-assignments",
        type=int,
        default=25000,
        help="Number of volunteer assignments to generate (default: 25000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=117,
        help="Random seed for deterministic generation (default: 117)",
    )
    parser.add_argument(
        "--lookup-dir",
        type=Path,
        default=DEFAULT_LOOKUP_DIR,
        help=f"Path to lookup_tables directory (default: {DEFAULT_LOOKUP_DIR})",
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


def load_request_ids(requests_csv: Path) -> list[str]:
    """Read request_id values from request.csv.

    Loads all request IDs from the CSV file. Expects a 'req_id' column
    or uses the first column if no header is found.

    Args:
        requests_csv: Path to the request CSV file.

    Returns:
        list[str]: Non-empty request_id values.

    Raises:
        FileNotFoundError: If request.csv file does not exist.
        ValueError: If the file is empty or has no valid request IDs.
    """
    if not requests_csv.exists():
        raise FileNotFoundError(f"request.csv not found: {requests_csv}")

    with requests_csv.open("r", encoding="utf-8", newline="") as handle:
        raw_rows = [row for row in csv.reader(handle) if any(cell.strip() for cell in row)]

    if not raw_rows:
        raise ValueError(f"request.csv is empty: {requests_csv}")

    header = [item.strip().lower() for item in raw_rows[0]]
    if "req_id" in header:
        req_id_idx = header.index("req_id")
        data_rows = raw_rows[1:]
    else:
        req_id_idx = 0
        data_rows = raw_rows

    request_ids = []
    seen = set()
    for row in data_rows:
        if req_id_idx >= len(row):
            continue
        req_id = row[req_id_idx].strip()
        if req_id and req_id not in seen:
            seen.add(req_id)
            request_ids.append(req_id)

    if not request_ids:
        raise ValueError(f"No valid request IDs found in: {requests_csv}")
    return request_ids


def load_volunteer_ids(volunteer_details_csv: Path) -> list[str]:
    """Read volunteer user_id values from volunteer_details.csv.

    Loads all user_ids from the volunteer_details CSV file. These are the
    actual volunteers available for assignment.

    Args:
        volunteer_details_csv: Path to the volunteer_details CSV file.

    Returns:
        list[str]: Non-empty user_id values (volunteers).

    Raises:
        FileNotFoundError: If volunteer_details.csv file does not exist.
        ValueError: If the file is empty or has no valid volunteer IDs.
    """
    if not volunteer_details_csv.exists():
        raise FileNotFoundError(f"volunteer_details.csv not found: {volunteer_details_csv}")

    with volunteer_details_csv.open("r", encoding="utf-8", newline="") as handle:
        raw_rows = [row for row in csv.reader(handle) if any(cell.strip() for cell in row)]

    if not raw_rows:
        raise ValueError(f"volunteer_details.csv is empty: {volunteer_details_csv}")

    header = [item.strip().lower() for item in raw_rows[0]]
    if "user_id" in header:
        user_id_idx = header.index("user_id")
        data_rows = raw_rows[1:]
    else:
        user_id_idx = 0
        data_rows = raw_rows

    volunteer_ids = []
    seen = set()
    for row in data_rows:
        if user_id_idx >= len(row):
            continue
        user_id = row[user_id_idx].strip()
        if user_id and user_id not in seen:
            seen.add(user_id)
            volunteer_ids.append(user_id)

    if not volunteer_ids:
        raise ValueError(f"No valid volunteer IDs found in: {volunteer_details_csv}")
    return volunteer_ids


def load_existing_assignments(output_csv: Path) -> set[tuple[str, str]]:
    """Read existing volunteer assignments to avoid duplicates.

    Checks if the output CSV file exists and has content, then extracts
    all (request_id, volunteer_id) tuples to prevent duplicate assignments.

    Args:
        output_csv: Path to the volunteers_assigned CSV file.

    Returns:
        set: Set of (request_id, volunteer_id) tuples (empty if file doesn't exist).

    Raises:
        ValueError: If required columns are missing from existing CSV file.
    """
    if not output_csv.exists() or output_csv.stat().st_size == 0:
        return set()

    with output_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return set()

        fieldnames_lower = [name.strip().lower() for name in reader.fieldnames]
        if "request_id" not in fieldnames_lower or "volunteer_id" not in fieldnames_lower:
            raise ValueError(
                f"'request_id' and 'volunteer_id' columns required in: {output_csv}"
            )

        assignments = set()
        for row in reader:
            request_id = row.get("request_id", "").strip()
            volunteer_id = row.get("volunteer_id", "").strip()
            if request_id and volunteer_id:
                assignments.add((request_id, volunteer_id))

    return assignments


def seeded_rng(seed: int, request_id: str, volunteer_id: str) -> random.Random:
    """Create a deterministic RNG for a specific assignment.

    Generates a unique but reproducible random number generator for each
    (request_id, volunteer_id) pair by hashing them with the seed.

    Args:
        seed: Base random seed.
        request_id: Request identifier.
        volunteer_id: Volunteer identifier.

    Returns:
        random.Random: Seeded RNG instance unique to this assignment pair.
    """
    digest = hashlib.sha256(f"{seed}:{request_id}:{volunteer_id}".encode("utf-8")).hexdigest()
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


def generate_assignment_row(
    request_id: str, volunteer_id: str, seed: int, now_dt: datetime
) -> dict[str, str]:
    """Generate one volunteers_assigned row for a request-volunteer pair.

    Creates a complete volunteer assignment record with realistic synthetic data
    including volunteer_type and last_update_date. Randomization is deterministic
    based on the request_id, volunteer_id, and seed.

    Args:
        request_id: The request being assigned.
        volunteer_id: The volunteer being assigned.
        seed: Random seed used to derive pair-specific RNG.
        now_dt: Current datetime reference point for relative date generation.

    Returns:
        dict[str, str]: Assignment record with all fields as strings, ready for CSV output.
    """
    rng = seeded_rng(seed, request_id, volunteer_id)

    volunteer_type = rng.choice(VOLUNTEER_TYPES)
    last_update_date = random_datetime(rng, now_dt - timedelta(days=365), now_dt)

    return {
        "request_id": request_id,
        "volunteer_id": volunteer_id,
        "volunteer_type": volunteer_type,
        "last_update_date": format_ts(last_update_date),
    }


def ensure_output_header(output_csv: Path, columns: list[str]) -> bool:
    """Ensure output CSV exists with header; return True if header was created.

    Checks if the output CSV file exists with content. If not, creates the file
    with the header row containing the schema column names. Handles directory
    creation if needed.

    Args:
        output_csv: Path to the volunteers_assigned CSV file.
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
    """Append generated volunteer assignment rows to CSV using schema column order.

    Writes volunteer assignment records to the output CSV file in append mode,
    respecting the column order defined in the schema.

    Args:
        output_csv: Path to the volunteers_assigned CSV file.
        columns: Ordered list of column names from the schema.
        rows: List of assignment record dictionaries to append.

    Returns:
        int: Number of rows actually written to the file.
    """
    if not rows:
        return 0
    with output_csv.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writerows(rows)
    return len(rows)


def generate_assignments(
    request_ids: list[str],
    volunteer_ids: list[str],
    num_assignments: int,
    existing_assignments: set[tuple[str, str]],
    seed: int,
    now_dt: datetime,
) -> list[dict[str, str]]:
    """Generate volunteer assignment records with relationship constraints.

    Creates the requested number of unique volunteer assignments by:
    1. Avoiding duplicate (request_id, volunteer_id) pairs
    2. Ensuring both IDs exist in their respective sources
    3. Using deterministic randomization for reproducibility

    Args:
        request_ids: List of available request IDs.
        volunteer_ids: List of available volunteer IDs.
        num_assignments: Target number of assignments to generate.
        existing_assignments: Set of (request_id, volunteer_id) pairs to skip.
        seed: Random seed for reproducible generation.
        now_dt: Current datetime for relative date generation.

    Returns:
        list[dict[str, str]]: Generated assignment records (may be fewer than requested
                              if unique combinations are exhausted).
    """
    rng = random.Random(seed)
    rows = []
    generated_count = 0
    max_attempts = num_assignments * 10  # Prevent infinite loops

    while generated_count < num_assignments and max_attempts > 0:
        max_attempts -= 1
        request_id = rng.choice(request_ids)
        volunteer_id = rng.choice(volunteer_ids)

        # Skip if this assignment already exists
        if (request_id, volunteer_id) in existing_assignments:
            continue

        # Generate the row
        row = generate_assignment_row(request_id, volunteer_id, seed, now_dt)
        rows.append(row)
        existing_assignments.add((request_id, volunteer_id))
        generated_count += 1

    return rows


def main() -> None:
    """Entry point for volunteers_assigned CSV generation.

    Orchestrates the complete workflow:
    1. Parse CLI arguments and load configuration
    2. Read request and volunteer IDs from their respective CSV files
    3. Identify existing assignments (to avoid duplicates)
    4. Generate new volunteer assignment records respecting constraints
    5. Write results to output CSV with appropriate headers
    6. Print summary statistics to stdout

    All operations are safe for repeated runs (idempotent) - existing
    assignments are preserved and only new assignments are appended.
    """
    args = parse_args()
    now_dt = datetime.now().replace(microsecond=0)

    try:
        columns = load_table_columns(args.schema_json, "volunteers_assigned")
        request_ids = load_request_ids(args.requests_csv)
        volunteer_ids = load_volunteer_ids(args.volunteer_details_csv)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        return

    existing_assignments = load_existing_assignments(args.output_csv)

    # Calculate how many new assignments we need
    total_possible = len(request_ids) * len(volunteer_ids)
    needed_count = min(
        args.num_assignments - len(existing_assignments),
        total_possible - len(existing_assignments),
    )

    if needed_count <= 0:
        print("All requested assignments have already been generated.")
        print(f"output_csv={args.output_csv}")
        return

    rows = generate_assignments(
        request_ids=request_ids,
        volunteer_ids=volunteer_ids,
        num_assignments=needed_count,
        existing_assignments=existing_assignments,
        seed=args.seed,
        now_dt=now_dt,
    )

    header_created = ensure_output_header(args.output_csv, columns)
    rows_appended = append_rows(args.output_csv, columns, rows)

    print(f"requests_found={len(request_ids)}")
    print(f"volunteers_found={len(volunteer_ids)}")
    print(f"total_possible_assignments={len(request_ids) * len(volunteer_ids)}")
    print(f"target_assignments={args.num_assignments}")
    print(f"existing_assignments={len(existing_assignments)}")
    print(f"rows_appended={rows_appended}")
    print(f"header_created={str(header_created).lower()}")
    print(f"output_csv={args.output_csv}")



if __name__ == "__main__":
    main()
