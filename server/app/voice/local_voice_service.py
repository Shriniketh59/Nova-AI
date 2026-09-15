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
    """Strip markdown/code so espeak-ng speaks clean sentences."""
    if not text:
        return ""
    t = re.sub(r"\*\*?(.*?)\*\*?", r"\1", text)
    t = re.sub(r"#+\s*", "", t)
    t = re.sub(r"`{1,3}[^`]*`{1,3}", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", t)
    t = re.sub(r"^[\*\-\+]\s+", "", t, flags=re.MULTILINE)
    t = t.replace("&", " and ").replace("%", " percent ")
    # Collapse blank lines
    t = re.sub(r"\n{2,}", ". ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


async def generate_voice_reply_local(
    message: str,
    chat_id: Optional[str] = None,
    conversation_history: Optional[list[dict]] = None,
    language: Optional[str] = None,
) -> dict:
    """
    Generate a spoken reply using:
    1. Local Orchestrator (Llama 3.2 via Ollama)
    2. Local TTS (pyttsx3 + espeak-ng)

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


async def synthesize_speech(text: str) -> bytes:
    """Convert text to WAV bytes using local pyttsx3/espeak-ng TTS."""
    from .local_tts import get_tts
    tts = get_tts()
    return await tts.synthesize(text)
