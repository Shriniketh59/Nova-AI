"""
Local Voice Service — text-in, spoken-audio-out.

Combines the Local Orchestrator with Local TTS for the voice chat API endpoint.
Used by /api/voice/chat (HTTP) and /ws/voice/local (WebSocket) routes.

This does NOT use Gemini, Google, or any external API.
"""
import re
import logging
from datetime import datetime, timezone
from typing import Optional

from ..core.logger import logger as nova_logger

_log = logging.getLogger("nova.voice_service")


def _clean_for_tts(text: str) -> str:
    """
    Format text for natural human conversational speech:
    - Strips code blocks and replaces with polite audio phrase
    - Strips markdown formatting, links, and symbols
    - Replaces headings with sentence breaks for natural pause
    - Removes emojis to prevent odd phonetic pronunciations
    - Cleans punctuation and whitespace
    """
    if not text:
        return ""

    t = text
    # Replace code blocks with concise spoken phrase
    t = re.sub(r"```[a-zA-Z0-9_-]*\n?[\s\S]*?```", " The code implementation is provided in your chat. ", t)
    # Inline code backticks
    t = re.sub(r"`([^`]+)`", r"\1", t)
    # Strip HTML tags
    t = re.sub(r"<[^>]+>", "", t)
    # Convert markdown links [Text](URL) -> Text
    t = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", t)
    # Headings -> add sentence termination period so TTS takes a natural pause
    t = re.sub(r"^#+\s*(.+)$", r"\1.", t, flags=re.MULTILINE)
    # Remove bullet markers and list numbers
    t = re.sub(r"^[\*\-\+]\s+", "", t, flags=re.MULTILINE)
    t = re.sub(r"^\d+\.\s+", "", t, flags=re.MULTILINE)
    # Blockquotes
    t = re.sub(r"^>\s*", "", t, flags=re.MULTILINE)
    # Bold / italic / strikethrough
    t = re.sub(r"[*_~]{1,3}(.*?)[*_~]{1,3}", r"\1", t)
    # Conversational replacements
    t = t.replace("&", " and ").replace("%", " percent ").replace("w/", "with ")
    t = re.sub(r"\bi\.e\.,?\s*", "that is, ", t, flags=re.I)
    t = re.sub(r"\be\.g\.,?\s*", "for example, ", t, flags=re.I)
    t = re.sub(r"\betc\.,?\s*", "and so on. ", t, flags=re.I)
    # Strip emojis and supplementary symbol characters
    t = re.sub(r"[\U00010000-\U0010ffff]", "", t)
    t = re.sub(r"[\u2600-\u27ff]", "", t)
    # Collapse multiple dots or spaces
    t = re.sub(r"\.{2,}", ".", t)
    t = re.sub(r"\n+", ". ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


async def generate_voice_reply_local(
    message: str,
    chat_id: Optional[str] = None,
    conversation_history: Optional[list[dict]] = None,
    language: Optional[str] = None,
    voice: Optional[str] = None,
) -> dict:
    """
    Generate a spoken reply using:
    1. Local Orchestrator (Llama 3.2 via Ollama)
    2. Local TTS (pyttsx3 / espeak-ng — fully offline)

    Returns:
        {
            "reply": str,          — cleaned text for TTS
            "engine": "ollama",
            "model": str,
            "success": bool,
        }
    """
    from ..orchestrator.local_orchestrator import orchestrate_full

    try:
        result = await orchestrate_full(
            query=message,
            chat_id=chat_id or "",
            conversation_history=conversation_history,
            is_voice=True,
        )
        raw_text = result.get("text", "")
        cleaned = _clean_for_tts(raw_text)

        if not cleaned:
            cleaned = "I'm here. What can I help you with?"

        from ..core.config import OLLAMA_MODEL
        return {
            "reply": cleaned,
            "engine": "ollama",
            "model": OLLAMA_MODEL,
            "success": True,
            "sources": result.get("sources", []),
        }
    except Exception as e:
        _log.error(f"local voice reply failed: {e}")
        nova_logger.error("voice_service.local_failed", {"error": str(e)})
        return {
            "reply": "I'm having trouble connecting to the local AI model right now.",
            "engine": "none",
            "model": "none",
            "success": False,
            "sources": [],
        }


async def synthesize_speech(text: str, voice: Optional[str] = None) -> tuple[bytes, str]:
    """Convert text to speech bytes + mime-type using the local offline engine.

    Raises TTSUnavailableError when no local speech engine/voice is installed,
    so callers can surface a real error state instead of silent failure.
    """
    from .local_tts import get_tts
    tts = get_tts()
    return await tts.synthesize_with_mime(text, voice=voice)
