import re

import httpx

from ..core.config import OLLAMA_URL, OLLAMA_MODEL
from .base_agent import BaseAgent

SUPPORTED_LANGUAGES = [
    "English", "Tamil", "Telugu", "Kannada", "Malayalam", "Hindi", "Bengali",
    "Marathi", "Gujarati", "Punjabi", "Urdu", "Arabic", "French", "German",
    "Spanish", "Japanese", "Korean", "Chinese", "Russian", "Portuguese",
]

SYSTEM_PROMPT = f"""You are Nova AI Multilingual Translation Engine.

Your only task is accurate translation between languages.

Supported Languages: {', '.join(SUPPORTED_LANGUAGES)}.

Instructions:
1. Automatically detect the source language.
2. Translate into the requested target language.
3. Preserve: Meaning, Context, Tone, Names, Numbers, Dates, Technical terms.
4. Never: Summarize, Explain, Add information, Remove information, Answer the content.
5. If the input is a word, return the translated word only. If a sentence, return the translated sentence only. If a paragraph, return the translated paragraph only.
6. Maintain original formatting.
7. For programming content: keep code unchanged, translate comments only if requested.
8. If translation is ambiguous, choose the most natural and commonly used translation.

Output Format (exactly, no extra text):
Detected Language: <language>

Translation: <translated text>"""

_DETECTED_RE = re.compile(r"Detected Language:\s*(.+)", re.I)
_TRANSLATION_RE = re.compile(r"Translation:\s*([\s\S]*)", re.I)


def _build_user_message(target_language: str, text: str) -> str:
    return f"Translate to {target_language}:\n{text}"


def _parse_translation_output(raw: str) -> dict:
    detected_match = _DETECTED_RE.search(raw)
    translation_match = _TRANSLATION_RE.search(raw)

    if translation_match:
        return {
            "detectedLanguage": detected_match.group(1).strip() if detected_match else None,
            "translation": translation_match.group(1).strip(),
        }

    if detected_match:
        after_detected = raw[raw.index(detected_match.group(0)) + len(detected_match.group(0)):].strip()
        return {"detectedLanguage": detected_match.group(1).strip(), "translation": after_detected}

    return {"detectedLanguage": None, "translation": raw.strip()}


class TranslationAgent(BaseAgent):
    def __init__(self):
        super().__init__("TranslationAgent")

    async def run(self, text: str, context: dict | None = None) -> dict:
        context = context or {}
        target_language = context.get("targetLanguage")
        if not target_language or target_language not in SUPPORTED_LANGUAGES:
            return {
                "success": False,
                "output": None,
                "error": f"targetLanguage must be one of: {', '.join(SUPPORTED_LANGUAGES)}",
            }

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                res = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": _build_user_message(target_language, text)},
                        ],
                        "stream": False,
                        "options": {"temperature": 0.1, "num_predict": 512},
                    },
                )
                if res.status_code >= 400:
                    raise RuntimeError(f"LLM request failed with status {res.status_code}")

                data = res.json()
                raw = (data.get("message") or {}).get("content", "")
                parsed = _parse_translation_output(raw)

                return {
                    "success": True,
                    "output": {**parsed, "targetLanguage": target_language},
                }
        except Exception as err:
            return {"success": False, "output": None, "error": str(err)}
