"""Offline tests for issue #422; no AWS/model calls or workflow writes."""

import itertools
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock
import zipfile

import pytest

from src.inappropriate_content_filter import lambda_function as api
from src.inappropriate_content_filter.create_profane_words_db import (
    create_profane_words_db,
)


def classification(**flags):
    """Produce a complete model response with independently controlled flags."""
    result = {flag: False for flag in api.FLAGS}
    result.update({field: [] for field in api.LIST_FIELDS})
    result.update(flags)
    return result


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Use a real local dictionary and prevent external classification calls."""
    source = tmp_path / "words.txt"
    source.write_text("damn\nass\n", encoding="utf-8")
    database = tmp_path / "words.db"
    create_profane_words_db(source, database)
    monkeypatch.setenv("PROFANITY_DB_PATH", str(database))
    mock = MagicMock(return_value=json.dumps(classification()))
    monkeypatch.setattr(api, "model_classification", mock)
    return mock


@pytest.mark.parametrize("values", itertools.product([False, True], repeat=4))
def test_all_flag_combinations(offline, values):
    """All 16 combinations preserve flags and select the documented priority."""
    model = classification(**dict(zip(api.FLAGS, values)))
    offline.return_value = json.dumps(model)
    reply = api.lambda_handler({"subject": "Please help"}, None)
    assert reply["statusCode"] == 200
    result = json.loads(reply["body"])
    expected = 3 if values[3] else 2 if any(values[1:3]) else int(values[0])
    assert result["severity_score"] == expected
    assert [s["score"] for s in result["severity_scores"]] == [0, 1, 2, 3]
    assert [s["flagged"] for s in result["severity_scores"]] == [
        expected == 0, values[0], any(values[1:3]), values[3],
    ]
    assert ("0. This is a normal request" in result) == (expected == 0)
    assert all(result[flag] == model[flag] for flag in api.FLAGS)


@pytest.mark.parametrize("event", [
    None, [], {}, {"body": "{"}, {"body": "[]"}, {"body": None},
    {"subject": 1}, {"description": None}, {"subject": "  "},
    {"subject": "a" * 20001}, {"isBase64Encoded": True, "body": "abc"},
])
def test_bad_input_does_not_call_services(offline, event):
    """Invalid/empty requests return 400 before model invocation."""
    assert api.lambda_handler(event, None)["statusCode"] == 400
    offline.assert_not_called()


@pytest.mark.parametrize("wrapper", ["direct", "dict", "json"])
def test_event_shapes_and_original_unicode(offline, wrapper):
    """Preserve multilingual text and punctuation for contextual evaluation."""
    body = {"subject": "Ayuda", "description": "¡Necesito ayuda!"}
    event = body if wrapper == "direct" else {
        "body": body if wrapper == "dict" else json.dumps(body)
    }
    assert api.lambda_handler(event, None)["statusCode"] == 200
    offline.assert_called_once_with("Ayuda", "¡Necesito ayuda!")


def test_dictionary_combines_with_model(offline):
    """Dictionary matches cannot be erased by a negative model flag."""
    reply = api.lambda_handler({"description": "Damn!"}, None)
    result = json.loads(reply["body"])
    assert result["severity_score"] == 1
    assert result["1. profanity"] == ["damn"]
    assert result["contains_profanity"] is True


@pytest.mark.parametrize("raw", [
    "{}", "null", "[]", "not json", None,
    json.dumps(classification(contains_profanity="false")),
    json.dumps(classification(contains_threatening_content=1)),
    json.dumps({**classification(), "1. profanity": "bad"}),
    json.dumps({**classification(), "1. profanity": [3]}),
    json.dumps({**classification(), "1. profanity": ["damn"]}),
    json.dumps({**classification(), "status_code": 500}),
    json.dumps({**classification(), "Error": "model failed"}),
])
def test_invalid_model_never_returns_normal(offline, raw):
    """Missing flags, nonbooleans, malformed lists and JSON fail closed."""
    offline.return_value = raw
    reply = api.lambda_handler({"subject": "Help"}, None)
    assert reply["statusCode"] == 503
    assert set(json.loads(reply["body"])) == {"error"}


def test_model_failure_does_not_leak_error(offline):
    """A failed model cannot be replaced with a misleading dictionary score."""
    offline.side_effect = api.ClassificationUnavailable("secret-key-and-content")
    reply = api.lambda_handler({"subject": "damn"}, None)
    assert reply["statusCode"] == 503
    assert "secret-key" not in reply["body"]
    assert "severity_score" not in reply["body"]


def test_missing_dictionary_is_not_created(offline, monkeypatch, tmp_path):
    """Read-only SQLite access cannot silently create an empty dictionary."""
    path = tmp_path / "missing.db"
    monkeypatch.setenv("PROFANITY_DB_PATH", str(path))
    assert api.lambda_handler({"subject": "help"}, None)["statusCode"] == 503
    assert not path.exists()
    offline.assert_not_called()


def test_corrupt_dictionary(offline, monkeypatch, tmp_path):
    """Unreadable SQLite data produces an unavailable response."""
    path = tmp_path / "corrupt.db"
    path.write_text("not sqlite")
    monkeypatch.setenv("PROFANITY_DB_PATH", str(path))
    assert api.lambda_handler({"subject": "help"}, None)["statusCode"] == 503


def test_fenced_json(offline):
    """Accept the fenced JSON format used by the previous implementation."""
    offline.return_value = "```json\n" + json.dumps(classification()) + "\n```"
    assert api.lambda_handler({"subject": "help"}, None)["statusCode"] == 200


def test_parameter_value_and_provider_contract(monkeypatch):
    """Extract SSM's Value and configure bounded provider calls without network."""
    ssm = MagicMock()
    ssm.get_parameter.return_value = {"Parameter": {"Value": "test-only-key"}}
    boto = MagicMock()
    boto.client.return_value = ssm
    groq = MagicMock()
    groq.return_value.__enter__.return_value.chat.completions.create.return_value = (
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(classification())
        ))])
    )
    monkeypatch.setitem(sys.modules, "boto3", boto)
    monkeypatch.setitem(sys.modules, "botocore.config", SimpleNamespace(Config=MagicMock()))
    monkeypatch.setitem(sys.modules, "groq", SimpleNamespace(Groq=groq))
    assert api.validate_classification(api.model_classification("Help", "Please"))
    groq.assert_called_once_with(api_key="test-only-key", timeout=15.0, max_retries=0)
    assert ssm.get_parameter.call_args.kwargs["WithDecryption"] is True
    ssm.get_parameter.side_effect = RuntimeError("sensitive detail")
    with pytest.raises(api.ClassificationUnavailable, match="service unavailable"):
        api.model_classification("Help", "Please")


