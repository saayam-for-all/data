"""Clean the collected CSV, then rebuild JSON and its provenance together."""

from pathlib import Path

import pandas as pd

if __package__:
    from .build_emergency_numbers import build_with_provenance, save_dataset, strip_references
else:
    from build_emergency_numbers import build_with_provenance, save_dataset, strip_references

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_CSV_PATH = PROJECT_ROOT / "datasets/raw/emergency_numbers.csv"
CLEANED_CSV_PATH = PROJECT_ROOT / "datasets/cleaned/cleaned_emergency_numbers.csv"
CLEANED_JSON_PATH = PROJECT_ROOT / "datasets/cleaned/emergency_numbers.json"
PROVENANCE_PATH = PROJECT_ROOT / "datasets/cleaned/emergency_numbers_provenance.json"


def clean_emergency_data(raw_path=RAW_CSV_PATH, csv_path=CLEANED_CSV_PATH,
                         json_path=CLEANED_JSON_PATH, provenance_path=PROVENANCE_PATH):
    """Preserve phone strings and notes; never infer values for missing cells."""
    data = pd.read_csv(raw_path, dtype=str, keep_default_na=False)
    expected = {"Country", "Police", "Ambulance", "Fire", "Notes"}
    if not expected.issubset(data.columns):
        raise ValueError(f"Missing CSV columns: {expected - set(data.columns)}")
    data = data[data["Country"] != "Country"].copy()
    for column in expected:
        data[column] = data[column].map(strip_references)
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(csv_path, index=False, encoding="utf-8")
    dataset, report = build_with_provenance(csv_path)
    save_dataset(dataset, json_path)
    save_dataset(report, provenance_path)
    return dataset, report


if __name__ == "__main__":
    dataset, report = clean_emergency_data()
    print(f"Rebuilt {len(dataset)} countries and {len(report['contacts'])} sourced contacts.")
