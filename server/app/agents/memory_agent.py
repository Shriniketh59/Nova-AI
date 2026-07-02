import json
import re

from ..core import db
from ..core.config import DEFAULT_USER_ID
from ..core.logger import logger
from ..rag import generate_embedding, cosine_similarity
from .base_agent import BaseAgent

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for",
    "and", "or", "with", "what", "how", "do", "does", "i", "you", "my",
}

MEMORY_TRIGGER_RE = re.compile(
    r"\b(remember|my name is|i prefer|i like|i'm working on|i am working on|call me|always (use|write|respond)|never (use|write))\b",
    re.I,
)

# Which memory `type` a triggering message should be filed under (checked in
# order — first match wins). Falls back to "fact" for anything else that
# tripped MEMORY_TRIGGER_RE.
PROJECT_TRIGGER_RE = re.compile(r"\bi'?m working on\b|\bi am working on\b|\bthis project\b", re.I)
PREFERENCE_TRIGGER_RE = re.compile(r"\bi prefer\b|\bi like\b|\balways (use|write|respond)\b|\bnever (use|write)\b|\bcall me\b", re.I)


def _classify_memory_type(user_message: str) -> str:
    if PROJECT_TRIGGER_RE.search(user_message):
        return "project"
    if PREFERENCE_TRIGGER_RE.search(user_message):
        return "preference"
    return "fact"

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


class MemoryAgent(BaseAgent):
    """Reuses the existing `messages` table as the memory store. Retrieval is
    keyword-overlap, not embeddings — avoids an extra Ollama round-trip on
    every query, keeping memory lookup near-free."""

    def __init__(self):
        super().__init__("MemoryAgent")

    async def run(self, query: str, context: dict | None = None) -> dict:
        context = context or {}
        chat_id = context.get("chatId")
        exclude_message_id = context.get("excludeMessageId")
        top_k = context.get("topK", 3)
        try:
            memories = await self.get_relevant_memories(chat_id, query, exclude_message_id, top_k)
            return {"success": True, "output": {"memories": memories}}
        except Exception as err:
            return {"success": False, "output": {"memories": []}, "error": str(err)}

    async def get_relevant_memories(self, chat_id, query, exclude_message_id=None, top_k=3) -> list[str]:
        try:
            short_term = await self._short_term_memories(chat_id, query, exclude_message_id, top_k)
        except Exception:
            short_term = []
        try:
            project_term = await self._project_memories(chat_id, query, top_k) if chat_id else []
        except Exception:
            project_term = []
        try:
            long_term = await self._long_term_memories(query, top_k)
        except Exception:
            long_term = []
        # Short-term (this conversation) ranks first, then project-scoped
        # facts/preferences, then user-global long-term memory.
        return [*short_term, *project_term, *long_term][: top_k + 2]

    async def _short_term_memories(self, chat_id, query, exclude_message_id, top_k) -> list[str]:
        if not chat_id:
            return []

        res = await db.query("SELECT * FROM messages WHERE chat_id = $1 ORDER BY created_at ASC", [chat_id])
        past_user_messages = [m for m in res["rows"] if m["role"] == "user" and m["id"] != exclude_message_id]
        if not past_user_messages:
            return []

        query_terms = {t for t in _tokenize(query) if t not in STOPWORDS and len(t) > 1}
        if not query_terms:
            return []

        scored = []
        for m in past_user_messages:
            msg_terms = _tokenize(m["content"])
            overlap = sum(1 for t in msg_terms if t in query_terms)
            if overlap > 0:
                scored.append({"content": m["content"], "createdAt": m["created_at"], "score": overlap})

        scored.sort(key=lambda m: (m["score"], m["createdAt"]), reverse=True)
        return [m["content"] for m in scored[:top_k]]

    async def _project_memories(self, chat_id, query, top_k=3) -> list[str]:
        """Semantic similarity against user_memory rows scoped to this chat
        (type='project') — facts/decisions specific to the project/thread
        the user is currently in, distinct from user-global preferences."""
        res = await db.query(
            "SELECT * FROM user_memory WHERE user_id = $1 AND chat_id = $2 AND type = 'project'",
            [DEFAULT_USER_ID, chat_id],
        )
        if not res["rows"]:
            return []

        query_vector = await generate_embedding(query)
        scored = [
            {"content": m["content"], "score": cosine_similarity(query_vector, m["embedding"])} for m in res["rows"]
        ]
        scored = [m for m in scored if m["score"] >= 0.5]
        scored.sort(key=lambda m: m["score"], reverse=True)
        return [m["content"] for m in scored[:top_k]]

    async def _long_term_memories(self, query, top_k=3) -> list[str]:
        """Semantic similarity against user_memory, which holds facts/preferences
        extracted across all chats (type='fact' or 'preference', chat_id NULL
        or any — user-global, not scoped to the current project/thread)."""
        res = await db.query(
            "SELECT * FROM user_memory WHERE user_id = $1 AND type IN ('fact', 'preference')",
            [DEFAULT_USER_ID],
        )
        if not res["rows"]:
            return []

        query_vector = await generate_embedding(query)
        scored = [
            {"content": m["content"], "score": cosine_similarity(query_vector, m["embedding"])} for m in res["rows"]
        ]
        scored = [m for m in scored if m["score"] >= 0.5]
        scored.sort(key=lambda m: m["score"], reverse=True)
        return [m["content"] for m in scored[:top_k]]

    async def extract_memory(self, user_id: str, chat_id: str, user_message: str):
        """Bounded extraction: only fires when the user's message looks like
        it states a durable fact/preference/project-context (heuristic gate).
        Routes into the fact/preference/project tier based on phrasing, and
        scopes project-type memories to this chat_id."""
        if not MEMORY_TRIGGER_RE.search(user_message):
            return

        try:
            memory_type = _classify_memory_type(user_message)
            embedding = await generate_embedding(user_message)
            row_chat_id = chat_id if memory_type == "project" else None
            await db.query(
                "INSERT INTO user_memory (user_id, chat_id, type, content, embedding) VALUES ($1, $2, $3, $4, $5)",
                [user_id, row_chat_id, memory_type, user_message, json.dumps(embedding)],
            )
        except Exception as err:
            logger.warn("Memory extraction failed (non-fatal)", {"error": str(err)})


memory_agent = MemoryAgent()
