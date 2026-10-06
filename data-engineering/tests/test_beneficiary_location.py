"""Synthetic local-only records for #433 task 1; no DB, AWS, or geocoder calls."""

import importlib.util
from pathlib import Path
import sys

import pytest


# The existing Lambda directory contains a hyphen and is deployed as loose modules.
MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src/saayam-org-aggregator/beneficiary_location.py"
)
SPEC = importlib.util.spec_from_file_location("beneficiary_location", MODULE_PATH)
location = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = location
SPEC.loader.exec_module(location)

REQUEST_ID = "synthetic-request"
BENEFICIARY_ID = "synthetic-beneficiary"


class SyntheticRecordSource:
    """Clearly synthetic injectable source, used only in these offline tests."""

    def __init__(self, request=None, current=None, profile=None):
        self.request = request
        self.current = current
        self.profile = profile
        self.calls = []
        self.viewer_location = (45, 60)  # Must never participate in resolution.

    def get_request(self, request_id):
        """Return the synthetic request while recording lookup identity."""
        self.calls.append(("request", request_id))
        return self.request

    def get_beneficiary_location(self, beneficiary_id):
        """Return the synthetic current location."""
        self.calls.append(("current", beneficiary_id))
        return self.current

    def get_profile_address(self, beneficiary_id):
        """Return the synthetic profile address."""
        self.calls.append(("profile", beneficiary_id))
        return self.profile


def synthetic_source(latitude=None, longitude=None):
    """Build all three synthetic candidates to exercise precedence."""
    return SyntheticRecordSource(
        location.RequestRecord(REQUEST_ID, BENEFICIARY_ID, latitude, longitude),
        location.BeneficiaryLocationRecord(BENEFICIARY_ID, 12, 34),
        location.ProfileAddressRecord(BENEFICIARY_ID, "Synthetic Example Road, Example City"),
    )


def resolve(records):
    """Resolve the fixed synthetic request/beneficiary identity."""
    return location.resolve_beneficiary_location(REQUEST_ID, BENEFICIARY_ID, records)


@pytest.mark.parametrize(
    "latitude,longitude",
    [
        (0, 0),
        (0, 90),
        (90, 0),
        (-90, -180),
        (90, 180),
        ("0", "0"),
        (" 12.5 ", "-34.5"),
    ],
)
def test_valid_request_coordinates_win(latitude, longitude):
    records = synthetic_source(latitude, longitude)
    result = resolve(records)
    assert result.status == "resolved"
    assert result.source == "request"
    assert result.coordinates == (float(latitude), float(longitude))
    assert result.address is None
    assert records.calls == [("request", REQUEST_ID)]


@pytest.mark.parametrize(
    "latitude,longitude",
    [
        (None, 10),
        (10, None),
        ("", 10),
        ("bad", 10),
        (True, 10),
        (10, False),
        (91, 10),
        (-91, 10),
        (10, 181),
        (10, -181),
        (float("nan"), 10),
        (10, float("inf")),
        ("-inf", 10),
        ("NaN", 10),
        ([], 10),
        (10, {}),
        (complex(1, 2), 10),
        (10**400, 10),
    ],
)
def test_malformed_request_pair_falls_back_without_mixing(latitude, longitude):
    result = resolve(synthetic_source(latitude, longitude))
    assert result.source == "beneficiary_current"
    assert result.coordinates == (12, 34)


def test_current_zero_coordinates_win_over_profile():
    records = synthetic_source()
    records.current = location.BeneficiaryLocationRecord(BENEFICIARY_ID, 0, 0)
    result = resolve(records)
    assert result.source == "beneficiary_current"
    assert result.coordinates == (0, 0)
    assert records.calls == [("request", REQUEST_ID), ("current", BENEFICIARY_ID)]


@pytest.mark.parametrize(
    "current",
    [
        None,
        location.BeneficiaryLocationRecord(BENEFICIARY_ID, 91, 0),
        location.BeneficiaryLocationRecord(BENEFICIARY_ID, 0, None),
    ],
)
def test_profile_only_address_requires_geocoding(current):
    records = synthetic_source()
    records.current = current
    records.profile = location.ProfileAddressRecord(BENEFICIARY_ID, "  Synthetic Example City  ")
    result = resolve(records)
    assert result.status == "requires_geocoding"
    assert result.source == "profile_address"
    assert result.address == "Synthetic Example City"
    assert result.coordinates is None


def test_missing_request_stops_before_fallback():
    records = synthetic_source()
    records.request = None
    assert resolve(records).reason == "missing_request"
    assert records.calls == [("request", REQUEST_ID)]


@pytest.mark.parametrize("address", [None, "", "  ", 123, {}])
def test_missing_or_invalid_profile_and_current_excludes_viewer(address):
    records = synthetic_source()
    records.current = None
    records.profile = location.ProfileAddressRecord(BENEFICIARY_ID, address)
    result = resolve(records)
    assert result.status == "unresolved"
    assert result.reason == "no_usable_beneficiary_location"
    assert result.coordinates is None
    assert result.address is None


def test_all_location_records_missing_excludes_viewer():
    records = synthetic_source()
    records.current = records.profile = None
    assert resolve(records).status == "unresolved"


@pytest.mark.parametrize(
    "request_id,beneficiary_id",
    [
        ("synthetic-other-request", BENEFICIARY_ID),
        (REQUEST_ID, "synthetic-other-beneficiary"),
    ],
)
def test_request_identity_mismatch_blocks_even_valid_coordinates(request_id, beneficiary_id):
    records = synthetic_source()
    records.request = location.RequestRecord(request_id, beneficiary_id, 0, 0)
    assert resolve(records).reason == "request_beneficiary_mismatch"
    assert records.calls == [("request", REQUEST_ID)]


def test_current_identity_mismatch_blocks_profile_fallback():
    records = synthetic_source()
    records.current = location.BeneficiaryLocationRecord("synthetic-other-beneficiary", 0, 0)
    assert resolve(records).reason == "beneficiary_location_mismatch"
    assert records.calls[-1] == ("current", BENEFICIARY_ID)


def test_profile_identity_mismatch():
    records = synthetic_source()
    records.current = None
    records.profile = location.ProfileAddressRecord("synthetic-other-beneficiary", "Synthetic City")
    assert resolve(records).reason == "profile_beneficiary_mismatch"


@pytest.mark.parametrize("request_id,beneficiary_id", [("", BENEFICIARY_ID), (REQUEST_ID, "")])
def test_missing_identity_does_not_retrieve_records(request_id, beneficiary_id):
    records = synthetic_source()
    result = location.resolve_beneficiary_location(request_id, beneficiary_id, records)
    assert result.reason == "missing_identity"
    assert records.calls == []


def test_retrieval_failure_is_not_reported_as_missing_data(monkeypatch):
    records = synthetic_source()

    def fail(_):
        """Simulate a local adapter failure without making a connection."""
        raise RuntimeError("Synthetic retrieval failure")

    monkeypatch.setattr(records, "get_request", fail)
    with pytest.raises(RuntimeError, match="Synthetic retrieval failure"):
        resolve(records)
