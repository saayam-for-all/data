from deep_translator import GoogleTranslator
from langdetect import detect

def detect_language(text):
    """Detects the language of the input text."""
    return detect(text)

def translate_to_english(text):
    """Translates the given text to English."""
    detected_language = detect_language(text)
    
    # If the text is already in English, return it as is
    if detected_language == 'en':
        return text
    
    # Translate text to English
    translation = GoogleTranslator(source=detected_language, target='en').translate(text)
    return translation
