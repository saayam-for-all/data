import json
import sys
import types
from pathlib import Path


# Add data-engineering to Python's import path.
DATA_ENGINEERING_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DATA_ENGINEERING_DIR))


# Stub external dependencies so these unit tests do not require
# Groq or AWS credentials.
if "groq" not in sys.modules:
    groq_stub = types.ModuleType("groq")

    class Groq:
        pass

    groq_stub.Groq = Groq
    sys.modules["groq"] = groq_stub


if "boto3" not in sys.modules:
    boto3_stub = types.ModuleType("boto3")
    boto3_stub.client = lambda *args, **kwargs: None
    sys.modules["boto3"] = boto3_stub


from src.inappropriate_content_filter import inappropriate_content_filter

build_severity_scores = inappropriate_content_filter.build_severity_scores


def get_flagged_scores(response_data):
    return [
        item["score"]
        for item in build_severity_scores(response_data)
        if item["flagged"]
    ]


def test_normal_request_returns_score_zero():
    response_data = {
        "contains_profanity": False,
        "contains_depressive_content": False,
        "contains_suicidal_content": False,
        "contains_threatening_content": False,
    }

    assert get_flagged_scores(response_data) == [0]


def test_profanity_returns_score_one():
    response_data = {
        "contains_profanity": True,
        "contains_depressive_content": False,
        "contains_suicidal_content": False,
        "contains_threatening_content": False,
    }

    assert get_flagged_scores(response_data) == [1]


def test_depressive_content_returns_score_two():
    response_data = {
        "contains_profanity": False,
        "contains_depressive_content": True,
        "contains_suicidal_content": False,
        "contains_threatening_content": False,
    }

    assert get_flagged_scores(response_data) == [2]


def test_suicidal_content_returns_score_two():
    response_data = {
        "contains_profanity": False,
        "contains_depressive_content": False,
        "contains_suicidal_content": True,
        "contains_threatening_content": False,
    }

    assert get_flagged_scores(response_data) == [2]


def test_threatening_content_returns_score_three():
    response_data = {
        "contains_profanity": False,
        "contains_depressive_content": False,
        "contains_suicidal_content": False,
        "contains_threatening_content": True,
    }

    assert get_flagged_scores(response_data) == [3]


def test_multiple_categories_can_be_flagged():
    response_data = {
        "contains_profanity": True,
        "contains_depressive_content": False,
        "contains_suicidal_content": True,
        "contains_threatening_content": True,
    }

    assert get_flagged_scores(response_data) == [1, 2, 3]


def test_all_four_scores_are_always_returned():
    response_data = {
        "contains_profanity": True,
        "contains_depressive_content": False,
        "contains_suicidal_content": False,
        "contains_threatening_content": False,
    }

    scores = build_severity_scores(response_data)

    assert len(scores) == 4
    assert [item["score"] for item in scores] == [0, 1, 2, 3]
    assert [item["category"] for item in scores] == [
        "normal",
        "profanity",
        "depressive_suicidal",
        "threatening",
    ]

def test_lambda_handler_returns_normal_severity_score(monkeypatch, tmp_path):
    db_path = tmp_path / "profane_words.db"

    import sqlite3

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE profane_words (words TEXT UNIQUE)")
    cursor.execute("INSERT INTO profane_words (words) VALUES (?)", ("damn",))
    conn.commit()
    conn.close()

    monkeypatch.chdir(tmp_path)

    class FakeSSM:
        def get_parameter(self, **kwargs):
            return {"Parameter": {"Value": "fake-api-key"}}

    monkeypatch.setattr(
        inappropriate_content_filter.boto3,
        "client",
        lambda *args, **kwargs: FakeSSM(),
    )

    class FakeMessage:
        content = """{
            "contains_profanity": false,
            "1. profanity": [],
            "contains_depressive_content": false,
            "contains_suicidal_content": false,
            "2. Depressive/Suicidal Content": [],
            "contains_threatening_content": false,
            "3. Threatening Content": []
        }"""

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletions:
        def create(self, **kwargs):
            return type("Response", (), {"choices": [FakeChoice()]})()

    class FakeChat:
        completions = FakeCompletions()

    class FakeGroq:
        chat = FakeChat()

    monkeypatch.setattr(
        inappropriate_content_filter,
        "Groq",
        lambda *args, **kwargs: FakeGroq(),
    )

    event = {
        "body": json.dumps(
            {
                "subject": "Need groceries",
                "description": "I need help getting groceries."
            }
        )
    }

    result = inappropriate_content_filter.lambda_handler(event, None)

    assert result["statusCode"] == 200

    body = json.loads(result["body"])

    assert "severity_scores" in body

    flagged_scores = [
        item["score"]
        for item in body["severity_scores"]
        if item["flagged"]
    ]

    assert flagged_scores == [0]


def test_lambda_handler_combines_local_profanity_and_threat(monkeypatch, tmp_path):
    db_path = tmp_path / "profane_words.db"

    import sqlite3

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE profane_words (words TEXT UNIQUE)")
    cursor.execute("INSERT INTO profane_words (words) VALUES (?)", ("damn",))
    conn.commit()
    conn.close()

    monkeypatch.chdir(tmp_path)

    class FakeSSM:
        def get_parameter(self, **kwargs):
            return {"Parameter": {"Value": "fake-api-key"}}

    monkeypatch.setattr(
        inappropriate_content_filter.boto3,
        "client",
        lambda *args, **kwargs: FakeSSM(),
    )

    class FakeMessage:
        content = """{
            "contains_profanity": false,
            "1. profanity": [],
            "contains_depressive_content": false,
            "contains_suicidal_content": false,
            "2. Depressive/Suicidal Content": [],
            "contains_threatening_content": true,
            "3. Threatening Content": ["threatening"]
        }"""

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletions:
        def create(self, **kwargs):
            return type("Response", (), {"choices": [FakeChoice()]})()

    class FakeChat:
        completions = FakeCompletions()

    class FakeGroq:
        chat = FakeChat()

    monkeypatch.setattr(
        inappropriate_content_filter,
        "Groq",
        lambda *args, **kwargs: FakeGroq(),
    )

    event = {
        "body": json.dumps(
            {
                "subject": "Damn request",
                "description": "This request contains threatening content."
            }
        )
    }

    result = inappropriate_content_filter.lambda_handler(event, None)

    assert result["statusCode"] == 200

    body = json.loads(result["body"])

    flagged_scores = [
        item["score"]
        for item in body["severity_scores"]
        if item["flagged"]
    ]

    assert flagged_scores == [1, 3]