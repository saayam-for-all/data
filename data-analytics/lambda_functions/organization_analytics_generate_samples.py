"""Generate committed sample responses from the configured local database."""

import json
import os
from pathlib import Path

from organization_analytics import lambda_handler


SAMPLE_DIRECTORY = Path(__file__).resolve().parent / "organization_analytics_samples"
REQUESTS = {
    "sample_response_overview_ALL_monthly.json": {
        "dashboard_type": "overview",
        "time_filter": "ALL",
        "group_by": "monthly",
    },
    "sample_response_performance_ALL.json": {
        "dashboard_type": "performance",
        "time_filter": "ALL",
    },
}


def require_local_test_mode():
    """Prevent sample generation without an explicit local opt-in."""
    enabled = os.environ.get("ORG_ANALYTICS_LOCAL_TEST", "").lower()
    if enabled not in {"1", "true", "yes"}:
        raise RuntimeError(
            "Set ORG_ANALYTICS_LOCAL_TEST=true before generating samples."
        )


def main():
    """Call both dashboards and save their decoded response bodies."""
    require_local_test_mode()
    SAMPLE_DIRECTORY.mkdir(exist_ok=True)
    for file_name, request in REQUESTS.items():
        response = lambda_handler(request, None)
        if response["statusCode"] != 200:
            raise RuntimeError(
                f"{file_name} failed with HTTP {response['statusCode']}: "
                f"{response['body']}"
            )
        output_path = SAMPLE_DIRECTORY / file_name
        output_path.write_text(
            json.dumps(json.loads(response["body"]), indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()

