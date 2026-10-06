"""Explicit local/test adapter for generator CSVs, never a runtime DB adapter."""

import csv
from collections.abc import Iterable, Mapping
from pathlib import Path
import re

from beneficiary_location import (
    BeneficiaryLocationRecord,
    ProfileAddressRecord,
    RequestRecord,
    _coordinates,
)

Row = Mapping[str, object]
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_POINT = re.compile(
    rf"\s*SRID\s*=\s*4326\s*;\s*POINT\s*\(\s*({_NUMBER})\s+({_NUMBER})\s*\)\s*",
    re.IGNORECASE,
)


def parse_mock_point(value: object) -> tuple[float, float] | None:
    """Parse generator EWKT (longitude latitude), returning validated (latitude, longitude).

    Unsupported SRIDs, shapes, dimensions, and malformed/nonfinite/out-of-range
    pairs are unusable. No coordinates are inferred from another field.
    """
    match = _POINT.fullmatch(value) if isinstance(value, str) else None
    return _coordinates(match[2], match[1]) if match else None


def _key(value: object) -> str:
    """Normalize CSV string IDs and integer generator IDs without inventing identity."""
    if isinstance(value, str):
        return value.strip()
    return str(value) if type(value) is int else ""


def _text(value: object) -> str:
    """Keep supplied names/address text; omit malformed or absent components."""
    return value.strip() if isinstance(value, str) else ""


def _index(rows: Iterable[Row], key: str) -> dict[str, dict[str, object]]:
    """Snapshot rows by identity, rejecting ambiguous duplicates and missing IDs."""
    indexed = {}
    for row in rows:
        identity = _key(row.get(key))
        if not identity:
            raise ValueError(f"Local mock record requires {key}")
        if identity in indexed:
            raise ValueError(f"Duplicate local mock record for {key}")
        indexed[identity] = dict(row)
    return indexed


def _read_csv(path: Path, identity_column: str) -> list[dict[str, str]]:
    """Read explicitly selected local CSVs without generating or modifying files."""
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if identity_column not in (reader.fieldnames or []):
            raise ValueError(f"Local mock CSV requires {identity_column} header")
        return list(reader)


class LocalMockLocationRecordSource:
    """Adapt inspected mock structures to the existing resolver's record interface.

    Requests must be supplied separately as explicitly synthetic fixtures with
    request_id, beneficiary_id, and optional req_loc. No generator requests table
    or real database schema is assumed. Construction/import does not load files.
    """

    def __init__(
        self,
        *,
        synthetic_requests: Iterable[Row],
        users: Iterable[Row] = (),
        user_locations: Iterable[Row] = (),
        states: Iterable[Row] = (),
        countries: Iterable[Row] = (),
    ):
        self._requests = _index(synthetic_requests, "request_id")
        self._users = _index(users, "user_id")
        self._locations = _index(user_locations, "user_id")
        self._states = _index(states, "state_id")
        self._countries = _index(countries, "country_id")

    @classmethod
    def from_csv_directory(
        cls, directory: str | Path, *, synthetic_requests: Iterable[Row]
    ) -> "LocalMockLocationRecordSource":
        """Explicitly load four local CSVs; missing files/identity headers raise.

        Never called by the live handler. cities.csv is neither read nor required.
        """
        directory = Path(directory)
        return cls(
            synthetic_requests=synthetic_requests,
            users=_read_csv(directory / "users.csv", "user_id"),
            user_locations=_read_csv(directory / "user_locations.csv", "user_id"),
            states=_read_csv(directory / "states.csv", "state_id"),
            countries=_read_csv(directory / "countries.csv", "country_id"),
        )

    def get_request(self, request_id: str) -> RequestRecord | None:
        """Retrieve a synthetic request without filtering away beneficiary mismatches."""
        row = self._requests.get(request_id)
        if row is None:
            return None
        lat, lon = parse_mock_point(row.get("req_loc")) or (None, None)
        return RequestRecord(_key(row.get("request_id")), _key(row.get("beneficiary_id")), lat, lon)

    def get_beneficiary_location(self, beneficiary_id: str) -> BeneficiaryLocationRecord | None:
        """Use only user_locations.curr_loc, excluding previous/viewer/volunteer locations."""
        row = self._locations.get(beneficiary_id)
        if row is None:
            return None
        lat, lon = parse_mock_point(row.get("curr_loc")) or (None, None)
        return BeneficiaryLocationRecord(_key(row.get("user_id")), lat, lon)

    def get_profile_address(self, beneficiary_id: str) -> ProfileAddressRecord | None:
        """Assemble supplied profile components and lookup names, never raw geography IDs."""
        user = self._users.get(beneficiary_id)
        if user is None:
            return None
        state = self._states.get(_key(user.get("state_id")), {})
        country_id = _key(user.get("country_id")) or _key(state.get("country_id"))
        country = self._countries.get(country_id, {})
        # An inconsistent mock foreign key must not add a state from another country.
        state_country = _key(state.get("country_id"))
        state_name = _text(state.get("state_name")) if state_country == country_id else ""
        parts = [
            _text(user.get("addr_ln1")),
            _text(user.get("addr_ln2")),
            _text(user.get("addr_ln3")),
            _text(user.get("city_name")),
            state_name,
            _key(user.get("zip_code")),
            _text(country.get("country_name")),
        ]
        address = ", ".join(part for part in parts if part) or None
        return ProfileAddressRecord(_key(user.get("user_id")), address)