def test_packaged_lambda_includes_working_dictionary(tmp_path, monkeypatch):
    """Build and unpack a clean artifact, then classify using its real dictionary."""
    source = Path(api.__file__).parent
    package = tmp_path / "package"
    package.mkdir()
    for name in ("lambda_function.py", "create_profane_words_db.py", "bad-words.txt"):
        shutil.copy2(source / name, package / name)

    # Same command as the manual deployment workflow, with no prebuilt database.
    subprocess.run(
        [sys.executable, "-B", "package/create_profane_words_db.py"],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    archive = shutil.make_archive(str(tmp_path / "deployment"), "zip", package)
    deployed = tmp_path / "deployed"
    with zipfile.ZipFile(archive) as bundle:
        assert "profane_words.db" in bundle.namelist()
        bundle.extractall(deployed)

    expected_words = {
        word.strip().lower()
        for word in (source / "bad-words.txt").read_text(encoding="utf-8").splitlines()
        if word.strip()
    }
    database = sqlite3.connect(
        (deployed / "profane_words.db").as_uri() + "?mode=ro", uri=True,
    )
    try:
        assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert {row[0] for row in database.execute("SELECT words FROM profane_words")} == expected_words
    finally:
        database.close()

    spec = importlib.util.spec_from_file_location(
        "packaged_profanity_lambda", deployed / "lambda_function.py",
    )
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    monkeypatch.delenv("PROFANITY_DB_PATH", raising=False)
    monkeypatch.chdir(tmp_path)  # Dictionary resolution must not depend on cwd.
    monkeypatch.setattr(
        handler, "model_classification", lambda *_: json.dumps(classification()),
    )
    reply = handler.lambda_handler({"description": "damn"}, None)
    assert reply["statusCode"] == 200
    result = json.loads(reply["body"])
    assert result["severity_score"] == 1
    assert "damn" in result["1. profanity"]
