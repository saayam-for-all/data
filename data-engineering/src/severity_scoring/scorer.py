import re

SEVERITY_NORMAL = 0
SEVERITY_PROFANITY = 1
SEVERITY_DEPRESSIVE = 2
SEVERITY_THREAT = 3

PROFANITY_WORDS = ["damn", "crap", "bullshit", "asshole"]
DEPRESSIVE_PHRASES = ["want to die", "kill myself", "end my life", "no reason to live", "can't go on", "can't do this anymore", "better off dead", "want to disappear", "don't want to live", "end it all"]
THREAT_PHRASES = ["i will kill you", "i will hurt you", "i will beat you", "you will pay for this", "i will find you"]

def _contains(text, phrases):
    for phrase in phrases:
        if re.search(r"\b" + re.escape(phrase) + r"\b", text):
            return True
    return False

def score_text(text):
    cleaned = (text or "").lower().replace("’", "'")
    scores = []

    if _contains(cleaned, PROFANITY_WORDS):
        scores.append(SEVERITY_PROFANITY)
    if _contains(cleaned, DEPRESSIVE_PHRASES):
        scores.append(SEVERITY_DEPRESSIVE)
    if _contains(cleaned, THREAT_PHRASES):
        scores.append(SEVERITY_THREAT)

    if not scores:
        scores.append(SEVERITY_NORMAL)

    return {"severity_scores": scores, "highest": max(scores)}