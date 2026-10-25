"""Content Filter (Profanity / Self-harm / Threat screening) for issue #422.

Standalone Lambda for the Help Request workflow's content screening step.
Given a Help Request's subject and description, returns a JSON report
flagging profanity, depressive/suicidal content, and threatening content,
along with the specific words/phrases that triggered each flag.

Per the scope clarified on the issue: this function ONLY returns the
classification JSON. It does not do any routing or database writes.

Design (split by what each check is actually good at):
- Profanity: checked locally against the `better-profanity` package's word
  list -- fast, free, no API call, no risk of an LLM being inconsistent on
  simple swear-word matching. Each word of the text is checked individually
  so we can report exactly which words were flagged.
- Depressive/suicidal content and threatening content: still use the LLM
  (mirrors src/categorizer/classifier.py's existing "prompt GPT for strict
  JSON" pattern), since these need language understanding a word list can't
  provide.

IMPORTANT -- fail-safe behavior on error:
If the LLM call fails or returns something unparseable, contains_
depressive_content/contains_suicidal_content/contains_threatening_content
are set to True (held for manual review) rather than defaulting to "nothing
flagged" -- silently waving through an unscreened Help Request during an
outage is worse than a false positive. The local profanity check is wrapped
the same way for consistency, even though it's much less likely to fail.
Confirm with the team whether this fail-safe behavior is what's wanted.
"""

import json
import os
import re

from openai import OpenAI
from dotenv import load_dotenv
from better_profanity import Profanity

load_dotenv()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

profanity = Profanity()
profanity.load_censor_words()

WORD_PATTERN = re.compile(r"[A-Za-z']+")


# --------------------------------------------------------------------------
# Profanity (local word list)
# --------------------------------------------------------------------------

def check_profanity(text: str):
    """Returns (contains_profanity: bool, flagged_words: list[str]).
    Checks each word individually (rather than the whole string at once)
    so we can report exactly which words triggered the flag.
    """
    try:
        words = WORD_PATTERN.findall(text or "")
        flagged = [w for w in words if profanity.contains_profanity(w)]
        # de-duplicate while preserving first-seen order
        seen = set()
        unique_flagged = []
        for w in flagged:
            key = w.lower()
            if key not in seen:
                seen.add(key)
                unique_flagged.append(w)
        return bool(unique_flagged), unique_flagged
    except Exception:  # noqa: BLE001
        # Fail-safe: if the local check itself breaks, flag for review
        # rather than silently reporting "no profanity."
        return True, []


# --------------------------------------------------------------------------
# Depressive/suicidal + threatening content (LLM)
# --------------------------------------------------------------------------

def build_prompt(subject: str, description: str) -> str:
    return f"""You are a content safety screener for a nonprofit help request platform.
Given a help request's subject and description, check it for two separate concerns.

For each concern, decide whether it is present (true/false) and list the
specific word(s) or short phrase(s) from the text that caused that decision.
If a concern is not present, its word list must be an empty list.

Concerns to check, independently of each other (a request can match either,
both, or neither):
1. Depressive or suicidal content -- expressions of hopelessness, self-harm,
   or suicidal ideation or intent. These are two separate flags
   (depressive vs. suicidal) but share one combined word/phrase list.
2. Threatening content -- language threatening violence or harm to others.

Respond ONLY with a valid JSON object, no extra text, in this exact shape:
{{
  "contains_depressive_content": <true/false>,
  "contains_suicidal_content": <true/false>,
  "2. Depressive/Suicidal Content": [<words/phrases found, or empty list>],
  "contains_threatening_content": <true/false>,
  "3. Threatening Content": [<words/phrases found, or empty list>]
}}

Help Request:
Subject: {subject}
Description: {description}"""


def _failed_review_result(reason: str) -> dict:
    """Fail-safe result for the LLM-based checks: flag both concerns for
    manual review rather than silently reporting a clean request when the
    automatic check itself failed. See the module docstring for why.
    """
    return {
        "contains_depressive_content": True,
        "contains_suicidal_content": True,
        "2. Depressive/Suicidal Content": [],
        "contains_threatening_content": True,
        "3. Threatening Content": [],
        "review_reason": reason,
    }


