"""Isolated SQLite databases and real loopback API fixtures."""

import pytest

from profanity_routing.client import ProfanityClient
from profanity_routing.local_tools import create_mock_api, local_server
from profanity_routing.service import RoutingService
from profanity_routing.storage import RoutingStore
from profanity_routing.web import create_app


@pytest.fixture
def submission():
    """Return a valid Help Request with a stable idempotency key."""
    return {
        "request_id": "request-422",
        "user_id": "user-422",
        "subject": "Normal fixture",
        "description": "Please help me find groceries.",
    }


@pytest.fixture
def store(tmp_path):
    """Use an actual database, with no mock transaction or query implementation."""
    value = RoutingStore(f"sqlite:///{(tmp_path / 'routing.sqlite3').as_posix()}")
    value.initialize_local()
    yield value
    value.engine.dispose()


@pytest.fixture(scope="session")
def mock_url():
    """Exercise HTTP serialization and the real requests transport."""
    with local_server(create_mock_api()) as url:
        yield f"{url}/check-profanity"


@pytest.fixture
def service(store, mock_url):
    """Connect the production client and store to the explicit local API."""
    return RoutingService(ProfanityClient(mock_url, allow_local_http=True), store)


@pytest.fixture
def app(service):
    """Expose the same routes used by the local CLI server."""
    value = create_app(service)
    value.config["TESTING"] = True
    return value
