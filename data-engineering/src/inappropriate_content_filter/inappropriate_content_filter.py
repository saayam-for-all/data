import json
import sqlite3
import string
import os

import boto3


# Same codes as the sentiment_codes table (database wiki, "Changes to the Database").
SENTIMENT_CODES = {
    0: "Good Request",
    1: "Foul Language",
    2: "Depressive or Suicidal",
    3: "Threatening",
}

# Score 0 goes into the normal matching workflow. Anything else is kept out of
# matching and saved in fraud_requests with ref_code = score.
GOOD_REQUEST_TABLE = "requests"
FLAGGED_REQUEST_TABLE = "fraud_requests"


def get_severity_score(response_data):
    """Return one score (0-3) for the request. If more than one category is
    flagged, the most serious one wins, since fraud_requests only stores one ref_code."""
    if response_data.get("contains_threatening_content"):
        return 3
    if response_data.get("contains_depressive_content") or response_data.get("contains_suicidal_content"):
        return 2
    if response_data.get("contains_profanity"):
        return 1
    return 0


def route_request(score):
    if score not in SENTIMENT_CODES:
        raise ValueError(f"Invalid severity score: {score}")
    return GOOD_REQUEST_TABLE if score == 0 else FLAGGED_REQUEST_TABLE


def get_llm_flags(clean_text):
    from groq import Groq

    ssm = boto3.client('ssm', region_name='us-east-1')
    param = ssm.get_parameter(Name='/dev/saayam/GenAI/groq/key', WithDecryption=True)
    api_key = param["Parameter"]["Value"]

    if not api_key:
        raise ValueError("Groq API key not found in SSM.")
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
    return json.loads(llm_response)


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
    db_path = os.path.join(os.getcwd(), 'profane_words.db')

    if not os.path.exists(db_path):
        return _response(500, {"error": "Database file not found"})

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Integrity check
    cursor.execute("PRAGMA integrity_check;")
    if cursor.fetchone()[0] != "ok":
        raise ValueError("Database integrity check failed.")

    # ---- Helper function for table lookup ----
    def lookup(table):
        # e.g. text that was only punctuation - "IN ()" is invalid SQL
        if not input_words:
            return []
        placeholders = ",".join("?" for _ in input_words)
        query = f"SELECT words FROM {table} WHERE words IN ({placeholders})"
        cursor.execute(query, input_words)
        return [row[0] for row in cursor.fetchall()]

    # ---- Keyword detection ----
    profane_words = lookup("profane_words")
    # depressive_words = lookup("depressive_suicidal_terms")
    # threatening_words = lookup("threatening_language")

    conn.close()

    try:
        response_data = get_llm_flags(clean_text)
        profane_words_combined = list(set(profane_words + response_data.get("1. profanity", [])))
        response_data["contains_profanity"] = bool(profane_words_combined)
        response_data["1. profanity"] = profane_words_combined
    except Exception:
        # If the LLM call fails we still score using the word list, so a
        # request with foul language is not let through as a good request.
        response_data = {
            "status_code": 500,
            "Error": "Invalid API key or issue with the model",
            "contains_profanity": bool(profane_words),
            "1. profanity": profane_words,
            "contains_depressive_content": False,
            "contains_suicidal_content": False,
            "2. Depressive/Suicidal Content": [],

            "contains_threatening_content": False,
            "3. Threatening Content": []
        }

    score = get_severity_score(response_data)
    if score == 0:
        response_data = {"0. This is a normal request": []} | response_data

    response_data["severity_score"] = score
    response_data["severity_label"] = SENTIMENT_CODES[score]
    response_data["route_to"] = route_request(score)

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
