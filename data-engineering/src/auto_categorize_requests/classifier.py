import json
import logging
import os
from dataclasses import dataclass
from typing import Optional, Tuple, List

import numpy as np
from openai import OpenAI

from .categories_config import CATEGORY_OPTIONS, UNCATEGORIZED, CategoryOption

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is not set; LLM/embeddings will fail at runtime.")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

EMBEDDING_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-4.1-mini"

_category_embeddings: Optional[np.ndarray] = None
_category_labels: Optional[List[CategoryOption]] = None


@dataclass
class ClassificationResult:
    category: str
    subcategory: str
    confidence: float
    reasoning: str


def _normalize_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _get_category_embeddings() -> Tuple[np.ndarray, List[CategoryOption]]:
    global _category_embeddings, _category_labels
    if _category_embeddings is not None and _category_labels is not None:
        return _category_embeddings, _category_labels

    if client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    _category_labels = CATEGORY_OPTIONS
    labels = [opt["canonical_label"] for opt in _category_labels]

    logger.info("Computing embeddings for %d category options", len(labels))
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=labels,
    )
    vectors = [item.embedding for item in response.data]
    _category_embeddings = np.array(vectors, dtype=np.float32)
    return _category_embeddings, _category_labels


def _embed_text(text: str) -> np.ndarray:
    if client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[text],
    )
    return np.array(response.data[0].embedding, dtype=np.float32)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_norm = a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-8)
    b_norm = b / (np.linalg.norm(b, axis=-1, keepdims=True) + 1e-8)
    return np.dot(a_norm, b_norm.T)


def _keyword_rule_based(text: str) -> Optional[ClassificationResult]:
    if not text:
        return None

    shelter_keywords = [
        "homeless",
        "on the streets",
        "no place to stay",
        "nowhere to sleep",
        "emergency shelter",
        "place to stay tonight",
        "lost my apartment",
    ]
    if any(kw in text for kw in shelter_keywords):
        return ClassificationResult(
            category="Shelter",
            subcategory="Emergency Shelter",
            confidence=0.9,
            reasoning="Text describes immediate loss of housing or need for a safe place to stay.",
        )

    food_keywords = [
        "hungry",
        "food",
        "meals",
        "food assistance",
        "grocery",
        "food pantry",
        "food vouchers",
    ]
    if any(kw in text for kw in food_keywords):
        return ClassificationResult(
            category="Food",
            subcategory="Food Pantry",
            confidence=0.8,
            reasoning="Text mentions hunger or need for food assistance.",
        )

    employment_keywords = [
        "job",
        "employment",
        "work",
        "resume",
        "cv",
        "looking for work",
        "lost my job",
    ]
    if any(kw in text for kw in employment_keywords):
        return ClassificationResult(
            category="Employment",
            subcategory="Job Search Assistance",
            confidence=0.8,
            reasoning="Text references employment, jobs, or job search support.",
        )

    health_keywords = [
        "doctor",
        "hospital",
        "medical",
        "health",
        "clinic",
        "medicine",
        "medication",
        "mental health",
        "therapy",
        "counseling",
    ]
    if any(kw in text for kw in health_keywords):
        return ClassificationResult(
            category="Health",
            subcategory="Medical Assistance",
            confidence=0.8,
            reasoning="Text mentions medical or health-related needs.",
        )

    return None


def _embedding_based_classification(text: str) -> Optional[ClassificationResult]:
    if not text:
        return None

    try:
        cat_embeddings, labels = _get_category_embeddings()
        query_vec = _embed_text(text)
        sims = _cosine_similarity(query_vec[np.newaxis, :], cat_embeddings)[0]
        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])
        best_option = labels[best_idx]

        if best_sim < 0.35:
            confidence = 0.3
        elif best_sim < 0.5:
            confidence = 0.5
        else:
            confidence = min(0.95, 0.7 + (best_sim - 0.5))

        reasoning = (
            f"Embedding similarity between the request and category "
            f"'{best_option['canonical_label']}' was {best_sim:.2f}."
        )
        return ClassificationResult(
            category=best_option["category"],
            subcategory=best_option["subcategory"],
            confidence=confidence,
            reasoning=reasoning,
        )
    except Exception as exc:
        logger.error("Embedding-based classification failed: %s", exc, exc_info=True)
        return None


def _llm_fallback_classification(text: str) -> Optional[ClassificationResult]:
    if not text or client is None:
        return None

    try:
        options = [
            {"category": opt["category"], "subcategory": opt["subcategory"]}
            for opt in CATEGORY_OPTIONS
        ]
        system_prompt = (
            "You classify help requests into predefined categories.\n"
            "You will receive a request text and a list of valid (category, subcategory) pairs.\n\n"
            "Rules:\n"
            "- You MUST choose exactly one category and one subcategory from the provided list.\n"
            '- If no option fits reasonably, use category "Uncategorized" and subcategory "Uncategorized".\n'
            "- Return a JSON object with fields: category, subcategory, confidence (0–1), reasoning.\n"
            "- Keep reasoning to 1–2 short sentences.\n"
            "- Do NOT invent new categories or subcategories.\n"
        )
        user_payload = {
            "request_text": text,
            "options": options,
        }

        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)

        category = str(data.get("category") or "").strip()
        subcategory = str(data.get("subcategory") or "").strip()
        confidence = float(data.get("confidence", 0.5))
        reasoning = str(data.get("reasoning") or "").strip()

        valid = next(
            (
                opt
                for opt in CATEGORY_OPTIONS
                if opt["category"] == category and opt["subcategory"] == subcategory
            ),
            None,
        )
        if not valid:
            logger.warning(
                "LLM returned invalid category/subcategory: %s / %s; falling back to Uncategorized",
                category,
                subcategory,
            )
            category = UNCATEGORIZED["category"]
            subcategory = UNCATEGORIZED["subcategory"]

        confidence = max(0.0, min(1.0, confidence))
        if not reasoning:
            reasoning = "LLM-based classification using the predefined category list."

        return ClassificationResult(
            category=category,
            subcategory=subcategory,
            confidence=confidence,
            reasoning=reasoning,
        )
    except Exception as exc:
        logger.error("LLM fallback classification failed: %s", exc, exc_info=True)
        return None


def classify_help_request(
    subject: Optional[str],
    description: Optional[str],
) -> ClassificationResult:
    text = _normalize_text((subject or "") + " " + (description or ""))

    if not text:
        return ClassificationResult(
            category=UNCATEGORIZED["category"],
            subcategory=UNCATEGORIZED["subcategory"],
            confidence=0.0,
            reasoning="No subject or description provided.",
        )

    rule_result = _keyword_rule_based(text)
    if rule_result and rule_result.confidence >= 0.8:
        return rule_result

    embed_result = _embedding_based_classification(text)

    if embed_result and embed_result.confidence >= 0.7:
        return embed_result

    llm_result = _llm_fallback_classification(text)

    if llm_result and (not embed_result or llm_result.confidence >= embed_result.confidence):
        return llm_result

    if embed_result:
        return embed_result

    return ClassificationResult(
        category=UNCATEGORIZED["category"],
        subcategory=UNCATEGORIZED["subcategory"],
        confidence=0.2,
        reasoning="Unable to confidently match request to any category.",
    )
