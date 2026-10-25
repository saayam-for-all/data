"""
Help Request Content Evaluator.

Analyzes incoming help requests for profanity, depressive/suicidal themes, 
and threatening language using a hybrid approach (local SQLite DB + Groq LLM).
Outputs a unified JSON schema containing the detected text and a routing severity score (0-3).
"""

import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

logger = logging.getLogger()
logger.setLevel(logging.INFO)

GROQ_PARAM_PATH = "/dev/saayam/GenAI/groq/key"
DEFAULT_MODEL = "openai/gpt-oss-120b"
SQLITE_BATCH_SIZE = 500


def format_api_response(status_code: int, response_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Wraps the output in a standard API Gateway response format."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(response_payload),
    }


def validate_and_parse_event(event: Any) -> Tuple[Dict[str, Any], Optional[str]]:
    """Extracts and validates the JSON body from direct or API Gateway invocations."""
    if not event or not isinstance(event, dict):
        return {}, "Invocation event must be a valid JSON object."
    
    body = event.get("body", event)
    if body is None:
        return {}, None
        
    if isinstance(body, dict):
        return body, None
        
    try:
        parsed_body = json.loads(body)
        if not isinstance(parsed_body, dict):
            return {}, "Parsed body must be a JSON object."
        return parsed_body, None
    except (json.JSONDecodeError, TypeError):
        return {}, "Request body contains malformed JSON."


