"""Local commands: demo, serve, mock-api, and init-db."""

import argparse
import json

import requests
from sqlalchemy import func, select

from .client import ProfanityClient
from .config import TASK_FOLDER, build_service, build_store
from .local_tools import FIXTURE_SCORES, create_mock_api, local_server
from .service import RoutingService
from .storage import RoutingStore
from .web import create_app


def run_demo() -> None:
    """Exercise two real local HTTP services and an on-disk SQLite database."""
    database = TASK_FOLDER / "task422_demo.sqlite3"
    store = RoutingStore(f"sqlite:///{database.as_posix()}")
    store.initialize_local()
    results = []
    try:
        with local_server(create_mock_api()) as mock_url:
            service = RoutingService(
                ProfanityClient(f"{mock_url}/check-profanity", allow_local_http=True), store
            )
            with local_server(create_app(service)) as app_url:
                for index, subject in enumerate(
                    [*FIXTURE_SCORES, "API outage fixture", "Model failure fixture"]
                ):
                    payload = {
                        "request_id": f"demo-422-{index}",
                        "user_id": "demo-user",
                        "subject": subject,
                        "description": "Synthetic Help Request used only for local verification.",
                    }
                    response = requests.post(
                        f"{app_url}/api/help_requests", json=payload, timeout=5
                    )
                    body = response.json()
                    expected = 200 if subject in FIXTURE_SCORES else 503
                    if response.status_code != expected:
                        raise RuntimeError(
                            f"Demo failed for {subject}: HTTP {response.status_code}"
                        )
                    if expected == 200:
                        expected_score = max(FIXTURE_SCORES[subject], default=0)
                        if body["severity_score"] != expected_score:
                            raise RuntimeError(f"Unexpected severity for {subject}.")
                    results.append(
                        {"fixture": subject, "http_status": response.status_code, **body}
                    )
                retry = {
                    "request_id": "demo-422-0",
                    "user_id": "demo-user",
                    "subject": "Normal fixture",
                    "description": "Synthetic Help Request used only for local verification.",
                }
                response = requests.post(f"{app_url}/api/help_requests", json=retry, timeout=5)
                if response.status_code != 200 or not response.json()["replayed"]:
                    raise RuntimeError("Idempotent retry verification failed.")
        with store.engine.connect() as connection:
            counts = {
                table.name: connection.scalar(select(func.count()).select_from(table))
                for table in (store.requests, store.fraud_requests, store.screenings)
            }
        if counts != {"request": 1, "fraud_requests": 4, "profanity_screenings": 5}:
            raise RuntimeError(f"Unexpected demo database counts: {counts}")
        print(
            json.dumps(
                {
                    "results": results,
                    "retry_replayed": True,
                    "row_counts": counts,
                    "database": str(database),
                },
                indent=2,
            )
        )
    finally:
        store.engine.dispose()


def main() -> None:
    """Run only the local action explicitly selected on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("demo", "serve", "mock-api", "init-db"))
    parser.add_argument(
        "--port", type=int, help="Local listening port (serve: 5010; mock-api: 5011)"
    )
    args = parser.parse_args()
    if args.command == "demo":
        run_demo()
    elif args.command == "mock-api":
        create_mock_api().run(host="127.0.0.1", port=args.port or 5011, debug=False)
    elif args.command == "init-db":
        store = build_store()
        try:
            store.initialize_local()
            print("Local SQLite tables are ready.")
        finally:
            store.engine.dispose()
    else:
        create_app(build_service()).run(host="127.0.0.1", port=args.port or 5010, debug=False)


if __name__ == "__main__":
    main()
