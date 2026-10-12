import json
import logging
import sqlite3
import string
import os

# from huggingface_hub import InferenceClient
from groq import Groq

# from dotenv import load_dotenv
import boto3

logger = logging.getLogger(__name__)

GROQ_KEY_PARAMETER = '/dev/saayam/GenAI/groq/key'

# Fixed, safe error codes. Exception text is never returned to callers because
# it can contain secrets, ARNs or request content.
ERROR_INVALID_INPUT = "invalid_input"
ERROR_KEYWORD_DB = "keyword_database_unavailable"
ERROR_SECRET = "classifier_secret_unavailable"
ERROR_CLASSIFIER = "classifier_unavailable"
ERROR_RESPONSE = "classifier_response_invalid"

ERROR_MESSAGES = {
    ERROR_INVALID_INPUT: "subject and description must be strings and at least one must not be blank.",
    ERROR_KEYWORD_DB: "The keyword database is unavailable; the request could not be classified.",
    ERROR_SECRET: "The classifier credentials are unavailable; the request could not be classified.",
    ERROR_CLASSIFIER: "The content classifier is unavailable; the request could not be classified.",
    ERROR_RESPONSE: "The content classifier returned an unusable response; the request could not be classified.",
}

# Flags the LLM must return as real booleans. A missing or mistyped flag is a
# failed classification, never an implicit "False".
LLM_REQUIRED_FLAGS = (
    "contains_depressive_content",
    "contains_suicidal_content",
    "contains_threatening_content",
)
LLM_OPTIONAL_LISTS = (
    "2. Depressive/Suicidal Content",
    "3. Threatening Content",
)

# Severity score -> category -> response flags that trigger the score.
SEVERITY_CATEGORIES = (
    (1, "profanity", ("contains_profanity",)),
    (
        2,
        "depressive_suicidal",
        ("contains_depressive_content", "contains_suicidal_content"),
    ),
    (3, "threatening", ("contains_threatening_content",)),
)


def build_severity_scores(response_data, degraded=False):
    """
    Build severity classifications for a help request.

    Score 0: Normal request
    Score 1: Profanity
    Score 2: Depressive or suicidal content
    Score 3: Threatening content

    More than one non-zero severity may be flagged when the request
    contains multiple types of inappropriate content.

    When ``degraded`` is True the classifier did not finish, so nothing can be
    declared normal: score 0 is never flagged, a category is ``True`` only when
    keyword evidence exists, and every other category is ``None`` (unknown).
    """
    if degraded:
        degraded_scores = [{"score": 0, "category": "normal", "flagged": False}]
        for score, category, flags in SEVERITY_CATEGORIES:
            has_evidence = any(response_data.get(flag) is True for flag in flags)
            degraded_scores.append(
                {
                    "score": score,
                    "category": category,
                    "flagged": True if has_evidence else None,
                }
            )
        return degraded_scores

    severity_scores = []

    for score, category, flags in SEVERITY_CATEGORIES:
        flagged = any(bool(response_data.get(flag)) for flag in flags)

        severity_scores.append(
            {
                "score": score,
                "category": category,
                "flagged": flagged,
            }
        )

    has_flagged_content = any(
        severity["flagged"] for severity in severity_scores
    )

    normal_score = {
        "score": 0,
        "category": "normal",
        "flagged": not has_flagged_content,
    }

    return [normal_score] + severity_scores


