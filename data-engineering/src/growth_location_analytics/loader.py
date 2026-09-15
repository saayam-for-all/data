"""Load and normalize local CSV inputs for Growth & Location Analytics."""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd
from pandas.errors import EmptyDataError, ParserError


REQUIRED_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "organizations": (
        "org_id",
        "state_id",
        "city_name",
        "is_collaborator",
        "created_at",
    ),
    "states": ("state_id", "state_name", "country_id"),
    "countries": ("country_id", "country_code"),
}

# The plural names are the issue's canonical interface. The singular aliases
# retain compatibility with the tracked reference datasets in data-analytics/sql.
INPUT_FILENAMES: Mapping[str, tuple[str, ...]] = {
    "organizations": ("organizations.csv",),
    "states": ("states.csv", "state.csv"),
    "countries": ("countries.csv", "country.csv"),
}

_ISO_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}"
    r"(?::\d{2}(?:\.\d{1,9})?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?"
    r")?$"
)


class LocalDataError(ValueError):
    """Raised when local analytics inputs cannot be loaded or validated."""


@dataclass(frozen=True)
class LocalDataTables:
    """The three normalized source tables, kept separate for later analytics."""

    organizations: pd.DataFrame
    states: pd.DataFrame
    countries: pd.DataFrame


def load_local_data(data_dir: str | os.PathLike[str] | None = None) -> LocalDataTables:
    """Load and normalize the three analytics CSVs from a local directory.

    An explicit ``data_dir`` takes precedence. If it is omitted, the directory
    must be supplied through ``MOCK_DATA_DIR``. No files are accessed until this
    function is called.
    """

    directory = _resolve_data_directory(data_dir)
    paths = {
        table_name: _find_input_file(directory, table_name, filenames)
        for table_name, filenames in INPUT_FILENAMES.items()
    }

    organizations = _load_table(
        paths["organizations"], "organizations", REQUIRED_COLUMNS["organizations"]
    )
    states = _load_table(paths["states"], "states", REQUIRED_COLUMNS["states"])
    countries = _load_table(
        paths["countries"], "countries", REQUIRED_COLUMNS["countries"]
    )

    organizations["is_collaborator"] = _normalize_booleans(
        organizations["is_collaborator"], paths["organizations"].name
    )
    organizations["created_at"] = _normalize_timestamps(
        organizations["created_at"], paths["organizations"].name
    )

    return LocalDataTables(
        organizations=organizations,
        states=states,
        countries=countries,
    )


def _resolve_data_directory(
    data_dir: str | os.PathLike[str] | None,
) -> Path:
    if data_dir is None:
        configured_dir = os.getenv("MOCK_DATA_DIR")
        if not configured_dir:
            raise LocalDataError(
                "Local data directory is required: pass data_dir or set MOCK_DATA_DIR"
            )
        directory = Path(configured_dir).expanduser()
    else:
        directory = Path(data_dir).expanduser()

    if not directory.exists():
        raise LocalDataError(f"Local data directory does not exist: {directory}")
    if not directory.is_dir():
        raise LocalDataError(f"Local data path is not a directory: {directory}")
    return directory


def _find_input_file(
    directory: Path,
    table_name: str,
    filenames: Sequence[str],
) -> Path:
    for filename in filenames:
        candidate = directory / filename
        if candidate.is_file():
            return candidate

    expected = ", ".join(filenames)
    raise LocalDataError(
        f"Missing {table_name} CSV in {directory}; expected one of: {expected}"
    )


def _load_table(
    path: Path,
    table_name: str,
    required_columns: Sequence[str],
) -> pd.DataFrame:
    _validate_csv_structure(path)
    try:
        frame = pd.read_csv(
            path,
            dtype="string",
            encoding="utf-8-sig",
            keep_default_na=False,
            skip_blank_lines=False,
        )
    except EmptyDataError as exc:
        raise LocalDataError(f"{path.name}: missing CSV header") from exc
    except ParserError as exc:
        raise LocalDataError(f"{path.name}: invalid CSV structure") from exc
    except (OSError, UnicodeError) as exc:
        raise LocalDataError(f"{path.name}: unable to read CSV file") from exc

    missing_columns = sorted(set(required_columns) - set(frame.columns))
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise LocalDataError(f"{path.name}: missing required columns: {missing}")

    normalized = frame.copy()
    for column in required_columns:
        if table_name == "organizations" and column in {
            "is_collaborator",
            "created_at",
        }:
            continue
        normalized[column] = _normalize_required_strings(
            normalized[column], path.name, column
        )

    # Validate before type conversion so missing required values get one clear,
    # consistent error instead of being mixed with malformed-value errors.
    for column in required_columns:
        if (
            normalized[column].isna()
            | normalized[column].astype("string").str.strip().eq("")
        ).any():
            raise LocalDataError(
                f"{path.name}: required column '{column}' contains missing or "
                "blank values"
            )

    return normalized


def _validate_csv_structure(path: Path) -> None:
    """Reject blank records and rows whose field count differs from the header."""

    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle, strict=True)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise LocalDataError(f"{path.name}: missing CSV header") from exc

            if not header or not any(column.strip() for column in header):
                raise LocalDataError(f"{path.name}: missing CSV header")

            expected_fields = len(header)
            for record_number, row in enumerate(reader, start=2):
                if not row:
                    raise LocalDataError(
                        f"{path.name}: blank CSV record at record {record_number}"
                    )
                if len(row) != expected_fields:
                    raise LocalDataError(
                        f"{path.name}: inconsistent field count at record "
                        f"{record_number}; expected {expected_fields}, found {len(row)}"
                    )
    except LocalDataError:
        raise
    except csv.Error as exc:
        raise LocalDataError(f"{path.name}: invalid CSV structure") from exc
    except (OSError, UnicodeError) as exc:
        raise LocalDataError(f"{path.name}: unable to read CSV file") from exc


def _normalize_required_strings(
    values: pd.Series,
    filename: str,
    column: str,
) -> pd.Series:
    normalized = values.astype("string").str.strip()
    if (normalized.isna() | normalized.eq("")).any():
        raise LocalDataError(
            f"{filename}: required column '{column}' contains missing or blank values"
        )
    return normalized


def _normalize_booleans(values: pd.Series, filename: str) -> pd.Series:
    normalized = values.astype("string").str.strip().str.lower()
    invalid = normalized.isna() | ~normalized.isin({"true", "false"})
    if invalid.any():
        raise LocalDataError(
            f"{filename}: column 'is_collaborator' must contain only true or false"
        )
    return normalized.map({"true": True, "false": False}).astype("boolean")


def _normalize_timestamps(values: pd.Series, filename: str) -> pd.Series:
    normalized = values.astype("string").str.strip()
    missing = normalized.isna() | normalized.eq("")
    if missing.any():
        raise LocalDataError(
            f"{filename}: required column 'created_at' contains missing or blank values"
        )

    if not normalized.str.fullmatch(_ISO_TIMESTAMP_PATTERN).all():
        raise LocalDataError(
            f"{filename}: column 'created_at' contains invalid ISO 8601 timestamps"
        )

    parsed_values: list[pd.Timestamp] = []
    try:
        for value in normalized:
            timestamp = pd.Timestamp(value)
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize("UTC")
            else:
                timestamp = timestamp.tz_convert("UTC")
            parsed_values.append(timestamp)
    except (TypeError, ValueError) as exc:
        raise LocalDataError(
            f"{filename}: column 'created_at' contains invalid ISO 8601 timestamps"
        ) from exc

    return pd.Series(
        parsed_values,
        index=values.index,
        name=values.name,
        dtype="datetime64[ns, UTC]",
    )
