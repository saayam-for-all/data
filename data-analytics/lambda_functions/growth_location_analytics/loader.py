"""Load and normalize local CSV inputs for Growth & Location Analytics."""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd
from pandas.errors import EmptyDataError, ParserError, ParserWarning

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
    lookups = {
        name: _load_table(_find_input_file(directory, name, INPUT_FILENAMES[name]), name)
        for name in ("states", "countries")
    }
    return LocalDataTables(organizations=load_organizations(directory), **lookups)


def load_organizations(data_dir: str | os.PathLike[str] | None = None) -> pd.DataFrame:
    """Load normalized organization rows without reading the lookup tables."""

    path = _find_input_file(
        _resolve_data_directory(data_dir), "organizations", INPUT_FILENAMES["organizations"]
    )
    organizations = _load_table(path, "organizations")
    organizations["is_collaborator"] = _normalize_booleans(
        organizations["is_collaborator"], path.name
    )
    organizations["created_at"] = _normalize_timestamps(organizations["created_at"], path.name)
    return organizations


def _resolve_data_directory(
    data_dir: str | os.PathLike[str] | None,
) -> Path:
    """Resolve the explicit path or MOCK_DATA_DIR and require an existing directory."""

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
    """Select the first existing filename in priority order or raise LocalDataError."""

    for filename in filenames:
        candidate = directory / filename
        if candidate.is_file():
            return candidate

    expected = ", ".join(filenames)
    raise LocalDataError(f"Missing {table_name} CSV in {directory}; expected one of: {expected}")


def _load_table(
    path: Path,
    table_name: str,
) -> pd.DataFrame:
    """Read CSV columns and validate IDs/join values; skip blank physical lines."""

    try:
        with warnings.catch_warnings():
            # Prevent excess fields from being silently discarded or used as an index.
            warnings.simplefilter("error", ParserWarning)
            frame = pd.read_csv(
                path,
                dtype="string",
                encoding="utf-8-sig",
                keep_default_na=False,
                index_col=False,
                on_bad_lines="error",
            )
    except EmptyDataError as exc:
        raise LocalDataError(f"{path.name}: missing CSV header") from exc
    except (ParserError, ParserWarning) as exc:
        raise LocalDataError(f"{path.name}: invalid CSV structure") from exc
    except (OSError, UnicodeError) as exc:
        raise LocalDataError(f"{path.name}: unable to read CSV file") from exc

    required_columns = REQUIRED_COLUMNS[table_name]
    missing_columns = sorted(set(required_columns) - set(frame.columns))
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise LocalDataError(f"{path.name}: missing required columns: {missing}")

    for column in required_columns:
        if column in {"org_id", "state_id", "country_id", "country_code"}:
            frame[column] = _normalize_required_strings(frame[column], path.name, column)
    return frame


def _normalize_required_strings(
    values: pd.Series,
    filename: str,
    column: str,
) -> pd.Series:
    """Trim string values and raise LocalDataError for null or blank entries."""

    normalized = values.astype("string").str.strip()
    if (normalized.isna() | normalized.eq("")).any():
        raise LocalDataError(
            f"{filename}: required column '{column}' contains missing or blank values"
        )
    return normalized


def _normalize_booleans(values: pd.Series, filename: str) -> pd.Series:
    """Convert trimmed, case-insensitive true/false strings to nullable booleans.

    Raise LocalDataError for missing values or any other boolean spelling.
    """

    normalized = values.astype("string").str.strip().str.lower()
    invalid = normalized.isna() | ~normalized.isin({"true", "false"})
    if invalid.any():
        raise LocalDataError(
            f"{filename}: column 'is_collaborator' must contain only true or false"
        )
    return normalized.map({"true": True, "false": False}).astype("boolean")


def _normalize_timestamps(values: pd.Series, filename: str) -> pd.Series:
    """Parse ISO timestamps as UTC, interpreting timezone-naive values as UTC.

    Trim surrounding whitespace and reject missing or malformed timestamps
    with LocalDataError. Preserve the input index and series name.
    """

    normalized = values.astype("string").str.strip()
    # pandas 2.2.2 can carry an offset into following naive ISO values. Parse
    # the two groups separately so naive timestamps always mean UTC.
    aware = normalized.str.contains(r"[Tt ].*(?:[Zz]|[+-])", na=False)
    parsed = pd.Series(pd.NaT, index=values.index, name=values.name, dtype="datetime64[ns, UTC]")
    for mask in (aware, ~aware):
        parsed.loc[mask] = pd.to_datetime(
            normalized.loc[mask], format="ISO8601", utc=True, errors="coerce"
        )
    if parsed.isna().any():
        raise LocalDataError(
            f"{filename}: column 'created_at' contains missing or invalid ISO 8601 timestamps"
        )
    return parsed
