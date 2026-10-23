from backend.ai_client import chat

SUPPORTED_LANGUAGES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "ar": "Arabic", "zh": "Mandarin Chinese", "pt": "Portuguese",
    "hi": "Hindi", "ja": "Japanese",
}

def translate(text: str, target_lang: str) -> dict:
    if target_lang == "en":
        return {"language": "en", "language_name": "English", "text": text}

    lang_name = SUPPORTED_LANGUAGES.get(target_lang, target_lang)
    prompt = f"""Translate this Premier League football content into {lang_name}.
Preserve energy and excitement. Keep player and team names unchanged.

English:
{text}

{lang_name}:"""

    try:
        translated = chat(prompt, max_tokens=600, temperature=0.3)
        return {"language": target_lang, "language_name": lang_name, "text": translated}
    except Exception:
        return {
            "language": target_lang,
            "language_name": lang_name,
            "text": f"[Translation unavailable — AI service offline]\n\nOriginal: {text}",
        }
