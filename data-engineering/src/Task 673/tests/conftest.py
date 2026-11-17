"""Fixtures shared by offline and real-PostgreSQL checks."""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import load_app  # noqa: E402


@pytest.fixture
def app():
    """No network access: only these unit tests replace the DB connection."""
    with load_app(Mock(name="unit_test_connection")) as loaded:
        yield loaded
