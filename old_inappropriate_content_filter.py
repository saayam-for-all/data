import json
import sqlite3
import string
import os
import re
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
# from googletrans import Translator

# New API for language detection and translation
# @app.route('/api/translate', methods=['POST'])
#def translate_request_content():
#    data = request.get_json()
#    content = data.get('content', '')
#    http_res = {}

#    if not content:
#        http_res['status_code'] = 400
#        res_body = {"error": "No content provided"}
#        http_res['body'] = json.dumps(res_body)
#
#        return http_res
#
    # Translate the text to English
#    translator = Translator()
#    translated = translator.translate(content, dest="en")
#    translated_content = translated.text

#    res_body = {
#        "original": content,
#        "translated": translated_content
#        }

#    http_res['statusCode'] = 200
#    http_res['body'] = json.dumps(res_body)

#    return http_res

def lambda_handler(event, context):
    body = json.loads(event["body"])
    subject = body.get("subject")
    description = body.get("description")
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
        return {"statusCode": 500, "body": "Database file not found"}

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Integrity check
    cursor.execute("PRAGMA integrity_check;")
    if cursor.fetchone()[0] != "ok":
        raise ValueError("Database integrity check failed.")

    # ---- Helper function for table lookup ----
    def lookup(table):
        placeholders = ",".join("?" for _ in input_words)
        query = f"SELECT words FROM {table} WHERE words IN ({placeholders})"
        cursor.execute(query, input_words)
        return [row[0] for row in cursor.fetchall()]

    # ---- Keyword detection ----
    profane_words = lookup("profane_words")
    depressive_words = lookup("depressive_suicidal_terms")
    threatening_words = lookup("threatening_language")

    conn.close()

    # ---- Sentiment Analysis ----
    analyzer = SentimentIntensityAnalyzer()
    sentiment = analyzer.polarity_scores(text)

    compound = sentiment["compound"]
    neg = sentiment["neg"]

    # ---- Suicide / Depression Heuristics ----
    suicidal_patterns = [
        r"kill myself", r"end my life", r"i don'?t want to live",
        r"suicide", r"i hate my life", r"better off dead"
    ]

    suicide_flag = (
        any(re.search(p, clean_text) for p in suicidal_patterns)
        or compound < -0.65
        or neg > 0.45
        or bool(depressive_words)
    )

    # ---- Threat Heuristics ----
    threat_patterns = [
        r"kill you", r"hurt you", r"shoot", r"bomb", r"attack", r"destroy you"
    ]

    threat_flag = (
        any(re.search(p, clean_text) for p in threat_patterns)
        or compound < -0.55 and bool(threatening_words)
    )

    # ---- Final Response ----
    response_data = {
        "contains_profanity": bool(profane_words),
        "profanity": profane_words,

        "contains_depressive_content": bool(depressive_words),
        "contains_suicidal_content": suicide_flag,
        "2. Depressive/Suicidal Words": depressive_words,

        "keyword_threats": bool(threatening_words),
        "contains_threatening_content": threat_flag,
        "3. Threatening Content": threatening_words
    }

    return {
        "statusCode": 200,
        "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": '*'
            },
        "body": json.dumps(response_data)
    }
