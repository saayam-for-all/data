"""Profanity severity classifier for Help Request content (issue #422).

Mirrors `src/categorizer/classifier.py`: build a strict prompt, ask
gpt-3.5-turbo for JSON, then validate and coerce the reply before trusting it.

Two deliberate differences from the categorizer, both defensive:

1. `openai` is imported optionally and the client is built lazily. The
   categorizer constructs its client at module import, so importing it without
   `OPENAI_API_KEY` set - or without the package installed, which is the case
   for anyone who has only run `pip install -r requirements.txt`, since `openai`
   lives in the categorizer's own requirements file - raises on import. Keeping
   that out of this module is what lets `severity.py` and the routing tests run
   with no API key and no extra install.

2. A classification that cannot be trusted returns `severity_score: None`
   rather than a fabricated 0, so `severity.route` can tell an undetermined
   verdict apart from a real CLEAN one.

UNVERIFIED: the live gpt-3.5-turbo call has not been executed. There is no
OpenAI key in this environment and the package is not installed here, so every
test mocks the client. What is verified is the prompt construction, the
validation and coercion of the model's reply, and the error handling.
"""
import json
import os

from dotenv import load_dotenv

from src.profanity.severity import SEVERITY_SCALE, VALID_SCORES

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:  # keeps severity.py and the routing tests importable
    OpenAI = None
    OPENAI_AVAILABLE = False

load_dotenv()

MODEL = "gpt-3.5-turbo"
MAX_TOKENS = 200

_client = None


def get_client():
    """Build the OpenAI client on first use.

    Lazy on purpose: see the module docstring. Raises rather than returning None
    so the caller's except block records a real reason in `reasoning`.
    """
    global _client

    if not OPENAI_AVAILABLE:
        raise RuntimeError(
            "The 'openai' package is not installed. Install src/profanity/requirements.txt."
        )

    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        _client = OpenAI(api_key=api_key)

    return _client


def build_prompt(subject: str, description: str) -> str:
    """Render the severity scale into a strict, JSON-only classification prompt."""
    scale_list = ""
    for score in sorted(VALID_SCORES):
        tier = SEVERITY_SCALE[score]
        scale_list += f"\n- {score} = {tier['severity_label']}: {tier['description']}"

    return f"""You are a content safety classifier for a nonprofit help request platform.
Given a help request's subject and description, rate the profanity and abusive content it contains.

Rules:
- Return ONLY an integer severity score from the predefined scale below. Never invent other values.
- Judge the language used, not the severity of the hardship being described. A request about
  violence, abuse or self-harm is NOT profanity; it is someone asking for help. Score it 0
  unless the request itself uses profane or abusive language.
- Profanity aimed at the platform or at volunteers counts the same as any other profanity.
- Return a brief reasoning (1-2 sentences).
- Respond ONLY with a valid JSON object, no extra text.

Severity Scale:
{scale_list}

Help Request:
Subject: {subject}
Description: {description}

Respond in this exact JSON format:
{{
  "severity_score": <integer 0, 1, 2 or 3>,
  "reasoning": "<brief explanation>"
}}"""


def classify_content(subject: str, description: str) -> dict:
    """Score Help Request content for profanity severity.

    Returns {"severity_score": int | None, "reasoning": str, "error": str | None}.
    `severity_score` is None whenever the verdict cannot be trusted; callers
    should pass the result straight to `severity.route`, which turns that into a
    flag-for-review decision.
    """
    subject = (subject or "").strip()
    description = (description or "").strip()

    if not subject and not description:
        # Nothing to classify. Empty content carries no profanity, so this is a
        # genuine CLEAN rather than an undetermined verdict.
        return {
            "severity_score": 0,
            "reasoning": "No subject or description provided.",
            "error": None,
        }

    try:
        response = get_client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": build_prompt(subject, description)}],
            temperature=0,  # deterministic output
            max_tokens=MAX_TOKENS,
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)

        if not isinstance(result, dict):
            raise ValueError(f"Expected a JSON object, got {type(result).__name__}.")

        # Hand the raw value through unvalidated: severity.normalize_score owns
        # deciding whether it is usable, so there is exactly one such rule.
        return {
            "severity_score": result.get("severity_score"),
            "reasoning": str(result.get("reasoning", "")),
            "error": None,
        }

    except Exception as exc:  # noqa: BLE001 - never propagate into the request workflow
        message = f"{type(exc).__name__}: {exc}"
        return {
            "severity_score": None,
            "reasoning": f"Classification failed: {message}",
            "error": message,
        }
