
import importlib.util
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "saayam-org-aggregator"
    / "location_utils.py"
)

spec = importlib.util.spec_from_file_location(
    "location_utils", MODULE_PATH
)
location_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(location_utils)


def test_valid_request_coordinates():
    result = location_utils.parse_coordinates(
        "longitude:-121.9780,latitude:37.7799"
    )
    assert result == (37.7799, -121.9780)


def test_missing_coordinates():
    assert location_utils.parse_coordinates(None) is None


def test_invalid_coordinates():
    assert location_utils.parse_coordinates(
        "longitude:-200,latitude:95"
    ) is None


def test_self_request_coordinates():
    result = location_utils.resolve_request_location(
        "longitude:-121.9780,latitude:37.7799",
        0,
    )
    assert result == (37.7799, -121.9780)


def test_other_request_coordinates():
    result = location_utils.resolve_request_location(
        "longitude:-121.9780,latitude:37.7799",
        1,
    )
    assert result == (37.7799, -121.9780)
def test_get_user_location_returns_coordinates():
    from unittest.mock import Mock

    cursor = Mock()
    cursor.fetchone.return_value = (37.7799, -121.9780)

    result = location_utils.get_user_location(
        cursor,
        "virginia_dev_saayam_rdbms",
        "test-user-123"
    )

    assert result == (37.7799, -121.9780)

    cursor.execute.assert_called_once()
    query, parameters = cursor.execute.call_args.args

    assert "ST_Y(curr_loc::geometry)" in query
    assert "ST_X(curr_loc::geometry)" in query
    assert parameters == ("test-user-123",)

def test_get_user_location_missing_returns_none():
    from unittest.mock import Mock

    cursor = Mock()
    cursor.fetchone.return_value = None

    result = location_utils.get_user_location(
        cursor,
        "virginia_dev_saayam_rdbms",
        "test-user-123"
    )

    assert result is None
    cursor.execute.assert_called_once()

def test_self_request_coordinates():
    result = location_utils.resolve_request_location(
        "longitude:-121.9780,latitude:37.7799"
    )
    assert result == (37.7799, -121.9780)


def test_other_request_coordinates():
    result = location_utils.resolve_request_location(
        "longitude:-121.9780,latitude:37.7799"
    )
    assert result == (37.7799, -121.9780)


def test_beneficiary_location_fallback():
    result = location_utils.resolve_request_location(
        None,
        beneficiary_location=(37.7799, -121.9780),
    )
    assert result == (37.7799, -121.9780)


def test_missing_beneficiary_location():
    result = location_utils.resolve_request_location(
        None,
        beneficiary_location=None,
    )
    assert result is None


def test_explicit_request_location_takes_priority():
    result = location_utils.resolve_request_location(
        "longitude:-73.9857,latitude:40.7484",
        beneficiary_location=(37.7799, -121.9780),
    )
    assert result == (40.7484, -73.9857)

def test_build_beneficiary_address_complete():
    profile = {
        "addr_ln1": "123 Main Street",
        "addr_ln2": "Apt 4",
        "city_name": "Jersey City",
        "state_name": "New Jersey",
        "zip_code": "07306",
        "country_name": "United States",
    }

    result = location_utils.build_beneficiary_address(profile)

    assert result == (
        "123 Main Street, Apt 4, Jersey City, "
        "New Jersey, 07306, United States"
    )


def test_build_beneficiary_address_partial():
    profile = {
        "city_name": "New York",
        "state_name": "New York",
        "country_name": "United States",
    }

    result = location_utils.build_beneficiary_address(profile)

    assert result == "New York, New York, United States"


def test_build_beneficiary_address_missing():
    assert location_utils.build_beneficiary_address({}) is None
    assert location_utils.build_beneficiary_address(None) is None


def test_get_beneficiary_profile_address_complete():
    cursor = Mock()
    cursor.fetchone.return_value = (
        "123 Main Street",
        "Apt 4",
        None,
        "Jersey City",
        "New Jersey",
        "07306",
        "United States",
    )

    result = location_utils.get_beneficiary_profile_address(
        cursor, "virginia_dev_saayam_rdbms", "user123"
    )

    assert result == (
        "123 Main Street, Apt 4, Jersey City, "
        "New Jersey, 07306, United States"
    )
    cursor.execute.assert_called_once()
    assert cursor.execute.call_args.args[1] == ("user123",)