def merge_text_fields(payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Combines subject and description fields into a single analyzable string."""
    text_segments = []
    for key in ("subject", "description"):
        val = payload.get(key)
        if val is None:
            continue
        if not isinstance(val, str):
            return None, "Fields 'subject' and 'description' must be strings."
        if val.strip():
            text_segments.append(val.strip())
            
    if not text_segments:
        return None, "A valid 'subject' or 'description' must be provided."
        
    return " ".join(text_segments), None


def extract_normalized_words(text: str) -> List[str]:
    """Strips punctuation and lowercases text for database matching."""
    cleaned_text = re.sub(r"[^\w\s]", "", text.lower())
    return cleaned_text.split()


def apply_basic_stemming(word: str) -> str:
    """Applies basic suffix rules to match plural forms in the database."""
    exceptions = {"ass", "dumbass", "piss"}
    if word in exceptions:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("es") and len(word) > 2:
        return word[:-2]
    if word.endswith("s") and len(word) > 1:
        return word[:-1]
    return word


def generate_search_terms(words: List[str]) -> List[str]:
    """Creates a deduplicated list of original words and their stemmed versions."""
    term_map = {}
    for w in words:
        term_map[w] = True
        term_map[apply_basic_stemming(w)] = True
    return list(term_map.keys())


def query_local_dictionary(words: List[str]) -> Tuple[List[str], Optional[str]]:
    """Checks the sanitized words against the local SQLite profanity database."""
    db_location = os.environ.get(
        "PROFANE_WORDS_DB",
        str(Path(__file__).parent / "profane_words.db")
    )
    
    if not Path(db_location).exists():
        return [], "Local profanity database is missing."

    search_terms = generate_search_terms(words)
    if not search_terms:
        return [], None

    detected_words = set()
    try:
        with sqlite3.connect(db_location) as conn:
            cursor = conn.cursor()
            for offset in range(0, len(search_terms), SQLITE_BATCH_SIZE):
                batch = search_terms[offset:offset + SQLITE_BATCH_SIZE]
                placeholders = ",".join("?" for _ in batch)
                query = f"SELECT words FROM profane_words WHERE words IN ({placeholders})"
                
                for row in cursor.execute(query, batch):
                    detected_words.add(row[0])
        return sorted(detected_words), None
    except sqlite3.Error as e:
        logger.error(f"Database execution failed: {e}")
        return [], "Failed to read from local database."


def sanitize_llm_array(array_val: Any) -> List[str]:
    """Ensures LLM outputs are strictly lists of non-empty strings."""
    if not isinstance(array_val, list):
        return []
    return [str(item).strip() for item in array_val if isinstance(item, str) and str(item).strip()]


def invoke_llm_classifier(text: str) -> Dict[str, List[str]]:
    """Delegates contextual analysis to the Groq LLM."""
    import boto3
    from groq import Groq

    ssm_client = boto3.client("ssm", region_name="us-east-1")
    param_response = ssm_client.get_parameter(Name=GROQ_PARAM_PATH, WithDecryption=True)
    groq_api_key = param_response["Parameter"]["Value"]

    system_prompt = (
        "You are an expert multilingual content moderator. Analyze the provided text and "
        "extract any instances of profanity, depressive language, suicidal language, and "
        "threatening language. Respond ONLY with a valid JSON object using exactly these keys: "
        '["profanity", "depressive", "suicidal", "threatening"]. '
        "The values must be arrays of exact quotes from the text. If none exist, return an empty array.\n\n"
        f"Text to analyze: {text}"
    )
    
    client = Groq(api_key=groq_api_key)
    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[{"role": "user", "content": system_prompt}],
    )
    
    raw_output = response.choices[0].message.content
    clean_json_str = raw_output.replace("```json", "").replace("```", "").strip()
    parsed_json = json.loads(clean_json_str)
    
    return {
        key: sanitize_llm_array(parsed_json.get(key))
        for key in ("profanity", "depressive", "suicidal", "threatening")
    }


def determine_routing_severity(flags: Dict[str, bool]) -> int:
    """Calculates the 0-3 severity score required for downstream routing."""
    if flags.get("contains_threatening_content"):
        return 3
    if flags.get("contains_depressive_content") or flags.get("contains_suicidal_content"):
        return 2
    if flags.get("contains_profanity"):
        return 1
    return 0


def process_content_evaluation(text: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Orchestrates DB and LLM checks, merging results into the final routing schema."""
    db_matches, db_err = query_local_dictionary(extract_normalized_words(text))

    llm_err = None
    llm_results = {"profanity": [], "depressive": [], "suicidal": [], "threatening": []}
    try:
        llm_results = invoke_llm_classifier(text)
    except Exception as e:
        logger.error(f"LLM Invocation Error: {str(e)}")
        llm_err = "Content analysis model unavailable"

    if db_err and llm_err:
        return None, "Content analysis unavailable"

    merged_profanity = sorted(set(db_matches) | {w.lower() for w in llm_results["profanity"]})
    depressive_items = llm_results["depressive"]
    suicidal_items = llm_results["suicidal"]
    threatening_items = llm_results["threatening"]

    evaluation = {
        "contains_profanity": bool(merged_profanity),
        "1. profanity": merged_profanity,
        "contains_depressive_content": bool(depressive_items),
        "contains_suicidal_content": bool(suicidal_items),
        "2. Depressive/Suicidal Content": list(dict.fromkeys(depressive_items + suicidal_items)),
        "contains_threatening_content": bool(threatening_items),
        "3. Threatening Content": threatening_items,
    }
    
    evaluation["severity_score"] = determine_routing_severity(evaluation)

    active_errors = [err for err in (db_err, llm_err) if err]
    if active_errors:
        evaluation["Error"] = " | ".join(active_errors)
    elif evaluation["severity_score"] == 0:
        evaluation = {"0. This is a normal request": [], **evaluation}
        
    return evaluation, None


def lambda_handler(event: Any, context: Any) -> Dict[str, Any]:
    """AWS Lambda entry point."""
    payload, parse_err = validate_and_parse_event(event)
    if parse_err:
        return format_api_response(400, {"error": parse_err})

    text_to_analyze, text_err = merge_text_fields(payload)
    if text_err:
        return format_api_response(400, {"error": text_err})

    try:
        final_body, eval_err = process_content_evaluation(text_to_analyze)
    except Exception as e:
        logger.error(f"Unexpected execution failure: {str(e)}", exc_info=True)
        return format_api_response(500, {"error": "Internal server error"})

    if eval_err:
        return format_api_response(500, {"error": eval_err})
        
    return format_api_response(200, final_body)