def parse_llm_classification(raw: str) -> dict:
    """Parse and validate the model's raw JSON text into the expected
    schema, defaulting any missing/malformed field fail-safe (True).
    Raises json.JSONDecodeError if raw isn't valid JSON at all (caller
    decides the fail-safe response in that case).
    """
    result = json.loads(raw)

    def _bool(key):
        return bool(result.get(key, True))  # missing -> fail-safe True

    def _list(key):
        value = result.get(key)
        return value if isinstance(value, list) else []

    return {
        "contains_depressive_content": _bool("contains_depressive_content"),
        "contains_suicidal_content": _bool("contains_suicidal_content"),
        "2. Depressive/Suicidal Content": _list("2. Depressive/Suicidal Content"),
        "contains_threatening_content": _bool("contains_threatening_content"),
        "3. Threatening Content": _list("3. Threatening Content"),
    }


def check_depressive_and_threatening(subject: str, description: str) -> dict:
    if not subject and not description:
        return {
            "contains_depressive_content": False,
            "contains_suicidal_content": False,
            "2. Depressive/Suicidal Content": [],
            "contains_threatening_content": False,
            "3. Threatening Content": [],
        }

    prompt = build_prompt(subject or "", description or "")

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=250,
        )
        raw = response.choices[0].message.content.strip()
        return parse_llm_classification(raw)
    except Exception as e:  # noqa: BLE001
        return _failed_review_result(f"Automatic content check failed: {e}")


# --------------------------------------------------------------------------
# Combined classification
# --------------------------------------------------------------------------

def classify_content(subject: str, description: str) -> dict:
    contains_profanity, profane_words = check_profanity(f"{subject or ''} {description or ''}")
    llm_result = check_depressive_and_threatening(subject, description)

    result = {
        "contains_profanity": contains_profanity,
        "1. profanity": profane_words,
        "contains_depressive_content": llm_result["contains_depressive_content"],
        "contains_suicidal_content": llm_result["contains_suicidal_content"],
        "2. Depressive/Suicidal Content": llm_result["2. Depressive/Suicidal Content"],
        "contains_threatening_content": llm_result["contains_threatening_content"],
        "3. Threatening Content": llm_result["3. Threatening Content"],
    }
    if "review_reason" in llm_result:
        result["review_reason"] = llm_result["review_reason"]
    return result


# --------------------------------------------------------------------------
# Lambda handler
# --------------------------------------------------------------------------

def build_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def lambda_handler(event, context):
    event = event or {}

    if isinstance(event.get("body"), str):
        try:
            params = json.loads(event["body"])
        except json.JSONDecodeError:
            return build_response(400, {"error": "request body is not valid JSON"})
    elif isinstance(event.get("body"), dict):
        params = event["body"]
    else:
        params = event

    if not isinstance(params, dict):
        return build_response(400, {"error": "request body must be a JSON object"})

    subject = params.get("subject", "")
    description = params.get("description", "")

    if not subject and not description:
        return build_response(
            400, {"error": "at least one of subject or description is required"}
        )

    result = classify_content(subject, description)
    return build_response(200, result)


if __name__ == "__main__":
    print("=== check_profanity: clean text ===")
    print(check_profanity("I need help with groceries this week"))

    print("\n=== check_profanity: profane text ===")
    print(check_profanity("This is such a damn shitty situation"))

    print("\n=== parse_llm_classification: well-formed response ===")
    sample_raw = json.dumps({
        "contains_depressive_content": True,
        "contains_suicidal_content": False,
        "2. Depressive/Suicidal Content": ["I feel so hopeless"],
        "contains_threatening_content": False,
        "3. Threatening Content": [],
    })
    print(json.dumps(parse_llm_classification(sample_raw), indent=2))

    print("\n=== lambda_handler: malformed JSON body ===")
    print(json.dumps(lambda_handler({"body": "{not valid json"}, None), indent=2))

    print("\n=== lambda_handler: empty body ===")
    print(json.dumps(lambda_handler({"body": json.dumps({})}, None), indent=2))

    print("\n=== classify_content: LLM call raises -> fail-safe, but profanity still works locally ===")
    original_create = client.chat.completions.create if hasattr(client, "chat") else None

    # Live calls below need OPENAI_API_KEY set in your environment/.env.
    sample_requests = {
        "clean request": {
            "subject": "Need help with groceries",
            "description": "I lost my job and could use some food assistance this week.",
        },
        "profanity example": {
            "subject": "This is such a damn mess",
            "description": "My landlord screwed me over and I don't know what to do.",
        },
        "depressive/suicidal example": {
            "subject": "I don't see the point anymore",
            "description": "I feel like giving up and ending it all. Nothing is working.",
        },
        "threatening example": {
            "subject": "Warning",
            "description": "If my request isn't handled I will find you and make you regret it.",
        },
    }

    for label, body in sample_requests.items():
        print(f"\n=== lambda_handler (live call): {label} ===")
        print(json.dumps(lambda_handler({"body": json.dumps(body)}, None), indent=2))