class ClassifierError(Exception):
    """A required classification step failed; carries a safe error code only."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _json_response(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": '*'
        },
        "body": json.dumps(payload)
    }


def _parse_request(event):
    """Return (subject, description) or raise ClassifierError(invalid_input)."""
    body = event.get('body') if isinstance(event, dict) else None

    if isinstance(body, (str, bytes)):
        try:
            body = json.loads(body)
        except ValueError:
            raise ClassifierError(ERROR_INVALID_INPUT) from None

    if not isinstance(body, dict):
        raise ClassifierError(ERROR_INVALID_INPUT)

    subject = body.get('subject')
    description = body.get('description')

    if not isinstance(subject, str) or not isinstance(description, str):
        raise ClassifierError(ERROR_INVALID_INPUT)

    if not (subject + description).strip():
        raise ClassifierError(ERROR_INVALID_INPUT)

    return subject, description


def _lookup_profane_words(input_words):
    """Return the profane words found in ``input_words`` from the SQLite DB."""
    db_path = os.path.join(os.getcwd(), 'profane_words.db')

    if not os.path.exists(db_path):
        logger.error("profane_words.db not found")
        raise ClassifierError(ERROR_KEYWORD_DB)

    if not input_words:
        return []

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Integrity check
        cursor.execute("PRAGMA integrity_check;")
        if cursor.fetchone()[0] != "ok":
            raise ValueError("Database integrity check failed.")

        placeholders = ",".join("?" for _ in input_words)
        query = f"SELECT words FROM profane_words WHERE words IN ({placeholders})"
        cursor.execute(query, input_words)
        return [row[0] for row in cursor.fetchall()]
    except (sqlite3.Error, ValueError) as exc:
        logger.error("Keyword database lookup failed: %s", type(exc).__name__)
        raise ClassifierError(ERROR_KEYWORD_DB) from None
    finally:
        if conn is not None:
            conn.close()


def _get_groq_api_key():
    """Fetch the Groq API key string from SSM Parameter Store."""
    try:
        ssm = boto3.client('ssm', region_name='us-east-1')
        response = ssm.get_parameter(Name = GROQ_KEY_PARAMETER, WithDecryption = True)
        api_key = response["Parameter"]["Value"]
    except Exception as exc:
        logger.error("Could not retrieve the classifier secret: %s", type(exc).__name__)
        raise ClassifierError(ERROR_SECRET) from None

    if not isinstance(api_key, str) or not api_key.strip():
        logger.error("Classifier secret was empty or not a string")
        raise ClassifierError(ERROR_SECRET)

    return api_key


def _validate_llm_payload(payload):
    """Return a trusted copy of the LLM classification or raise ClassifierError."""
    if not isinstance(payload, dict):
        raise ClassifierError(ERROR_RESPONSE)

    for flag in LLM_REQUIRED_FLAGS:
        if type(payload.get(flag)) is not bool:
            raise ClassifierError(ERROR_RESPONSE)

    def string_list(key):
        # Evidence lists are informational: missing or null means "no words
        # listed". Only the boolean flags above decide the classification.
        value = payload.get(key)
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ClassifierError(ERROR_RESPONSE)
        return value

    validated = {flag: payload[flag] for flag in LLM_REQUIRED_FLAGS}
    validated["1. profanity"] = string_list("1. profanity")
    for key in LLM_OPTIONAL_LISTS:
        validated[key] = string_list(key)

    return validated


def _degraded_response(code, profane_words=None):
    """503 response for a request that could not be fully classified.

    Keyword-derived results are included as partial information only; they
    never imply the request is safe.
    """
    keyword_hit = bool(profane_words)

    response_data = {
        "classification_status": "degraded",
        "severity_score": None,
        "error_code": code,
        "error": ERROR_MESSAGES[code],
        "contains_profanity": True if keyword_hit else None,
        "1. profanity": list(profane_words) if profane_words is not None else None,
        "contains_depressive_content": None,
        "contains_suicidal_content": None,
        "2. Depressive/Suicidal Content": None,
        "contains_threatening_content": None,
        "3. Threatening Content": None,
    }
    response_data["severity_scores"] = build_severity_scores(response_data, degraded=True)

    return _json_response(503, response_data)


def lambda_handler(event, context):
    """Classify a help request.

    Success (HTTP 200): the original fields plus ``classification_status``
    "complete" and a numeric ``severity_score`` (0-3). If several categories
    are flagged the highest score is used. That precedence is provisional,
    pending maintainer confirmation on issue #422; the full per-category
    ``severity_scores`` list is always returned so consumers can apply their
    own policy.

    Failure to classify (HTTP 503): ``classification_status`` "degraded",
    ``severity_score`` null and a safe ``error_code``. Never read this as a
    normal request. Invalid input returns HTTP 400.
    """
    try:
        subject, description = _parse_request(event)
    except ClassifierError as error:
        return _json_response(
            400, {"error": ERROR_MESSAGES[error.code], "error_code": error.code}
        )

    text = subject + " " + description

    # Remove punctuation
    translator = str.maketrans('', '', string.punctuation)
    clean_text = text.translate(translator).lower()
    input_words = clean_text.split()

    # ---- Singular form handling ----
    singular_words = ['ass', 'dumbass', 'piss']
    for i, word in enumerate(input_words):
        if word in singular_words:
            continue
        if word.endswith("ies"):
            input_words[i] = word[:-3] + "y"
        elif word.endswith("es") and len(word) > 2:
            input_words[i] = word[:-2]
        elif word.endswith("s") and len(word) > 1:
            input_words[i] = word[:-1]

    # ---- Keyword detection (SQLite DB) ----
    try:
        profane_words = _lookup_profane_words(input_words)
    except ClassifierError as error:
        return _degraded_response(error.code)
    # depressive_words = lookup("depressive_suicidal_terms")
    # threatening_words = lookup("threatening_language")

    # ---- LLM classification ----
    try:
        api_key = _get_groq_api_key()
    except ClassifierError as error:
        return _degraded_response(error.code, profane_words)

    try:
        # client = InferenceClient(api_key = api_key)
        client = Groq(api_key = api_key)
        response = client.chat.completions.create(
        model = "openai/gpt-oss-120b",
        messages = [

            {
                "role": "user",
                "content": f""" You are a multilingual moderation assistant.

                Determine whether the text has depressive content, suicidal language, or threatening language.

                Return it as a JSON object in the following format:
                    "contains_profanity": contains_profanity,
                    "1. profanity": profane_words,
                    "contains_depressive_content": contains_depressive_content,
                    "contains_suicidal_content": contains_suicidal_content,
                    "2. Depressive/Suicidal Content": depressive_suicidal_words,

                    "contains_threatening_content": contains_threatening_content,
                    "3. Threatening Content": threatening_words

                Text: {clean_text}
                """
            }
            ]
        )
    except Exception as exc:
        logger.error("Classifier request failed: %s", type(exc).__name__)
        return _degraded_response(ERROR_CLASSIFIER, profane_words)

    # ---- Validate the model output before trusting it ----
    try:
        llm_response = response.choices[0].message.content
        llm_response = llm_response.replace("```json", "").replace("```", "").strip()
        llm_dict = _validate_llm_payload(json.loads(llm_response))
    except ClassifierError as error:
        return _degraded_response(error.code, profane_words)
    except (AttributeError, IndexError, TypeError, ValueError):
        return _degraded_response(ERROR_RESPONSE, profane_words)

    profane_words_combined = sorted(set(profane_words + llm_dict["1. profanity"]))
    llm_dict["contains_profanity"] = bool(profane_words_combined)
    llm_dict["1. profanity"] = profane_words_combined

    # ---- Final Response ----
    response_data = llm_dict

    if not response_data["contains_profanity"] and not response_data["contains_depressive_content"] and not response_data["contains_suicidal_content"] and not response_data["contains_threatening_content"]:
        normal_dict = {"0. This is a normal request": []}
        response_data = normal_dict | response_data

    response_data["severity_scores"] = build_severity_scores(response_data)
    response_data["classification_status"] = "complete"
    response_data["severity_score"] = max(
        (item["score"] for item in response_data["severity_scores"] if item["flagged"]),
        default=0,
    )

    return _json_response(200, response_data)



if __name__ == "__main__":
    test_phrases = [
    "I've been feeling down, and there is no hope.",                 # English Depressive
    "Me siento incre├¡blemente solo, vac├¡o y que nada va a mejorar.", # Spanish Depressive
    "I'm feeling very happy today.",                                 # English Happy (Normal)
    "Hoy fui al supermercado y compr├⌐ algunas frutas.",              # Spanish Normal
    "Get out of my way or you will regret it.",                     # English Threat
    "Te voy a buscar y lo vas a pagar muy caro."                    # Spanish Threat
    ]
    event = {
        "body": "{ \"subject\": \"Hi\", \"description\": \"Te voy a buscar y lo vas a pagar muy caro.\" }"
        }
    print(lambda_handler(event, ""))
