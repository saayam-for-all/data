import ast
import json
import math
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pandas as pd


LAMBDA_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "saayam-org-aggregator"
    / "lambda_function.py"
)


def test_multiple_organizations():
    source = LAMBDA_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    handler = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "lambda_handler"
    )

    # Load only the handler, avoiding AWS-dependent imports.
    namespace = {
        "json": json,
        "math": math,
        "ThreadPoolExecutor": ThreadPoolExecutor,
        "get_orgs_from_db": lambda location, category: None,
        "get_ai_orgs": lambda subject, description, location: None,
        "merge_organizations": lambda db, ai: pd.DataFrame([
            {"name": "Organization A", "street": "123 Main St"},
            {"name": "Organization B", "street": "456 Oak St"},
        ]),
        "build_distance_result": lambda beneficiary, organization: {
            "distance": None,
            "distance_unit": "miles",
            "distance_method": "straight_line",
            "distance_status": "unknown_location",
        },
    }

    module = ast.Module(body=[handler], type_ignores=[])
    exec(compile(module, str(LAMBDA_PATH), "exec"), namespace)

    response = namespace["lambda_handler"](
        {"location": "Jersey City", "category": "Shelter"},
        None,
    )

    assert response["statusCode"] == 200, response

    organizations = json.loads(response["body"])

    assert len(organizations) == 2

    for organization in organizations:
        assert organization["distance"] is None
        assert organization["distance_unit"] == "miles"
        assert organization["distance_status"] == "unknown_location"
        assert "street" in organization

    print("MULTIPLE ORGANIZATIONS TEST PASSED")

def test_beneficiary_lookup():
    source = LAMBDA_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    handler = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "lambda_handler"
    )

    calls = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            calls.append("cursor_closed")


    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    def fake_get_request_details(cursor, schema, request_id):
        calls.append("request_lookup")
        assert request_id == 123
        return {"req_id": 123, "req_for_id": 0, "req_user_id": 7}

    def fake_resolve_location(cursor, schema, request, beneficiary_id=None):
        calls.append("location_resolved")
        return {"coordinates": (37.7799, -121.9780), "address": None}

    namespace = {
        "json": json,
        "math": math,
        "ThreadPoolExecutor": ThreadPoolExecutor,
        "get_db_schema": lambda: "test_schema",
        "get_db_cursor": FakeCursor,
        "get_request_details": fake_get_request_details,
        "resolve_beneficiary_location": fake_resolve_location,
        "get_orgs_from_db": lambda location, category: None,
        "get_ai_orgs": lambda subject, description, location: None,
        "_db_conn": FakeConnection(),
"_db_name": "test_schema",
"aggregate_request_organizations_with_distances": (
    lambda **kwargs: (
        calls.append("distance_adapter_called")
        or pd.DataFrame([{
            "name": "Organization A",
            "distance": 25.4,
            "distance_unit": "miles",
            "distance_method": "straight_line",
            "distance_status": "ok",
        }])
    )
),
        "merge_organizations": lambda db, ai: pd.DataFrame([
            {"name": "Organization A", "street": "123 Main St"}
        ]),
        "build_distance_result": lambda beneficiary, organization: {
            "distance": None,
            "distance_unit": "miles",
            "distance_method": "straight_line",
            "distance_status": "unknown_location",
        },
    }

    module = ast.Module(body=[handler], type_ignores=[])
    exec(compile(module, str(LAMBDA_PATH), "exec"), namespace)

    response = namespace["lambda_handler"](
        {
            "location": "Jersey City",
            "category": "Shelter",
            "request_id": 123,
        },
        None,
    )

    assert response["statusCode"] == 200, response
    assert calls == [
    "distance_adapter_called",
    "cursor_closed",
]

    print("\n=== LOCAL MOCKED LAMBDA RESPONSE ===")
    print("HTTP Status:", response["statusCode"])
    print(json.dumps(json.loads(response["body"]), indent=2))
    print("=== END RESPONSE ===")

def test_beneficiary_lookup_failure():
    source = LAMBDA_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    handler = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "lambda_handler"
    )

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    def failing_lookup(cursor, schema, request_id):
        raise RuntimeError("Database lookup failed")

    namespace = {
        "json": json,
        "math": math,
        "ThreadPoolExecutor": ThreadPoolExecutor,
        "get_db_schema": lambda: "test_schema",
        "get_db_cursor": FakeCursor,
        "get_request_details": failing_lookup,
        "resolve_beneficiary_location": lambda *args, **kwargs: None,
        "get_orgs_from_db": lambda location, category: None,
        "get_ai_orgs": lambda subject, description, location: None,
                "_db_conn": FakeConnection(),
        "_db_name": "test_schema",
        "aggregate_request_organizations_with_distances": (
            lambda **kwargs: failing_lookup(
                kwargs["cursor"],
                kwargs["schema"],
                kwargs["request_id"],
            )
        ),
        "merge_organizations": lambda db, ai: pd.DataFrame([
            {"name": "Organization A"}
        ]),
        "build_distance_result": lambda beneficiary, organization: {
            "distance": None,
            "distance_unit": "miles",
            "distance_method": "straight_line",
            "distance_status": "unknown_location",
        },
    }

    module = ast.Module(body=[handler], type_ignores=[])
    exec(compile(module, str(LAMBDA_PATH), "exec"), namespace)

    response = namespace["lambda_handler"](
        {
            "location": "Jersey City",
            "category": "Shelter",
            "request_id": 123,
        },
        None,
    )

    assert response["statusCode"] == 200, response
    print("\n=== LOCAL MOCKED LAMBDA RESPONSE ===")
    print("HTTP Status:", response["statusCode"])
    print(json.dumps(json.loads(response["body"]), indent=2))
    print("=== END RESPONSE ===")

    organizations = json.loads(response["body"])
    assert len(organizations) == 1
    assert organizations[0]["distance"] is None