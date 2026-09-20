import os

import httpx

from ..core import db
from ..core.config import OLLAMA_URL, OLLAMA_MODEL
from ..core.logger import logger
from ..retrieval.context_compression import compress_context, estimate_tokens

SUMMARY_REFRESH_THRESHOLD = int(os.environ.get("SUMMARY_REFRESH_THRESHOLD", 20))


async def _summarize(messages: list[dict]) -> str:
    transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "stream": False,
                    "options": {"temperature": 0.2},
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Summarize this conversation in 3-5 sentences: key facts established, "
                                "decisions made, and the user's stated preferences/goals. Be specific, not generic."
                            ),
                        },
                        {"role": "user", "content": transcript},
                    ],
                },
            )
            if res.status_code >= 400:
                raise RuntimeError(f"Summary call failed: {res.status_code}")
            data = res.json()
            return (data.get("message") or {}).get("content", "")
    except Exception as err:
        logger.warn("contextManager.summarize.failed", {"error": str(err)})
        return ""


async def get_conversation_context(chat_id: str, query: str = "", max_chars: int = 3000) -> str:
    """Returns a context block for the prompt: a cached summary of older turns,
    semantically retrieved past messages via vector embedding similarity, and
    most recent messages verbatim, budgeted to max_chars."""
    if not chat_id:
        return ""

    chat_res = await db.query("SELECT * FROM chats WHERE id = $1", [chat_id])
    chat_row = chat_res["rows"][0] if chat_res["rows"] else {}
    cached_summary = chat_row.get("summary")
    summary_message_count = chat_row.get("summary_message_count") or 0

    messages_res = await db.query("SELECT * FROM messages WHERE chat_id = $1 ORDER BY created_at ASC", [chat_id])
    messages = messages_res["rows"]

    new_since_summary = len(messages) - summary_message_count
    summary = cached_summary

    if new_since_summary >= SUMMARY_REFRESH_THRESHOLD:
        to_summarize = messages[:-5]
        if to_summarize:
            summary = await _summarize(to_summarize)
            await db.query(
                "UPDATE chats SET summary = $1, summary_updated_at = CURRENT_TIMESTAMP, summary_message_count = $2 WHERE id = $3",
                [summary, len(messages), chat_id],
            )

    # Vector search over older messages if query is provided and we have > 5 messages
    vector_retrieved_turns = []
    if query and len(messages) > 5:
        try:
            from ..rag import generate_embedding, cosine_similarity
            query_vec = await generate_embedding(query)
            older_messages = messages[:-5]
            scored = []
            for m in older_messages:
                content = m.get("content", "")
                if content:
                    emb = await generate_embedding(content[:300])
                    sim = cosine_similarity(query_vec, emb)
                    if sim > 0.3:
                        scored.append((sim, f"{m['role']}: {content}"))
            scored.sort(key=lambda x: x[0], reverse=True)
            vector_retrieved_turns = [item[1] for item in scored[:3]]
        except Exception as v_err:
            logger.warn("vector_chat_search_failed", {"error": str(v_err)})

    recent_messages = [{"content": f"{m['role']}: {m['content']}"} for m in messages[-5:]]
    recent_budget = max_chars - len(summary or "") - 50
    recent_kept = compress_context(recent_messages, max(recent_budget, 0))

    blocks = []
    if summary:
        blocks.append(f"[Earlier in this conversation]\n{summary}")
    if vector_retrieved_turns:
        blocks.append("[Relevant past context (Vector Search)]\n" + "\n".join(vector_retrieved_turns))
    if recent_kept:
        blocks.append("[Recent messages]\n" + "\n".join(m["content"] for m in recent_kept))

    context_text = "\n\n".join(blocks)
    logger.info("contextManager.context", {
        "chatId": chat_id,
        "totalMessages": len(messages),
        "hasSummary": bool(summary),
        "vectorRetrievedCount": len(vector_retrieved_turns),
        "estimatedTokens": estimate_tokens(context_text),
    })
    return context_text
