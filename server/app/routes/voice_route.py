"""
Voice routes — local-only, no external AI APIs.

Endpoints:
  POST /api/voice/chat      — text-in voice reply (Ollama LLM, local TTS)
  POST /api/voice/retrieval — Vector DB knowledge retrieval for voice
  GET  /api/voice/config    — voice engine capabilities

Removed:
  - /api/voice/token        (Gemini Live ephemeral token — obsolete)
  - /ws/voice/live          (Gemini Live WebSocket — replaced by /ws/voice/local)
  - /api/settings/gemini    (Gemini key management — not needed)
"""
import re

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core import db
from ..core.config import DEFAULT_USER_ID
from ..core.logger import logger
from ..middleware.auth_middleware import get_optional_user

router = APIRouter()


class VoiceChatRequest(BaseModel):
    message: str
    chatId: str | None = None
    language: str | None = None
    langCode: str | None = None
    history: list[dict] | None = None


class VoiceRetrievalRequest(BaseModel):
    query: str
    chatId: str | None = None


@router.post("/api/voice/chat")
async def voice_chat(body: VoiceChatRequest, current_user: Optional[dict] = Depends(get_optional_user)):
    """
    Text-in, spoken-text-out voice chat endpoint.
    Uses local Ollama (llama3.2:3b) for LLM response.
    The client handles TTS via /ws/voice/local WebSocket or browser.
    """
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message text is required")

    user_id = current_user["id"] if current_user else DEFAULT_USER_ID

    # Fetch recent history from DB if chatId provided
    history = list(body.history or [])
    if body.chatId and not history:
        try:
            chat_check = await db.query(
                "SELECT id FROM chats WHERE id = $1 AND user_id = $2",
                [body.chatId, user_id],
            )
            if chat_check["rowCount"] > 0:
                msg_res = await db.query(
                    "SELECT role, content FROM messages WHERE chat_id = $1 ORDER BY created_at DESC LIMIT 6",
                    [body.chatId],
                )
                history = list(reversed(msg_res["rows"]))
        except Exception:
            pass

    from ..voice.local_voice_service import generate_voice_reply_local
    result = await generate_voice_reply_local(
        message=message,
        chat_id=body.chatId,
        conversation_history=history,
        language=body.language,
    )

    # Persist to chat
    if body.chatId and result.get("success"):
        try:
            await db.query(
                "INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)",
                [body.chatId, "user", message],
            )
            await db.query(
                "INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3)",
                [body.chatId, "ai", result["reply"]],
            )
            await db.query(
                "UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = $1",
                [body.chatId],
            )
        except Exception:
            pass

    return result


@router.post("/api/voice/retrieval")
async def voice_retrieval(body: VoiceRetrievalRequest):
    """Retrieve grounded knowledge from Vector DB for voice tool calls."""
    try:
        from ..retrieval.retrieval_service import retrieve
        from datetime import datetime
        result = await retrieve(
            query=body.query,
            chat_id=body.chatId or "",
            top_k=4,
        )
        context_text = result.get("contextText", "")
        sources = result.get("sources", [])
        current_date = datetime.now().strftime("%A, %B %d, %Y")

        if context_text:
            result_text = f"Knowledge as of {current_date}:\n{context_text[:600]}"
        else:
            result_text = f"No specific knowledge found for '{body.query}'."

        return {"result": result_text, "sources": sources}
    except Exception as e:
        logger.warn(f"Voice retrieval error: {e}")
        return {"result": f"Could not retrieve knowledge: {e}", "sources": []}


@router.get("/api/voice/config")
async def get_voice_config():
    """Return local voice engine capabilities."""
    return {
        "engine": "local",
        "stt": "faster-whisper",
        "tts": "pyttsx3+espeak-ng",
        "llm": "ollama/llama3.2:3b",
        "wsEndpoint": "/ws/voice/local",
        "supportedLanguages": [
            {"code": "en-IN", "name": "English", "native": "English"},
        ],
        "geminiConfigured": False,
        "fallbackEngine": "ollama",
    }
