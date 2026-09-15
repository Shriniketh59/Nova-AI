"""
Voice service — local Ollama only. No Gemini, no external APIs.

This module is now a thin wrapper that delegates to:
  - local_orchestrator.orchestrate_full (LLM response)
  - local_tts.synthesize (audio, called by voice WebSocket)

The old Gemini-based generate_voice_reply is replaced by
voice.local_voice_service.generate_voice_reply_local.

Kept here for backward compatibility with any callers that import
from voice_service directly.
"""
import re


LANG_MAP = {
    "auto": ("Auto", "auto"),
    "ta-in": ("Tamil", "ta-IN"),
    "tamil": ("Tamil", "ta-IN"),
    "hi-in": ("Hindi", "hi-IN"),
    "hindi": ("Hindi", "hi-IN"),
    "te-in": ("Telugu", "te-IN"),
    "telugu": ("Telugu", "te-IN"),
    "ml-in": ("Malayalam", "ml-IN"),
    "malayalam": ("Malayalam", "ml-IN"),
    "kn-in": ("Kannada", "kn-IN"),
    "kannada": ("Kannada", "kn-IN"),
    "en-in": ("English", "en-IN"),
    "en-us": ("English", "en-US"),
    "english": ("English", "en-IN"),
}


def detect_script_language(text: str) -> tuple[str, str]:
    """Detect language and BCP-47 tag based on Unicode script characters."""
    if not text:
        return ("English", "en-IN")
    if re.search(r"[\u0B80-\u0BFF]", text):
        return ("Tamil", "ta-IN")
    if re.search(r"[\u0900-\u097F]", text):
        return ("Hindi", "hi-IN")
    if re.search(r"[\u0C00-\u0C7F]", text):
        return ("Telugu", "te-IN")
    if re.search(r"[\u0D00-\u0D7F]", text):
        return ("Malayalam", "ml-IN")
    if re.search(r"[\u0C80-\u0CFF]", text):
        return ("Kannada", "kn-IN")
    return ("English", "en-IN")


def resolve_language(lang_param: str | None, text: str) -> tuple[str, str]:
    """Resolve target language name and BCP-47 code."""
    if lang_param:
        norm = lang_param.strip().lower()
        if norm in LANG_MAP:
            return LANG_MAP[norm]
        for k, v in LANG_MAP.items():
            if k in norm:
                return v
    return detect_script_language(text)


def _clean_spoken_text(text: str) -> str:
    """Strip markdown formatting for TTS."""
    if not text:
        return ""
    cleaned = re.sub(r"\*\*?(.*?)\*\*?", r"\1", text)
    cleaned = re.sub(r"#+\s*", "", cleaned)
    cleaned = re.sub(r"`{1,3}[^`]*`{1,3}", "", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"^[\*\-\+]\s+", "", cleaned, flags=re.MULTILINE)
    if re.search(r"[\u0900-\u0D7F]", cleaned):
        cleaned = re.sub(r"\([A-Za-z0-9\s,\.!?-]+\)", "", cleaned)
    cleaned = cleaned.replace("&", " and ").replace("%", " percent ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


async def generate_voice_reply(
    message: str,
    api_key: str | None = None,
    model_name: str | None = None,
    language: str | None = None,
    lang_code: str | None = None,
    conversation_history: list[dict] | None = None,
) -> dict:
    """
    Generate a voice reply using local Ollama only.
    Signature kept for backward compatibility.
    api_key and model_name parameters are ignored (local only).
    """
    from ..voice.local_voice_service import generate_voice_reply_local
    lang_param = language or lang_code
    lang_name, lang_tag = resolve_language(lang_param, message)

    result = await generate_voice_reply_local(
        message=message,
        conversation_history=conversation_history,
        language=lang_param,
    )

    reply = _clean_spoken_text(result.get("reply", ""))
    resp_lang, resp_tag = detect_script_language(reply)

    return {
        "reply": reply,
        "engine": result.get("engine", "ollama"),
        "model": result.get("model", "llama3.2:3b"),
        "language": lang_name if lang_name != "Auto" else resp_lang,
        "langCode": lang_tag if lang_tag != "auto" else resp_tag,
        "success": result.get("success", False),
    }
