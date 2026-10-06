"""Generate small, local-only CSV fixtures for running issue #376."""

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


def sample_tables(now: datetime) -> tuple:
    """Build deterministic examples of both flags, neither flag, and each flag."""
    organizations = pd.DataFrame([
        ("a", "small", True, True, "non_profit", "CA", now - timedelta(days=1)),
        ("b", "medium", False, False, "for_profit", "CA", now - timedelta(days=2)),
        ("c", "small", True, False, "non_profit", "KA", now - timedelta(days=6)),
        ("d", "large", False, True, "non_profit", "CA", now - timedelta(days=10)),
        ("e", "medium", True, True, "for_profit", "KA", now - timedelta(days=40)),
        ("f", "small", False, True, "non_profit", "CA", now - timedelta(days=400)),
        ("g", "large", True, True, "for_profit", "ON", now + timedelta(days=1)),
        ("h", "small", False, False, "non_profit", "unknown", now - timedelta(days=100)),
    ], columns=[
        "org_id", "org_size", "is_collaborator", "is_contributor",
        "org_type", "state_id", "created_at",
    ])
    states = pd.DataFrame([
        ("CA", "001"), ("KA", "002"), ("ON", "003"),
    ], columns=["state_id", "country_id"])
    countries = pd.DataFrame([
        ("001", "USA", "United States"),
        ("002", "IND", "India"),
        ("003", "CAN", "Canada"),
    ], columns=["country_id", "country_code", "country_name"])
    return organizations, states, countries


def write_tables(directory: Path, tables: tuple) -> None:
    """Write fixture tables with pandas; callers choose an ignored/temp folder."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, frame in zip(("organizations", "states", "countries"), tables):
        frame.to_csv(directory / f"{name}.csv", index=False)


def main() -> None:
    """Create a fresh fixture without overwriting existing local CSVs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).parent / "mock_data"
    )
    args = parser.parse_args()
    paths = [args.output / f"{name}.csv" for name in (
        "organizations", "states", "countries"
    )]
    if any(path.exists() for path in paths):
        parser.error("The output contains CSVs already; choose a fresh --output directory.")
    now = datetime.now(timezone.utc)
    write_tables(args.output, sample_tables(now))
    print(f"Created 8 organizations and their lookups in {args.output}")
    print(f"Fixture reference time (UTC): {now.isoformat()}")


if __name__ == "__main__":
    main()
