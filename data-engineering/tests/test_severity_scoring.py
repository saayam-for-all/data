import json
from src.severity_scoring.handler import lambda_handler, score_text

def test_normal_request():
    result = score_text("I need help with groceries")
    assert result["severity_scores"] == [0]
    assert result["highest"] == 0


def test_profanity():
    assert score_text("this is bullshit")["severity_scores"] == [1]


def test_depressive():
    assert score_text("I want to die")["severity_scores"] == [2]


def test_threat():
    assert score_text("I will find you")["severity_scores"] == [3]


def test_multiple_flags():
    result = score_text("damn, I will hurt you")
    assert result["severity_scores"] == [1, 3]
    assert result["highest"] == 3


def test_empty_and_none():
    assert score_text("")["severity_scores"] == [0]
    assert score_text(None)["severity_scores"] == [0]


def test_no_match_inside_other_words():
    assert score_text("my class is at noon")["severity_scores"] == [0]

def test_handler_normal_request():
    event = {"body": json.dumps({"subject": "Help", "description": "need groceries"})}
    response = lambda_handler(event, None)
    assert response["statusCode"] == 200
    assert response["body"]["severity_scores"] == [0]


def test_handler_flags_threat():
    event = {"subject": "Help", "description": "I will hurt you"}
    response = lambda_handler(event, None)
    assert response["body"]["severity_scores"] == [3]

def test_handler_bad_body():
    response = lambda_handler({"body": "not json"}, None)
    assert response["statusCode"] == 400

def test_uppercase_text():
    assert score_text("DAMN IT")["severity_scores"] == [1]


def test_normal_pay_sentence_is_not_a_threat():
    assert score_text("you will pay the volunteer back")["severity_scores"] == [0]


def test_indirect_depressive_wording():
    assert score_text("I can't do this anymore")["severity_scores"] == [2]


def test_curly_apostrophe():
    assert score_text("I can’t go on")["severity_scores"] == [2]


def test_handler_missing_fields():
    response = lambda_handler({"foo": "bar"}, None)
    assert response["statusCode"] == 400