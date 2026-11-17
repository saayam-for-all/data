"""Load the real aggregator locally while replacing its AWS boundary."""

import importlib.util
import io
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

TASK_DIR = Path(__file__).resolve().parent
REPO_ROOT = TASK_DIR.parents[2]
AGGREGATOR_DIR = TASK_DIR.parent / "saayam-org-aggregator"
# Verified against remote test on 2026-11-16. Never fetches or writes to GitHub.
BASELINE_REF = "c3b66eadc20b765c09dedb40d35d3566efdd652f"


def ai_response(organizations=None, status=200):
    """Build a deterministic GenAI Lambda response without an AWS invocation."""
    if organizations is None:
        organizations = [{
            "organization_name": "Generated Food Network",
            "org_type": "Nonprofit",
            "location": "Evanston, IL",
            "address": "20 Example Avenue, Evanston, IL",
            "size": "Small",
            "rating": 4.2,
            "contact": "555-0104",
            "email": "generated@example.invalid",
            "web_url": "https://generated.example.invalid",
            "mission": "Food assistance",
            # Untrusted AI flags must never imply verified contributor status.
            "is_collaborator": True,
            "is_contributor": True,
            "contributor": True,
        }]
    body = {"organizations": organizations}
    if status == 502:
        body = {"code": "ORG_SEARCH_UNAVAILABLE"}
    return {"statusCode": status, "body": json.dumps(body)}


def _load_module(name, filename, baseline_ref):
    """Import local source or read the pinned baseline from local Git history."""
    path = AGGREGATOR_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    if baseline_ref:
        relative = path.relative_to(REPO_ROOT).as_posix()
        source = subprocess.check_output(
            ["git", "show", f"{baseline_ref}:{relative}"],
            cwd=REPO_ROOT, text=True, encoding="utf-8",
        )
        exec(compile(source, f"{baseline_ref}:{relative}", "exec"), module.__dict__)
    else:
        spec.loader.exec_module(module)
    return module


@contextmanager
def load_app(connection, schema="task673", payload=None, baseline_ref=None):
    """Run production Python/SQL with local DB and mocked SSM/GenAI only."""
    client = Mock(name="local_genai")

    def invoke(**kwargs):
        """Return a fresh readable stream on every warm invocation."""
        response = payload if payload is not None else ai_response()
        return {"Payload": io.BytesIO(json.dumps(response).encode())}

    client.invoke.side_effect = invoke
    credentials = json.dumps({
        "DATABASE NAME": schema, "HOST": "127.0.0.1", "USERNAME": "task673",
        "PASSWORD": "", "PORT": 5432,
    })
    # Restore import names afterwards so unrelated Lambda tests stay isolated.
    with patch.dict(sys.modules):
        distance = _load_module("distance", "distance.py", baseline_ref)
        with (
            patch("boto3.client", return_value=client),
            patch("aws_lambda_powertools.utilities.parameters.get_parameter",
                  return_value=credentials),
            patch("psycopg2.connect", return_value=connection),
        ):
            helpers = _load_module("helpers", "helpers.py", baseline_ref)
            handler = _load_module("task673_handler", "lambda_function.py", baseline_ref)
        with patch.dict("os.environ", {"GEOCODER_PROVIDER": "city_table"}):
            yield SimpleNamespace(
                helpers=helpers, handler=handler, distance=distance, client=client,
            )


def event(sort_by=None):
    """Representative API Gateway event for the fixture beneficiary/request."""
    body = {"request_id": "request-673", "beneficiary_id": "beneficiary-673"}
    if sort_by:
        body["sort_by"] = sort_by
    return {"body": json.dumps(body)}
