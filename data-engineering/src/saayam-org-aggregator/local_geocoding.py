"""Deterministic local/test fakes; never selected by the Lambda handler."""

from collections.abc import Mapping

from address_geocoding import CoordinateRecord


class FakeGeocodingProvider:
    """Use explicit test responses only; unknown addresses are unmatched, never fabricated."""

    def __init__(self, responses: Mapping[str, CoordinateRecord | Exception | None]):
        self.responses = dict(responses)
        self.calls: list[str] = []

    def geocode(self, address: str) -> CoordinateRecord | None:
        """Record the lookup and return or raise its deterministic configured response."""
        self.calls.append(address)
        response = self.responses.get(address)
        if isinstance(response, Exception):
            raise response
        return response


class FakeCoordinateCache:
    """Instance-local memory only; does not prove persistence across Lambda invocations."""

    def __init__(self, entries: Mapping[str, CoordinateRecord] | None = None):
        self.entries = dict(entries or {})
        self.reads: list[str] = []
        self.writes: list[tuple[str, CoordinateRecord]] = []

    def get(self, address: str) -> CoordinateRecord | None:
        """Read configured or previously saved local coordinates."""
        self.reads.append(address)
        return self.entries.get(address)

    def put(self, address: str, coordinates: CoordinateRecord) -> None:
        """Record and save successful coordinates within this fake instance."""
        self.writes.append((address, coordinates))
        self.entries[address] = coordinates
