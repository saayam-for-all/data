"""Tests for Help Request profanity severity scoring."""

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "profanity_severity"
    / "lambda_function.py"
)

spec = importlib.util.spec_from_file_location(
    "profanity_severity_lambda",
    MODULE_PATH,
)

severity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(severity)


def classification(
    profanity=False,
    depressive=False,
    suicidal=False,
    threatening=False,
):
    return {
        "contains_profanity": profanity,
        "contains_depressive_content": depressive,
        "contains_suicidal_content": suicidal,
        "contains_threatening_content": threatening,
    }


def test_normal_returns_zero():
    assert severity.get_severity_score(
        classification()
    ) == 0


def test_profanity_returns_one():
    assert severity.get_severity_score(
        classification(
            profanity=True
        )
    ) == 1


def test_depressive_returns_two():
    assert severity.get_severity_score(
        classification(
            depressive=True
        )
    ) == 2


def test_suicidal_returns_two():
    assert severity.get_severity_score(
        classification(
            suicidal=True
        )
    ) == 2


def test_threatening_returns_three():
    assert severity.get_severity_score(
        classification(
            threatening=True
        )
    ) == 3


def test_highest_severity_wins():
    assert severity.get_severity_score(
        classification(
            profanity=True,
            depressive=True,
            threatening=True,
        )
    ) == 3


def test_score_two_beats_profanity():
    assert severity.get_severity_score(
        classification(
            profanity=True,
            suicidal=True,
        )
    ) == 2


@pytest.mark.parametrize(
    "missing_flag",
    [
        "contains_profanity",
        "contains_depressive_content",
        "contains_suicidal_content",
        "contains_threatening_content",
    ],
)
def test_missing_flag_is_rejected(
    missing_flag,
):
    data = classification()
    del data[missing_flag]

    with pytest.raises(
        ValueError,
        match="Missing classification field",
    ):
        severity.get_severity_score(
            data
        )


@pytest.mark.parametrize(
    "invalid_value",
    [
        1,
        0,
        "true",
        "false",
        None,
        [],
        {},
    ],
)
def test_flags_must_be_boolean(
    invalid_value,
):
    data = classification()

    data["contains_profanity"] = (
        invalid_value
    )

    with pytest.raises(
        ValueError,
        match="must be boolean",
    ):
        severity.get_severity_score(
            data
        )


def test_lambda_returns_zero():
    response = severity.lambda_handler(
        classification(),
        None,
    )

    assert response["statusCode"] == 200

    body = json.loads(
        response["body"]
    )

    assert body["severity_score"] == 0


def test_lambda_returns_three():
    response = severity.lambda_handler(
        classification(
            threatening=True
        ),
        None,
    )

    assert response["statusCode"] == 200

    body = json.loads(
        response["body"]
    )

    assert body["severity_score"] == 3


def test_lambda_accepts_json_string_body():
    response = severity.lambda_handler(
        {
            "body": json.dumps(
                classification(
                    profanity=True
                )
            )
        },
        None,
    )

    assert response["statusCode"] == 200

    body = json.loads(
        response["body"]
    )

    assert body["severity_score"] == 1


def test_lambda_accepts_dict_body():
    response = severity.lambda_handler(
        {
            "body": classification(
                suicidal=True
            )
        },
        None,
    )

    assert response["statusCode"] == 200

    body = json.loads(
        response["body"]
    )

    assert body["severity_score"] == 2


def test_invalid_json_returns_400():
    response = severity.lambda_handler(
        {
            "body": "{invalid-json"
        },
        None,
    )

    assert response["statusCode"] == 400

    body = json.loads(
        response["body"]
    )

    assert body["severity_score"] is None


def test_json_array_returns_400():
    response = severity.lambda_handler(
        {
            "body": "[1, 2, 3]"
        },
        None,
    )

    assert response["statusCode"] == 400


def test_missing_field_returns_400():
    data = classification()

    del data[
        "contains_threatening_content"
    ]

    response = severity.lambda_handler(
        data,
        None,
    )

    assert response["statusCode"] == 400


def test_non_boolean_returns_400():
    data = classification()

    data["contains_profanity"] = "yes"

    response = severity.lambda_handler(
        data,
        None,
    )

    assert response["statusCode"] == 400