import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from src.categorizer.categories import CATEGORIES

load_dotenv()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

def build_prompt(subject: str, description: str) -> str:
    category_list = ""
    for cat, subcats in CATEGORIES.items():
        if subcats:
            category_list += f"\n- {cat}: {', '.join(subcats)}"
        else:
            category_list += f"\n- {cat}: (no subcategories — use as fallback only)"

    return f"""You are a classifier for a nonprofit help request platform.
Given a help request's subject and description, classify it into the most appropriate category and subcategory from the predefined list below.

Rules:
- ONLY return values from the predefined list. Never invent new ones.
- If no category fits well, use "General" with subcategory "General".
- Return a confidence score between 0 and 1.
- Return a brief reasoning (1-2 sentences).
- Respond ONLY with a valid JSON object, no extra text.

Predefined Categories:
{category_list}

Help Request:
Subject: {subject}
Description: {description}

Respond in this exact JSON format:
{{
  "category": "<category>",
  "subcategory": "<subcategory>",
  "confidence": <float between 0 and 1>,
  "reasoning": "<brief explanation>"
}}"""


def classify_request(subject: str, description: str) -> dict:
    if not subject and not description:
        return {
            "category": "General",
            "subcategory": "General",
            "confidence": 0.0,
            "reasoning": "No subject or description provided."
        }

    prompt = build_prompt(subject or "", description or "")

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",  # cheap and fast
            messages=[{"role": "user", "content": prompt}],
            temperature=0,          # deterministic output
            max_tokens=200
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)

        # Validate category exists
        cat = result.get("category", "General")
        subcat = result.get("subcategory", "General")

        if cat not in CATEGORIES:
            cat = "General"
            subcat = "General"
        elif subcat not in CATEGORIES.get(cat, []) and cat != "General":
            subcat = CATEGORIES[cat][0] if CATEGORIES[cat] else "General"

        return {
            "category": cat,
            "subcategory": subcat,
            "confidence": float(result.get("confidence", 0.5)),
            "reasoning": result.get("reasoning", "")
        }

    except Exception as e:
        return {
            "category": "General",
            "subcategory": "General",
            "confidence": 0.0,
            "reasoning": f"Classification failed: {str(e)}"
        }