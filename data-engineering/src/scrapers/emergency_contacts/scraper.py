"""Collect source tables without losing merged cells or dialing prefixes."""

from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_DATA_PATH = PROJECT_ROOT / "datasets/raw/emergency_numbers.csv"
SOURCE_URL = "https://en.wikipedia.org/wiki/List_of_emergency_telephone_numbers"
COLUMNS = ["Country", "Police", "Ambulance", "Fire", "Notes"]


def expand_table(table):
    """Expand HTML rowspan/colspan into a rectangular grid of text cells."""
    spans = {}
    for row in table.find_all("tr"):
        values = {}
        for column, (remaining, value) in list(spans.items()):
            values[column] = value
            if remaining == 1:
                del spans[column]
            else:
                spans[column] = (remaining - 1, value)
        column = 0
        for cell in row.find_all(["th", "td"], recursive=False):
            while column in values:
                column += 1
            value = cell.get_text(" ", strip=True)
            width = int(cell.get("colspan", 1))
            height = int(cell.get("rowspan", 1))
            for offset in range(width):
                position = column + offset
                if position in values:
                    raise ValueError("Overlapping table spans")
                values[position] = value
                if height > 1:
                    spans[position] = (height - 1, value)
            column += width
        if values:
            yield [values.get(i, "") for i in range(max(values) + 1)]


def parse_emergency_numbers(html: str) -> pd.DataFrame:
    """Read emergency tables by their headers, preserving notes separately."""
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for table in soup.select("table.wikitable"):
        rows = iter(expand_table(table))
        header = next(rows, [])
        normalized = ["Notes" if value == "Other numbers" else value for value in header]
        if not set(COLUMNS[:4]).issubset(normalized):
            continue
        for row in rows:
            if row == header:
                continue
            if len(row) != len(header):
                raise ValueError(f"Unexpected table width for {row[0]!r}")
            record = dict(zip(normalized, row))
            if record["Country"]:
                records.append({key: record.get(key, "") for key in COLUMNS})
    if not records:
        raise ValueError("No emergency-number records found; output was not overwritten")
    return pd.DataFrame(records, columns=COLUMNS)


def scrape_emergency_numbers(output_path=RAW_DATA_PATH):
    """Download and validate the source before replacing the raw CSV."""
    response = requests.get(
        SOURCE_URL, headers={"User-Agent": "Saayam emergency contacts/1.0"}, timeout=30
    )
    response.raise_for_status()
    data = parse_emergency_numbers(response.text)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(output_path, index=False, encoding="utf-8")
    return data


if __name__ == "__main__":
    print(f"Collected {len(scrape_emergency_numbers())} source records.")
