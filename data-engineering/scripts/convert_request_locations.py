"""Convert req_loc in a local requests CSV, preserving its rows and columns."""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils.request_location import convert_request_locations


def convert_csv(source: Path, destination: Path) -> tuple[int, int]:
    """Write converted CSV; return row count and count of empty output locations."""
    if source.resolve() == destination.resolve():
        raise ValueError("Input and output paths must be different")
    with source.open(encoding="utf-8-sig", newline="") as input_file:
        reader = csv.DictReader(input_file)
        if not reader.fieldnames or "req_loc" not in reader.fieldnames:
            raise ValueError("Input CSV must contain a req_loc column")
        with destination.open("w", encoding="utf-8", newline="") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=reader.fieldnames, lineterminator="\n")
            writer.writeheader()
            count = empty = 0
            for row in convert_request_locations(reader):
                writer.writerow(row)
                count += 1
                empty += row["req_loc"] is None
    return count, empty


def main() -> None:
    """Run the local converter; no AWS or database connection is made."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        count, empty = convert_csv(args.source, args.destination)
    except (OSError, ValueError, csv.Error) as error:
        parser.exit(1, f"Conversion failed: {error}\n")
    print(f"Exported {count} rows; {empty} null/invalid locations written as empty fields.")


if __name__ == "__main__":
    main()
