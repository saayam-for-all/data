"""Inappropriate content filter (Profanity API) for Help Requests.

Issue #422: every response now carries a severity score so the Help Request
workflow can route the request before it reaches volunteer matching.

    0  Good Request            -> request         (active matching)
    1  Foul Language           -> fraud_requests
    2  Depressive or Suicidal  -> fraud_requests
    3  Threatening             -> fraud_requests

If more than one category is flagged, the highest score wins.
"""
import json
import os
import sqlite3
import string

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profane_words.db")

SEVERITY_LABELS = {
    0: "Good Request",
    1: "Foul Language",
    2: "Depressive or Suicidal",
    3: "Threatening",
}

# Score 0 enters the matching workflow; anything else is held out of it.
GOOD_REQUEST_TABLE = "request"
FLAGGED_REQUEST_TABLE = "fraud_requests"


def get_severity_score(flags):
    if flags.get("contains_threatening_content"):
        return 3
    if flags.get("contains_depressive_content") or flags.get("contains_suicidal_content"):
        return 2
    if flags.get("contains_profanity"):
        return 1
    return 0


def route_request(score):
    # bool is an int subclass, so True would otherwise pass as score 1
    if isinstance(score, bool) or score not in SEVERITY_LABELS:
        raise ValueError(f"Invalid severity score: {score!r}")
    return {
        "route_to": GOOD_REQUEST_TABLE if score == 0 else FLAGGED_REQUEST_TABLE,
        "allow_active_matching": score == 0,
    }


def get_llm_flags(clean_text):
    # Imported here so the word-list path and the tests don't need the SDK
    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set.")

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
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
    llm_response = response.choices[0].message.content
    llm_response = llm_response.replace("```json", "").replace("```", "").strip()
    llm_dict = json.loads(llm_response)
    if not isinstance(llm_dict, dict):
        raise ValueError("Model did not return a JSON object.")
    return llm_dict


def _response(status_code, data):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": '*'
        },
        "body": json.dumps(data)
    }


def lambda_handler(event, context):
    try:
        body = json.loads(event.get('body') or '{}')
    except (TypeError, ValueError):
        return _response(400, {"error": "Request body must be valid JSON"})
    if not isinstance(body, dict):
        return _response(400, {"error": "Request body must be a JSON object"})

    subject = body.get('subject') or ""
    description = body.get('description') or ""
    if not isinstance(subject, str) or not isinstance(description, str):
        return _response(400, {"error": "subject and description must be strings"})
    if not subject.strip() and not description.strip():
        return _response(400, {"error": "subject or description is required"})
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

    # ---- Connect to SQLite DB ----
    if not os.path.exists(DB_PATH):
        return _response(500, {"error": "Database file not found"})

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()

        # Integrity check
        cursor.execute("PRAGMA integrity_check;")
        if cursor.fetchone()[0] != "ok":
            return _response(500, {"error": "Database integrity check failed"})

        # ---- Helper function for table lookup ----
        def lookup(table):
            # e.g. punctuation-only text: "IN ()" is invalid SQL
            if not input_words:
                return []
            placeholders = ",".join("?" for _ in input_words)
            query = f"SELECT words FROM {table} WHERE words IN ({placeholders})"
            cursor.execute(query, input_words)
            return [row[0] for row in cursor.fetchall()]

        # ---- Keyword detection ----
        profane_words = lookup("profane_words")
    finally:
        conn.close()

    try:
        response_data = get_llm_flags(clean_text)
        llm_profanity = response_data.get("1. profanity")
        if not isinstance(llm_profanity, list):
            llm_profanity = []
        profane_words_combined = sorted(set(profane_words + llm_profanity))
        response_data["contains_profanity"] = bool(profane_words_combined) or bool(
            response_data.get("contains_profanity"))
        response_data["1. profanity"] = profane_words_combined
        response_data["llm_checked"] = True
    except Exception:
        # Without the model we still score from the word list, so foul language
        # is never let through as a good request. llm_checked tells the caller
        # that depressive/threatening content could not be checked.
        response_data = {
            "status_code": 500,
            "Error": "Invalid API key or issue with the model",
            "contains_profanity": bool(profane_words),
            "1. profanity": profane_words,
            "contains_depressive_content": False,
            "contains_suicidal_content": False,
            "2. Depressive/Suicidal Content": [],

            "contains_threatening_content": False,
            "3. Threatening Content": [],
            "llm_checked": False,
        }

    score = get_severity_score(response_data)
    if score == 0:
        response_data = {"0. This is a normal request": []} | response_data

    response_data["severity_score"] = score
    response_data["severity_label"] = SEVERITY_LABELS[score]
    response_data.update(route_request(score))

    return _response(200, response_data)


if __name__ == "__main__":
    test_phrases = [
        "I've been feeling down, and there is no hope.",                 # English Depressive
        "Me siento increíblemente solo, vacío y que nada va a mejorar.", # Spanish Depressive
        "I'm feeling very happy today.",                                 # English Happy (Normal)
        "Hoy fui al supermercado y compré algunas frutas.",              # Spanish Normal
        "Get out of my way or you will regret it.",                      # English Threat
        "Te voy a buscar y lo vas a pagar muy caro."                     # Spanish Threat
    ]
    event = {
        "body": "{ \"subject\": \"Hi\", \"description\": \"Te voy a buscar y lo vas a pagar muy caro.\" }"
    }
    print(lambda_handler(event, ""))
