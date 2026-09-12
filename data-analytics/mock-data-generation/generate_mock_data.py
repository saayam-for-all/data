from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from config import DEFAULT_CONFIG, GeneratorConfig
from generators import generate_all
from schema import CSV_FILE_NAMES, TABLE_COLUMNS
from utils import write_csv
from validation import validate_all


BASE_DIR = Path(__file__).resolve().parent


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate schema-aligned synthetic CSV data for "
            "Saayam Virginia analytics tables."
        )
    )

    parser.add_argument(
        "--users",
        type=int,
        default=DEFAULT_CONFIG.users,
        help=(
            "Number of users to generate. "
            f"Default: {DEFAULT_CONFIG.users}"
        ),
    )

    parser.add_argument(
        "--organizations",
        type=int,
        default=DEFAULT_CONFIG.organizations,
        help=(
            "Number of organizations to generate. "
            f"Default: {DEFAULT_CONFIG.organizations}"
        ),
    )

    parser.add_argument(
        "--cities-per-state",
        type=int,
        default=DEFAULT_CONFIG.cities_per_state,
        help=(
            "Number of synthetic cities generated for each "
            "configured state."
        ),
    )

    parser.add_argument(
        "--volunteer-ratio",
        type=float,
        default=DEFAULT_CONFIG.volunteer_ratio,
        help=(
            "Fraction of users that receive a "
            "volunteer_details record."
        ),
    )

    parser.add_argument(
        "--user-location-ratio",
        type=float,
        default=DEFAULT_CONFIG.user_location_ratio,
        help=(
            "Fraction of users that receive a "
            "user_locations record."
        ),
    )

    parser.add_argument(
        "--volunteer-location-ratio",
        type=float,
        default=DEFAULT_CONFIG.volunteer_location_ratio,
        help=(
            "Fraction of volunteers that receive a "
            "volunteer_locations record."
        ),
    )

    parser.add_argument(
        "--skills-min",
        type=int,
        default=DEFAULT_CONFIG.skills_per_user_min,
        help="Minimum skills generated per user.",
    )

    parser.add_argument(
        "--skills-max",
        type=int,
        default=DEFAULT_CONFIG.skills_per_user_max,
        help="Maximum skills generated per user.",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_CONFIG.seed,
        help=(
            "Random seed used for reproducible generation. "
            f"Default: {DEFAULT_CONFIG.seed}"
        ),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=BASE_DIR,
        help=(
            "Directory where generated CSV files are written. "
            "Default: mock-data-generation directory."
        ),
    )

    return parser.parse_args()


def build_config(
    args: argparse.Namespace,
) -> GeneratorConfig:
    config = replace(
        DEFAULT_CONFIG,
        seed=args.seed,
        users=args.users,
        organizations=args.organizations,
        cities_per_state=args.cities_per_state,
        volunteer_ratio=args.volunteer_ratio,
        user_location_ratio=args.user_location_ratio,
        volunteer_location_ratio=(
            args.volunteer_location_ratio
        ),
        skills_per_user_min=args.skills_min,
        skills_per_user_max=args.skills_max,
    )

    config.validate()

    return config


def write_all_csv_files(
    data: dict,
    output_dir: Path,
) -> None:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    for table_name, rows in data.items():
        output_path = (
            output_dir
            / CSV_FILE_NAMES[table_name]
        )

        write_csv(
            output_path,
            TABLE_COLUMNS[table_name],
            rows,
        )


def print_summary(
    data: dict,
    output_dir: Path,
) -> None:
    print()
    print("Mock data generation completed successfully.")
    print(f"Output directory: {output_dir.resolve()}")
    print()

    print("Generated rows:")

    total_rows = 0

    for table_name in TABLE_COLUMNS:
        row_count = len(data[table_name])
        total_rows += row_count

        print(
            f"  {table_name:<22} {row_count:>6}"
        )

    print("  " + "-" * 29)
    print(f"  {'TOTAL':<22} {total_rows:>6}")
    print()
    print("Validation: PASSED")


def main() -> None:
    args = parse_arguments()

    config = build_config(args)

    data = generate_all(config)

    print("Validating generated data...")

    validate_all(data)

    print("Validation passed.")
    print("Writing CSV files...")

    write_all_csv_files(
        data,
        args.output_dir,
    )

    print_summary(
        data,
        args.output_dir,
    )


if __name__ == "__main__":
    main()