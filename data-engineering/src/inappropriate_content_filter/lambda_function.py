"""Lambda entry point for the Help Request content filter, extended with
severity scores (#422).

Scope note: the content filter itself (word-list lookup + an LLM pass for
depressive/suicidal/threatening language) is the already-implemented
Profanity API referenced by #422 -- this file is a from-scratch
reimplementation of that same approach (word-list + LLM moderation call),
not a rewrite of its design. The only new piece #422 actually asks for is
`severity_scores`: a fixed 0-3 list, every score always present, with a
`flagged` bool per score so a caller can see every category that applied
rather than only the single highest one.

Severity scores, from the issue:
  0 - normal (nothing else flagged)
  1 - profanity
  2 - depressive / suicidal content
  3 - threatening content

Routing the Help Request to a table/workflow based on these scores is
explicitly a downstream concern per the issue text ("Based on the scores,
help request will be routed") -- out of scope here; this function's job
ends at returning the scores.
"""
import json
import os
import sqlite3
import string

try:
    import boto3
except ImportError:  # pragma: no cover - boto3 is provided by the Lambda runtime
    boto3 = None

try:
    from groq import Groq
except ImportError:  # pragma: no cover - exercised only when the package is absent
    Groq = None

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

# Score -> (category name, response flags that trigger it). Score 0 isn't
# listed here -- it's "none of the others flagged", computed afterward.
SEVERITY_CATEGORIES = (
    (1, "profanity", ("contains_profanity",)),
    (2, "depressive_suicidal", ("contains_depressive_content", "contains_suicidal_content")),
    (3, "threatening", ("contains_threatening_content",)),
)

_SSM_PARAMETER_NAME = os.environ.get("GROQ_API_KEY_PARAMETER", "/dev/saayam/GenAI/groq/key")
_GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
}

# Trailing few letters stripped to catch simple plurals before a word-list
# lookup -- "insults" should match "insult". Deliberately not stripped for
# words where that would create a false match.
_SINGULAR_EXCEPTIONS = {"ass", "dumbass", "piss"}


def build_severity_scores(flags):
    """Returns all 4 severity scores (0-3), each with a `flagged` bool.

    Every score is always present -- the caller sees every category that
    applied, not only the highest one. `flags` is the dict of
    contains_profanity/contains_depressive_content/... booleans produced
    by the word-list + LLM pass.
    """
    scored = [
        {
            "score": score,
            "category": category,
            "flagged": any(bool(flags.get(key)) for key in keys),
        }
        for score, category, keys in SEVERITY_CATEGORIES
    ]
    normal = not any(entry["flagged"] for entry in scored)
    return [{"score": 0, "category": "normal", "flagged": normal}] + scored


def _singularize(word):
    if word in _SINGULAR_EXCEPTIONS:
        return word
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith("es") and len(word) > 2:
        return word[:-2]
    if word.endswith("s") and len(word) > 1:
        return word[:-1]
    return word


def _tokenize(text):
    translator = str.maketrans("", "", string.punctuation)
    return [_singularize(w) for w in text.translate(translator).lower().split()]


def _profane_words_db_path():
    return os.environ.get(
        "PROFANE_WORDS_DB", os.path.join(_MODULE_DIR, "profane_words.db")
    )


def _lookup_profane_words(words):
    db_path = _profane_words_db_path()
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Profane words database not found at {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        if not words:
            return []
        placeholders = ",".join("?" for _ in words)
        cursor.execute(f"SELECT words FROM profane_words WHERE words IN ({placeholders})", words)
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()


def _get_groq_api_key():
    ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    parameter = ssm.get_parameter(Name=_SSM_PARAMETER_NAME, WithDecryption=True)
    return parameter["Parameter"]["Value"]


_MODERATION_PROMPT = """You are a multilingual moderation assistant.

Determine whether the text has depressive content, suicidal language, or
threatening language. Respond with ONLY a JSON object, no other text, in
exactly this shape:

{{
  "contains_depressive_content": <bool>,
  "contains_suicidal_content": <bool>,
  "contains_threatening_content": <bool>,
  "depressive_suicidal_terms": [<words that triggered it>],
  "threatening_terms": [<words that triggered it>]
}}

Text: {text}
"""


def _moderate_with_llm(clean_text):
    """Calls the LLM for the categories a word list can't reliably catch
    (depressive/suicidal/threatening language, not just keyword profanity).
    Raises on any failure -- the caller falls back to word-list-only.
    """
    api_key = _get_groq_api_key()
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=_GROQ_MODEL,
        messages=[{"role": "user", "content": _MODERATION_PROMPT.format(text=clean_text)}],
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": dict(_JSON_HEADERS),
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    del context
    try:
        body = json.loads(event["body"]) if isinstance(event.get("body"), str) else event.get("body", event)
    except (json.JSONDecodeError, TypeError) as exc:
        return _response(400, {"error": f"Invalid request body: {exc}"})

    subject = (body.get("subject") or "").strip()
    description = (body.get("description") or "").strip()
    text = f"{subject} {description}".strip()
    if not text:
        return _response(400, {"error": "subject and/or description must be non-empty"})

    clean_text = text.translate(str.maketrans("", "", string.punctuation)).lower()
    words = _tokenize(text)

    try:
        profane_words = _lookup_profane_words(words)
    except FileNotFoundError as exc:
        return _response(500, {"error": str(exc)})

    llm_error = None
    try:
        llm_result = _moderate_with_llm(clean_text)
    except Exception as exc:  # LLM/SSM failure -- degrade to word-list only, don't crash
        llm_error = str(exc)
        llm_result = {
            "contains_depressive_content": False,
            "contains_suicidal_content": False,
            "contains_threatening_content": False,
            "depressive_suicidal_terms": [],
            "threatening_terms": [],
        }

    flags = {
        "contains_profanity": bool(profane_words),
        "profanity_terms": profane_words,
        "contains_depressive_content": bool(llm_result.get("contains_depressive_content")),
        "contains_suicidal_content": bool(llm_result.get("contains_suicidal_content")),
        "depressive_suicidal_terms": llm_result.get("depressive_suicidal_terms", []),
        "contains_threatening_content": bool(llm_result.get("contains_threatening_content")),
        "threatening_terms": llm_result.get("threatening_terms", []),
    }
    if llm_error is not None:
        flags["llm_error"] = llm_error

    flags["severity_scores"] = build_severity_scores(flags)
    return _response(200, flags)


def _run_local_samples():
    """Prints the handler's output for a handful of representative requests.
    Run with `PROFANE_WORDS_DB=/path/to/profane_words.db python lambda_function.py`.
    """
    samples = {
        "normal request": {"subject": "Groceries", "description": "I need help buying food"},
        "word-list profanity": {"subject": "Hey", "description": "What a damn mess"},
        "missing subject/description (should be 400)": {},
    }
    for label, body in samples.items():
        print(f"\n=== {label} ===")
        print(json.dumps(body))
        response = lambda_handler({"body": json.dumps(body)}, None)
        print(f"status={response['statusCode']}")
        print(json.dumps(json.loads(response["body"]), indent=2))


if __name__ == "__main__":
    if not os.path.exists(_profane_words_db_path()):
        print(f"No word database at {_profane_words_db_path()} -- run create_profane_words_db.py first")
    else:
        _run_local_samples()
