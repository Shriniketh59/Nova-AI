import json
import re
import time
from datetime import datetime, timezone

from ..core import db
from ..core.config import DEFAULT_USER_ID
from ..core.logger import logger
from ..rag import generate_embedding, cosine_similarity
from ..utils.query_regularizer import regularize_query, fuzzy_token_overlap
from .base_agent import BaseAgent

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for",
    "and", "or", "with", "what", "how", "do", "does", "i", "you", "my",
}

MEMORY_TRIGGER_RE = re.compile(
    r"\b(remember|my name is|i prefer|i like|i'm working on|i am working on|call me|always (use|write|respond)|never (use|write))\b",
    re.I,
)

# Which memory `type` a triggering message should be filed under
PROJECT_TRIGGER_RE = re.compile(r"\bi'?m working on\b|\bi am working on\b|\bthis project\b", re.I)
PREFERENCE_TRIGGER_RE = re.compile(r"\bi prefer\b|\bi like\b|\balways (use|write|respond)\b|\bnever (use|write)\b|\bcall me\b", re.I)

# Topic extraction patterns for superseding older memories
NAME_TOPIC_RE = re.compile(r"\b(my name is|call me|i am|name)\b", re.I)
LANGUAGE_TOPIC_RE = re.compile(r"\b(python|java|javascript|typescript|c\+\+|rust|golang|go|ruby|sql)\b", re.I)
PROJECT_TOPIC_RE = re.compile(r"\b(working on|project|building|developing)\b", re.I)


def _classify_memory_type(user_message: str) -> str:
    if PROJECT_TRIGGER_RE.search(user_message):
        return "project"
    if PREFERENCE_TRIGGER_RE.search(user_message):
        return "preference"
    return "fact"


def _extract_memory_topic(user_message: str) -> str:
    """Extract a topic tag to identify memory domain for superseding."""
    msg = user_message.lower()
    if NAME_TOPIC_RE.search(msg) and ("name" in msg or "call me" in msg):
        return "user_name"
    if "prefer" in msg or "like" in msg:
        lang_match = LANGUAGE_TOPIC_RE.search(msg)
        if lang_match:
            return f"preference_lang_{lang_match.group(1)}"
        return "preference_general"
    if PROJECT_TOPIC_RE.search(msg):
        return "project_context"
    return "general_fact"


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _parse_timestamp(ts) -> float:
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            # Handle ISO string e.g. 2026-09-17T18:50:54Z
            clean_ts = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(clean_ts).timestamp()
        except Exception:
            pass
    return time.time()


