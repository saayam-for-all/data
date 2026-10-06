"""Offline address adapters for supplied aggregator/mock contracts, not live SQL."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from local_location_records import Row, _index, _key, _text


@dataclass(frozen=True)
class OrganizationAddress:
    """Keep every organization and its original fields alongside optional address text.

    online_only is an explicit caller classification; None means unclassified.
    No source field, organization name, URL, or location text implies online-only.
    """

    record: Mapping[str, object]
    source: Literal["db", "ai"]
    address: str | None
    online_only: bool | None = None


class OrganizationAddressAssembler:
    """Resolve mock organizations.state_id -> states.country_id -> countries names.

    Stored city_name is used directly. No cities join or centroid substitution.
    Lookup rows are snapshotted and ambiguous/missing identities raise.
    """

    def __init__(self, *, states: Iterable[Row] = (), countries: Iterable[Row] = ()):
        self._states = _index(states, "state_id")
        self._countries = _index(countries, "country_id")

    def from_database(
        self, row: Row, *, online_only: bool | None = None
    ) -> OrganizationAddress:
        """Assemble all available components, omitting unresolved IDs and malformed values."""
        state = self._states.get(_key(row.get("state_id")), {})
        country = self._countries.get(_key(state.get("country_id")), {})
        parts = [
            _text(row.get("street")),
            _text(row.get("city_name")),
            _text(state.get("state_name")),
            _key(row.get("zip_code")),
            _text(country.get("country_name")),
        ]
        address = ", ".join(part for part in parts if part) or None
        return _address_record(row, "db", address, online_only)


def from_genai(
    row: Row,
    *,
    online_only: bool | None = None,
    location_reader: Callable[[Row], object] | None = None,
) -> OrganizationAddress:
    """Use helper's location text; alternate payload mappings require explicit injection."""
    value = location_reader(row) if location_reader is not None else row.get("location")
    return _address_record(row, "ai", _text(value) or None, online_only)


def _address_record(
    row: Row, source: Literal["db", "ai"], address: str | None, online_only: bool | None
) -> OrganizationAddress:
    """Snapshot fields and make missing location explicit without removing a record."""
    record = dict(row)
    if address is None:
        record.update(distance=None, distance_status="unknown_location")
    return OrganizationAddress(record, source, address, online_only)
