"""Loads and joins the three #336 input CSVs (organizations, states,
countries) into a single normalized DataFrame.

Two things worth calling out, both found while reviewing #336's other
in-flight implementations:

  - is_collaborator encoding is not specified anywhere, and different mock
    CSVs in this repo use different conventions. Some implementations only
    accept "true"/"false" and silently treat anything else as False, which
    corrupts the collaborators metric with no error. This loader accepts
    several common encodings and raises on anything it doesn't recognize,
    so a bad value is loud instead of silent.

  - created_at may or may not include a time/timezone component depending
    on the exporter. Some implementations assume a naive date and crash
    (TypeError: can't compare naive and aware datetimes) the moment the
    column is timezone-aware. This loader normalizes everything to UTC.
"""
import os

import pandas as pd

REQUIRED_COLUMNS = {
    "organizations": ("org_id", "state_id", "city_name", "is_collaborator", "created_at"),
    "states": ("state_id", "state_name", "country_id"),
    "countries": ("country_id", "country_code"),
}

_TRUE_VALUES = {"true", "1", "yes", "y", "t"}
_FALSE_VALUES = {"false", "0", "no", "n", "f"}


class DataLoadError(ValueError):
    """Raised when the local CSV inputs are missing, malformed, or invalid."""


def _mock_data_dir(data_dir=None):
    if data_dir is not None:
        return data_dir
    configured = os.environ.get("MOCK_DATA_DIR")
    if not configured:
        raise DataLoadError(
            "No data directory given: pass data_dir or set MOCK_DATA_DIR"
        )
    return configured


def _read_csv(directory, filename, required_columns):
    path = os.path.join(directory, filename)
    if not os.path.isfile(path):
        raise DataLoadError(f"Missing required file: {path}")
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError as exc:
        raise DataLoadError(f"{filename}: file is empty") from exc
    except pd.errors.ParserError as exc:
        raise DataLoadError(f"{filename}: could not be parsed as CSV") from exc

    missing = set(required_columns) - set(df.columns)
    if missing:
        raise DataLoadError(f"{filename}: missing required columns: {sorted(missing)}")
    return df


def _normalize_is_collaborator(series, filename):
    normalized = series.astype(str).str.strip().str.lower()
    unrecognized = ~normalized.isin(_TRUE_VALUES | _FALSE_VALUES)
    if unrecognized.any():
        bad_values = sorted(set(series[unrecognized].astype(str)))
        raise DataLoadError(
            f"{filename}: column 'is_collaborator' has unrecognized values {bad_values}; "
            f"expected one of {sorted(_TRUE_VALUES | _FALSE_VALUES)}"
        )
    return normalized.isin(_TRUE_VALUES)


def _normalize_created_at(series, filename):
    # Parsed element-wise rather than via pd.to_datetime(series, ...) directly:
    # that column-wide fast path infers ONE format from an early value and
    # applies it to the whole column, silently marking every row in a
    # different (but valid) format as unparseable -- exactly the mixed
    # date-only / full-timestamp scenario this loader needs to tolerate.
    parsed = series.apply(lambda value: pd.to_datetime(value, utc=True, errors="coerce"))
    if parsed.isna().any():
        bad_rows = series[parsed.isna()].tolist()
        raise DataLoadError(f"{filename}: column 'created_at' has unparseable values {bad_rows}")
    return pd.to_datetime(parsed, utc=True)  # normalize dtype to datetime64[ns, UTC]


def _assert_unique_key(df, column, filename):
    """A duplicate join key on the right side of a left-merge silently
    fans out matching rows on the left -- e.g. a repeated state_id in
    states.csv would double-count every organization in that state, with
    no error. Catch it before the merge, not after.
    """
    duplicates = df[column][df[column].duplicated()]
    if not duplicates.empty:
        bad_ids = sorted(duplicates.unique().tolist())
        raise DataLoadError(
            f"{filename}: column '{column}' has duplicate value(s) {bad_ids}; "
            f"expected each {column} to appear at most once"
        )


def load_data(data_dir=None):
    """Loads organizations/states/countries and returns one joined DataFrame.

    The returned frame has one row per organization with a `country_code`
    column attached via states.country_id -> countries.country_id, plus a
    normalized boolean `is_collaborator` and a UTC-aware `created_at`.
    """
    directory = _mock_data_dir(data_dir)

    organizations = _read_csv(directory, "organizations.csv", REQUIRED_COLUMNS["organizations"])
    states = _read_csv(directory, "states.csv", REQUIRED_COLUMNS["states"])
    countries = _read_csv(directory, "countries.csv", REQUIRED_COLUMNS["countries"])

    _assert_unique_key(states, "state_id", "states.csv")
    _assert_unique_key(countries, "country_id", "countries.csv")

    organizations = organizations.copy()
    organizations["is_collaborator"] = _normalize_is_collaborator(
        organizations["is_collaborator"], "organizations.csv"
    )
    organizations["created_at"] = _normalize_created_at(
        organizations["created_at"], "organizations.csv"
    )

    merged = organizations.merge(
        states[["state_id", "country_id"]], on="state_id", how="left"
    ).merge(
        countries[["country_id", "country_code"]], on="country_id", how="left"
    )

    unmatched = merged["country_code"].isna()
    if unmatched.any():
        bad_ids = sorted(merged.loc[unmatched, "state_id"].unique().tolist())
        raise DataLoadError(
            f"organizations.csv: state_id(s) {bad_ids} do not resolve to a country via "
            f"states.csv -> countries.csv"
        )

    return merged