class MemoryAgent(BaseAgent):
    """
    Intelligent memory agent with recency boosting, automatic superseding of
    obsolete/conflicting facts, and spelling-tolerant memory retrieval.
    """

    def __init__(self):
        super().__init__("MemoryAgent")

    async def run(self, query: str, context: dict | None = None) -> dict:
        context = context or {}
        chat_id = context.get("chatId")
        exclude_message_id = context.get("excludeMessageId")
        user_id = context.get("userId") or DEFAULT_USER_ID
        top_k = context.get("topK") or context.get("top_k") or 3
        try:
            memories = await self.get_relevant_memories(chat_id, query, exclude_message_id, top_k, user_id=user_id)
            return {"success": True, "output": {"memories": memories}}
        except Exception as err:
            logger.error("memory_agent.run_failed", {"error": str(err)})
            return {"success": False, "output": {"memories": []}, "error": str(err)}

    async def get_relevant_memories(
        self,
        chat_id: str | None,
        query: str,
        exclude_message_id=None,
        top_k: int = 3,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[str]:
        """
        Retrieves relevant active memories, prioritizing:
        1. Conversation messages (short-term)
        2. Scoped project memories (with recency boost)
        3. Global durable facts & preferences (with recency boost & stale exclusion)
        """
        try:
            short_term = await self._short_term_memories(chat_id, query, exclude_message_id, top_k)
        except Exception as err:
            logger.warn(f"short_term_memories error: {err}")
            short_term = []

        try:
            project_term = await self._project_memories(chat_id, query, top_k, user_id=user_id) if chat_id else []
        except Exception as err:
            logger.warn(f"project_memories error: {err}")
            project_term = []

        try:
            long_term = await self._long_term_memories(query, top_k, user_id=user_id)
        except Exception as err:
            logger.warn(f"long_term_memories error: {err}")
            long_term = []

        # Deduplicate results preserving order
        combined = []
        seen = set()
        for m in [*short_term, *project_term, *long_term]:
            norm_m = m.strip().lower()
            if norm_m not in seen:
                seen.add(norm_m)
                combined.append(m)

        return combined[: top_k + 2]

    async def _short_term_memories(self, chat_id, query, exclude_message_id, top_k) -> list[str]:
        if not chat_id:
            return []

        res = await db.query("SELECT * FROM messages WHERE chat_id = $1 ORDER BY created_at DESC LIMIT 30", [chat_id])
        past_user_messages = [m for m in res["rows"] if m["role"] == "user" and m["id"] != exclude_message_id]
        if not past_user_messages:
            return []

        # Tokenize query with spelling tolerance
        reg = regularize_query(query)
        raw_terms = {t for t in _tokenize(query) if t not in STOPWORDS and len(t) > 1}
        norm_terms = {t for t in reg.get("normalized_tokens", []) if t not in STOPWORDS and len(t) > 1}
        query_terms = raw_terms | norm_terms

        if not query_terms:
            return []

        scored = []
        for m in past_user_messages:
            msg_terms = set(_tokenize(m.get("content", "")))
            overlap_set = fuzzy_token_overlap(query_terms, msg_terms)
            if overlap_set:
                score = len(overlap_set)
                created_ts = _parse_timestamp(m.get("created_at"))
                scored.append({
                    "content": m["content"],
                    "createdAt": created_ts,
                    "score": score,
                })

        # Sort by match score first, then newest timestamp first
        scored.sort(key=lambda m: (m["score"], m["createdAt"]), reverse=True)
        return [m["content"] for m in scored[:top_k]]

    async def _project_memories(self, chat_id, query, top_k=3, user_id=DEFAULT_USER_ID) -> list[str]:
        """Semantic similarity against user_memory scoped to this chat (is_active=true)."""
        res = await db.query(
            "SELECT * FROM user_memory WHERE user_id = $1 AND chat_id = $2 AND type = 'project' AND is_active = true",
            [user_id, chat_id],
        )
        if not res["rows"]:
            return []

        reg = regularize_query(query)
        query_vector = await generate_embedding(reg["normalized_query"])
        now_ts = time.time()

        scored = []
        for m in res["rows"]:
            raw_sim = cosine_similarity(query_vector, m["embedding"])
            if raw_sim < 0.45:
                continue
            # Recency factor: within 7 days = 1.0, fading to 0.7
            m_time = _parse_timestamp(m.get("updated_at") or m.get("created_at"))
            age_days = max(0.0, (now_ts - m_time) / 86400.0)
            recency_weight = max(0.7, 1.0 - (age_days / 60.0))
            composite_score = (raw_sim * 0.85) + (recency_weight * 0.15)
            scored.append({
                "content": m["content"],
                "score": composite_score,
                "timestamp": m_time,
            })

        scored.sort(key=lambda m: (m["score"], m["timestamp"]), reverse=True)
        return [m["content"] for m in scored[:top_k]]

    async def _long_term_memories(self, query, top_k=3, user_id=DEFAULT_USER_ID) -> list[str]:
        """
        Semantic similarity against active long-term user memories.
        Newer memories receive a recency boost to ensure that updated user
        facts naturally supersede older stale ones.
        """
        res = await db.query(
            "SELECT * FROM user_memory WHERE user_id = $1 AND type IN ('fact', 'preference') AND is_active = true",
            [user_id],
        )
        if not res["rows"]:
            return []

        reg = regularize_query(query)
        query_vector = await generate_embedding(reg["normalized_query"])
        now_ts = time.time()

        scored = []
        for m in res["rows"]:
            raw_sim = cosine_similarity(query_vector, m["embedding"])
            if raw_sim < 0.45:
                continue
            m_time = _parse_timestamp(m.get("updated_at") or m.get("created_at"))
            age_days = max(0.0, (now_ts - m_time) / 86400.0)
            recency_weight = max(0.7, 1.0 - (age_days / 60.0))
            composite_score = (raw_sim * 0.85) + (recency_weight * 0.15)
            scored.append({
                "id": m.get("id"),
                "content": m["content"],
                "topic": m.get("topic"),
                "score": composite_score,
                "timestamp": m_time,
            })

        scored.sort(key=lambda m: (m["score"], m["timestamp"]), reverse=True)
        return [m["content"] for m in scored[:top_k]]

    async def extract_memory(self, user_id: str, chat_id: str | None, user_message: str):
        """
        Extracts durable memory and automatically supersedes older, conflicting
        memories on the same topic or with high semantic overlap.
        """
        if not MEMORY_TRIGGER_RE.search(user_message):
            return

        try:
            memory_type = _classify_memory_type(user_message)
            topic = _extract_memory_topic(user_message)
            embedding = await generate_embedding(user_message)
            row_chat_id = chat_id if memory_type == "project" else None

            # 1. Fetch active existing memories for this user to check for conflicts
            existing_res = await db.query(
                "SELECT id, content, embedding, topic FROM user_memory WHERE user_id = $1 AND is_active = true",
                [user_id],
            )
            to_deactivate = []

            for row in existing_res.get("rows", []):
                old_id = row.get("id")
                old_topic = row.get("topic")
                old_emb = row.get("embedding")
                if isinstance(old_emb, str):
                    try:
                        old_emb = json.loads(old_emb)
                    except Exception:
                        old_emb = []

                # Topic match (e.g. updating name or specific language preference)
                if topic != "general_fact" and old_topic == topic:
                    to_deactivate.append(old_id)
                    continue

                # High semantic similarity conflict (e.g., both discussing favorite editor or name)
                if old_emb:
                    sim = cosine_similarity(embedding, old_emb)
                    if sim >= 0.70:
                        to_deactivate.append(old_id)

            # 2. Deactivate superseded older memories so they are never returned again
            for old_id in to_deactivate:
                await db.query(
                    "UPDATE user_memory SET is_active = false WHERE id = $1",
                    [old_id],
                )
                logger.info("memory_agent.superseded_old_memory", {"deactivated_id": old_id, "topic": topic})

            # 3. Insert the fresh, active memory
            await db.query(
                "INSERT INTO user_memory (user_id, chat_id, type, content, embedding, topic) VALUES ($1, $2, $3, $4, $5, $6)",
                [user_id, row_chat_id, memory_type, user_message, json.dumps(embedding), topic],
            )
            logger.info("memory_agent.extracted_fresh_memory", {"user_id": user_id, "topic": topic, "type": memory_type})
        except Exception as err:
            logger.warn("Memory extraction failed (non-fatal)", {"error": str(err)})


memory_agent = MemoryAgent()