def test_get_beneficiary_profile_address_missing_user():
    cursor = Mock()
    cursor.fetchone.return_value = None

    result = location_utils.get_beneficiary_profile_address(
        cursor, "virginia_dev_saayam_rdbms", "unknown_user"
    )

    assert result is None


def test_get_beneficiary_profile_address_missing_id():
    cursor = Mock()

    result = location_utils.get_beneficiary_profile_address(
        cursor, "virginia_dev_saayam_rdbms", None
    )

    assert result is None
    cursor.execute.assert_not_called()

def test_get_request_details_self():
    cursor = Mock()
    cursor.fetchone.return_value = (
        "REQ001",
        "USER123",
        0,
        "longitude:-121.9780,latitude:37.7799",
    )

    result = location_utils.get_request_details(
        cursor, "virginia_dev_saayam_rdbms", "REQ001"
    )

    assert result == {
        "req_id": "REQ001",
        "req_user_id": "USER123",
        "req_for_id": 0,
        "req_loc": "longitude:-121.9780,latitude:37.7799",
    }

    cursor.execute.assert_called_once()
    assert cursor.execute.call_args.args[1] == ("REQ001",)


def test_get_request_details_not_found():
    cursor = Mock()
    cursor.fetchone.return_value = None

    result = location_utils.get_request_details(
        cursor, "virginia_dev_saayam_rdbms", "UNKNOWN"
    )

    assert result is None


def test_get_request_details_missing_id():
    cursor = Mock()

    result = location_utils.get_request_details(
        cursor, "virginia_dev_saayam_rdbms", None
    )

    assert result is None
    cursor.execute.assert_not_called()


def test_resolve_beneficiary_request_coordinates():
    cursor = Mock()
    request = {
        "req_for_id": 1,
        "req_user_id": "REQUESTER123",
        "req_loc": "longitude:-121.9780,latitude:37.7799",
    }

    result = location_utils.resolve_beneficiary_location(
        cursor, "virginia_dev_saayam_rdbms", request
    )

    assert result == {
        "coordinates": (37.7799, -121.9780),
        "address": None,
    }
    cursor.execute.assert_not_called()


@patch.object(location_utils, "get_user_location")
def test_resolve_beneficiary_self_fallback(mock_get_location):
    mock_get_location.return_value = (40.7484, -73.9857)
    cursor = Mock()

    request = {
        "req_for_id": 0,
        "req_user_id": "USER123",
        "req_loc": None,
    }

    result = location_utils.resolve_beneficiary_location(
        cursor, "virginia_dev_saayam_rdbms", request
    )

    assert result["coordinates"] == (40.7484, -73.9857)
    mock_get_location.assert_called_once_with(
        cursor, "virginia_dev_saayam_rdbms", "USER123"
    )


@patch.object(location_utils, "get_user_location")
def test_resolve_beneficiary_other_explicit_id(mock_get_location):
    mock_get_location.return_value = (37.7799, -121.9780)
    cursor = Mock()

    request = {
        "req_for_id": 1,
        "req_user_id": "REQUESTER123",
        "req_loc": None,
    }

    result = location_utils.resolve_beneficiary_location(
        cursor,
        "virginia_dev_saayam_rdbms",
        request,
        beneficiary_id="BENEFICIARY456",
    )

    assert result["coordinates"] == (37.7799, -121.9780)
    mock_get_location.assert_called_once_with(
        cursor, "virginia_dev_saayam_rdbms", "BENEFICIARY456"
    )


def test_resolve_beneficiary_other_without_id():
    cursor = Mock()

    request = {
        "req_for_id": 1,
        "req_user_id": "REQUESTER123",
        "req_loc": None,
    }

    result = location_utils.resolve_beneficiary_location(
        cursor, "virginia_dev_saayam_rdbms", request
    )

    assert result == {"coordinates": None, "address": None}
    cursor.execute.assert_not_called()


@patch.object(location_utils, "get_beneficiary_profile_address")
@patch.object(location_utils, "get_user_location")
def test_resolve_beneficiary_profile_fallback(
    mock_get_location, mock_get_address
):
    mock_get_location.return_value = None
    mock_get_address.return_value = (
        "123 Main Street, Jersey City, New Jersey, 07306"
    )

    request = {
        "req_for_id": 0,
        "req_user_id": "USER123",
        "req_loc": None,
    }

    result = location_utils.resolve_beneficiary_location(
        Mock(), "virginia_dev_saayam_rdbms", request
    )

    assert result["coordinates"] is None
    assert result["address"] == (
        "123 Main Street, Jersey City, New Jersey, 07306"
    )