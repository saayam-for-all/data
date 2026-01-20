from deep_translator import GoogleTranslator
from langdetect import detect, DetectorFactory, LangDetectException
from groq import Groq

# ----------------------------
# Config
# ----------------------------
DetectorFactory.seed = 0

translator = GoogleTranslator(target="en")
groq_client = Groq(api_key="ENTER API KEY")  # expects GROQ_API_KEY in env

# ----------------------------
# Detect Language
# ----------------------------
def detect_language(text):
    return detect(text)

# ----------------------------
# Python-based translation
# ----------------------------
def python_translate(text: str) -> str:
    if not text or not text.strip():
        return text

    try:
        lang = detect_language(text)
    except LangDetectException:
        return text

    if lang == "en":
        return text

    try:
        return translator.translate(text)
    except Exception:
        return text

# ----------------------------
# Translation quality check
# ----------------------------
def is_translation_satisfactory(original: str, translated: str) -> bool:
    if not translated:
        return False

    if translated.strip() == original.strip():
        return False

    # If non-ASCII chars remain, likely untranslated content
    if any(ord(c) > 128 for c in translated):
        return False

    # Too short compared to original → suspicious
    if len(translated.split()) < max(2, len(original.split()) // 2):
        return False

    return True

# ----------------------------
# Groq AI fallback
# ----------------------------
def groq_translate(text: str) -> str:
    completion = groq_client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a translation engine.\n"
                    "Rules:\n"
                    "- Translate ALL non-English content into English\n"
                    "- Preserve existing English text exactly\n"
                    "- Handle mixed languages, slang, typos, emojis\n"
                    "- Do NOT explain anything\n"
                    "- Output ONLY the final translated text"
                )
            },
            {
                "role": "user",
                "content": text
            }
        ],
        temperature=0,
        top_p=1,
        reasoning_effort="medium",
        stream=False,
        max_completion_tokens=1024
    )

    return completion.choices[0].message.content.strip()

# ----------------------------
# Final smart translator
# ----------------------------
def smart_translate_to_english(text: str) -> str:
    python_result = python_translate(text)

    if is_translation_satisfactory(text, python_result):
        return python_result

    # Fallback to Groq only if needed
    try:
        return groq_translate(text)
    except Exception:
        return python_result

# ----------------------------
# Manual test
# ----------------------------
if __name__ == "__main__":
    samples = [
        "Hola, ¿cómo estás? Espero que tengas un buen día.",
        "Hola bro, kal meeting hai 😅 but deadline tight hai",
        "Bonjour this API est vraiment cool 🚀",
        "bhai pls fix this bug asap 😭 c'est urgent!!!",
        "Hello, how are you?"
    ]

    for s in samples:
        print("INPUT :", s)
        print("OUTPUT:", smart_translate_to_english(s))
        print("-" * 60)