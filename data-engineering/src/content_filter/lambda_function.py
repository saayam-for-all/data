"""Content filter Lambda.

Flags profanity, depressive/suicidal and threatening content in a help request.
Profanity comes from a local SQLite word list plus the LLM; the other two
categories come from the LLM. Returns the JSON shape agreed with the Data
Analytics team (keys are numbered by severity category).
"""

import json
import logging
import os
import re
import sqlite3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

GROQ_KEY_PARAM = "/dev/saayam/GenAI/groq/key"
GROQ_MODEL = "openai/gpt-oss-120b"
SQL_CHUNK = 500


def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def parse_event_body(event):
    """Return (payload, error). Handles API Gateway events and direct calls."""
    if event is None:
        return {}, None
    if not isinstance(event, dict):
        return {}, "Event must be a JSON object"
    if "body" in event:
        body = event["body"]
        if body is None:
            return {}, None
        if isinstance(body, dict):
            return body, None
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return {}, "Malformed JSON in request body"
        if not isinstance(parsed, dict):
            return {}, "Request body must be a JSON object"
        return parsed, None
    return event, None


def extract_text(payload):
    """Join subject and description into one string. Returns (text, error)."""
    parts = []
    for value in (payload.get("subject"), payload.get("description")):
        if value is None:
            continue
        if not isinstance(value, str):
            return None, "subject and description must be strings"
        if value.strip():
            parts.append(value.strip())
    if not parts:
        return None, "subject or description is required"
    return " ".join(parts), None


def tokenize(text):
    """Lowercase, drop punctuation, split into words (keeps accented letters)."""
    return re.sub(r"[^\w\s]", "", text.lower()).split()


def singular(word):
    """Same plural rules as the original filter."""
    if word in ("ass", "dumbass", "piss"):
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("es") and len(word) > 2:
        return word[:-2]
    if word.endswith("s") and len(word) > 1:
        return word[:-1]
    return word


def lookup_candidates(words):
    """Each word plus its singular form, de-duplicated, order preserved."""
    ordered = {}
    for w in words:
        ordered[w] = None
        ordered[singular(w)] = None
    return list(ordered)

def find_profane_words(words):
    """Look words up in the SQLite word list. Returns (matches, error)."""
    db_path = os.environ.get(
        "PROFANE_WORDS_DB",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "profane_words.db"),
    )
    if not os.path.exists(db_path):
        return [], "Profane word database not found"

    candidates = lookup_candidates(words)
    if not candidates:
        return [], None

    conn = sqlite3.connect(db_path)
    try:
        found = set()
        for i in range(0, len(candidates), SQL_CHUNK):
            chunk = candidates[i:i + SQL_CHUNK]
            marks = ",".join("?" for _ in chunk)
            rows = conn.execute(
                f"SELECT words FROM profane_words WHERE words IN ({marks})", chunk
            ).fetchall()
            found.update(row[0] for row in rows)
        return sorted(found), None
    finally:
        conn.close()


def call_llm(text):
    """Ask the LLM about profane, depressive, suicidal and threatening content.

    Returns a dict of four lists. Raises on any failure so the caller can fall
    back to keyword results. Tests replace this function with a fake.
    """
    import boto3
    from groq import Groq

    ssm = boto3.client("ssm", region_name="us-east-1")
    api_key = ssm.get_parameter(Name=GROQ_KEY_PARAM, WithDecryption=True)["Parameter"]["Value"]

    prompt = (
        "You are a multilingual content moderation assistant. Read the text and "
        "list any profane words, depressive language, suicidal language and "
        "threatening language that appear in it. Reply with ONLY a JSON object "
        'with exactly these keys: "profanity", "depressive", "suicidal", '
        '"threatening". Each value is a list of the offending words or phrases '
        "copied from the text, or an empty list if there are none.\n\nText: " + text
    )
    client = Groq(api_key=api_key)
    reply = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = reply.choices[0].message.content.replace("```json", "").replace("```", "").strip()
    parsed = json.loads(raw)
    return {
        key: clean_list(parsed.get(key))
        for key in ("profanity", "depressive", "suicidal", "threatening")
    }


def clean_list(value):
    """Keep only non-empty strings from an LLM-provided list."""
    if not isinstance(value, list):
        return []
    return [v.strip() for v in value if isinstance(v, str) and v.strip()]

def analyze_text(text):
    """Return (body, error). error is set only when no analysis was possible."""
    profane_db, db_error = find_profane_words(tokenize(text))

    llm_error = None
    try:
        llm = call_llm(text)
    except Exception:
        logger.exception("LLM call failed")
        llm = {"profanity": [], "depressive": [], "suicidal": [], "threatening": []}
        llm_error = "Content analysis model unavailable"

    if db_error and llm_error:
        return None, "Content analysis unavailable"

    profanity = sorted(set(profane_db) | {w.lower() for w in llm["profanity"]})
    depressive = llm["depressive"]
    suicidal = llm["suicidal"]
    threatening = llm["threatening"]

    body = {
        "contains_profanity": bool(profanity),
        "1. profanity": profanity,
        "contains_depressive_content": bool(depressive),
        "contains_suicidal_content": bool(suicidal),
        "2. Depressive/Suicidal Content": list(dict.fromkeys(depressive + suicidal)),
        "contains_threatening_content": bool(threatening),
        "3. Threatening Content": threatening,
    }

    errors = [e for e in (db_error, llm_error) if e]
    if errors:
        body["Error"] = "; ".join(errors)
    elif not (profanity or depressive or suicidal or threatening):
        body = {"0. This is a normal request": [], **body}
    return body, None


def lambda_handler(event, context):
    payload, err = parse_event_body(event)
    if err:
        return build_response(400, {"error": err})

    text, err = extract_text(payload)
    if err:
        return build_response(400, {"error": err})

    try:
        body, err = analyze_text(text)
    except Exception:
        logger.exception("Unhandled error in content filter")
        return build_response(500, {"error": "Internal server error"})

    if err:
        return build_response(500, {"error": err})
    return build_response(200, body)