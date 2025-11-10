from fastapi import FastAPI, HTTPException
from googletrans import Translator

app = FastAPI()
translator = Translator()

@app.get("/")
def home():
    return {"message": "Language Detection and Translation API is running"}

@app.post("/translate")
def translate_text(data: dict):
    try:
        text = data.get("text", "")
        if not text.strip():
            raise HTTPException(status_code=400, detail="Text cannot be empty")

        detection = translator.detect(text)
        translated = translator.translate(text, dest='en')

        return {
            "original_text": text,
            "detected_language": detection.lang,
            "translated_text": translated.text
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
