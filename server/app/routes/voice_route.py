import os
import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import db
from ..core.config import GEMINI_API_KEY, DEFAULT_USER_ID
from ..services.voice_service import generate_voice_reply

router = APIRouter()


class VoiceChatRequest(BaseModel):
    message: str
    chatId: str | None = None
    apiKey: str | None = None
    model: str | None = None
    language: str | None = None
    langCode: str | None = None


class GeminiKeyRequest(BaseModel):
    apiKey: str


@router.get("/api/voice/config")
async def get_voice_config():
    """Return status of voice assistant engine and active configuration."""
    active_key = os.environ.get("GEMINI_API_KEY") or GEMINI_API_KEY
    if not active_key:
        from dotenv import find_dotenv, load_dotenv
        load_dotenv(find_dotenv(), override=True)
        active_key = os.environ.get("GEMINI_API_KEY")

    has_gemini = bool(active_key)
    return {
        "geminiConfigured": has_gemini,
        "defaultModel": os.environ.get("GEMINI_VOICE_MODEL", "gemini-3.6-flash"),
        "availableModels": ["gemini-3.6-flash", "gemini-3.7-flash", "gemini-flash-latest", "gemini-3.8-flash"],
        "fallbackEngine": "ollama",
        "supportedLanguages": [
            {"code": "en-IN", "name": "English", "native": "English"},
            {"code": "ta-IN", "name": "Tamil", "native": "தமிழ்"},
            {"code": "hi-IN", "name": "Hindi", "native": "हिन्दी"},
            {"code": "te-IN", "name": "Telugu", "native": "తెలుగు"},
            {"code": "ml-IN", "name": "Malayalam", "native": "മലയാളം"},
            {"code": "kn-IN", "name": "Kannada", "native": "ಕನ್ನಡ"},
        ],
    }


@router.post("/api/settings/gemini")
async def save_gemini_key(body: GeminiKeyRequest):
    """Save or update Gemini API key in runtime environment and .env file."""
    key = body.apiKey.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key is required")

    os.environ["GEMINI_API_KEY"] = key

    # Persist to .env file in workspace root
    env_path = os.path.join(os.path.dirname(__file__), "../../../.env")
    try:
        content = ""
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()

        if re.search(r"^GEMINI_API_KEY=.*", content, re.MULTILINE):
            new_content = re.sub(r"^GEMINI_API_KEY=.*", f"GEMINI_API_KEY={key}", content, flags=re.MULTILINE)
        else:
            new_content = content + f"\nGEMINI_API_KEY={key}\n"

        with open(env_path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception:
        pass  # In-memory update still works even if .env write fails

    return {"status": "ok", "message": "Gemini API key saved successfully"}


@router.post("/api/voice/chat")
async def voice_chat(body: VoiceChatRequest):
    """Process a voice conversation turn, fetch chat context if available, and persist messages."""
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message text is required")

    history = []
    if body.chatId:
        try:
            # Check chat exists
            chat_check = await db.query(
                "SELECT id FROM chats WHERE id = $1 AND user_id = $2",
                [body.chatId, DEFAULT_USER_ID],
            )
            if chat_check["rowCount"] > 0:
                # Fetch recent messages for conversational context
                msg_res = await db.query(
                    "SELECT role, content FROM messages WHERE chat_id = $1 ORDER BY created_at DESC LIMIT 6",
                    [body.chatId],
                )
                history = list(reversed(msg_res["rows"]))
        except Exception:
            pass

    # Call Gemini (or Ollama fallback)
    result = await generate_voice_reply(
        message=message,
        api_key=body.apiKey,
        model_name=body.model,
        language=body.language,
        lang_code=body.langCode,
        conversation_history=history,
    )

    # Persist to chat if chatId provided
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
