"""Read explicit configuration without opening connections at import time."""

import os
from pathlib import Path

from sqlalchemy.engine import make_url

from .client import ProfanityClient
from .service import RoutingService
from .storage import RoutingStore


TASK_FOLDER = Path(__file__).resolve().parents[1]


def build_store() -> RoutingStore:
    """Default to a task-local database and require explicit PostgreSQL settings."""
    database_url = os.getenv(
        "TASK422_DATABASE_URL", f"sqlite:///{(TASK_FOLDER / 'task422.sqlite3').as_posix()}"
    )
    backend = make_url(database_url).get_backend_name()
    schema = os.getenv("TASK422_DB_SCHEMA") or None
    status_id = os.getenv("TASK422_ACTIVE_STATUS_ID")
    if backend == "postgresql" and (not schema or not status_id):
        raise ValueError("PostgreSQL requires TASK422_DB_SCHEMA and TASK422_ACTIVE_STATUS_ID.")
    return RoutingStore(database_url, schema, int(status_id or 1))


def build_service() -> RoutingService:
    """Construct the real adapter; a mock endpoint must be chosen explicitly."""
    client = ProfanityClient(
        os.getenv("PROFANITY_API_URL", ""),
        api_key=os.getenv("PROFANITY_API_KEY", ""),
        timeout=float(os.getenv("PROFANITY_API_TIMEOUT", "10")),
        allow_local_http=os.getenv("PROFANITY_ALLOW_LOCAL_HTTP", "false").lower() == "true",
    )
    return RoutingService(client, build_store())
