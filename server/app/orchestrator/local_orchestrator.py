"""
Local Orchestrator — single entry point for all AI processing.

Both text chat (SSE) and voice (WebSocket) flow through here.
No external AI API is used. All LLM calls go to local Ollama.

Pipeline:
  query → Intent Router
        → [conditional] Vector DB retrieval
        → [conditional] DDGS web search
        → build prompt with retrieved context
        → llama3.2:3b via Ollama streaming
        → yield SSE tokens
"""
import asyncio
import json
import re
import time
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import httpx

from ..core.config import (
    OLLAMA_URL,
    OLLAMA_MODEL,
    OLLAMA_CODE_MODEL,
    MAX_CONTINUATIONS,
)
from ..core.logger import logger
from .intent_router import classify_intent, needs_web_search, needs_vector_retrieval, is_coding_question

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TOKENS = int(2048)
NUM_THREADS = None  # let Ollama decide based on CPU
RETRIEVAL_CHAR_LIMIT = 4000  # max chars of retrieved context passed to Llama
WEB_SNIPPET_LIMIT = 3        # max web results to include

SYSTEM_PROMPT = (
    "You are Nova AI, a helpful, accurate, and concise assistant running fully locally. "
    "Answer directly and factually. If context is provided, use it. "
    "For code questions, produce complete, runnable code. "
    "Never mention your knowledge cutoff or training limitations. "
    "Today's date: {date}."
)

VOICE_SYSTEM_PROMPT = (
    "You are Nova Voice, a fast conversational voice assistant. "
    "Speak naturally in 1-3 short sentences. No markdown, no bullet points, "
    "no asterisks, no code blocks — your response will be spoken aloud. "
    "Be direct, warm, and conversational. Today's date: {date}."
)

# Regex to detect and strip training-cutoff disclaimers
CUTOFF_RE = re.compile(
    r"(knowledge cutoff|training data|as of my last|my knowledge (ends|is limited)|"
    r"i (don't|do not|can't|cannot) (have access|browse|access) (the )?(internet|real-time|live))",
    re.I,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today() -> str:
    return datetime.now(timezone.utc).strftime("%A, %B %d, %Y")


def _strip_cutoff_sentences(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(s for s in sentences if not CUTOFF_RE.search(s)).strip()


def _clean_voice_text(text: str) -> str:
    """Strip markdown for TTS."""
    t = re.sub(r"\*\*?(.*?)\*\*?", r"\1", text)
    t = re.sub(r"#+\s*", "", t)
    t = re.sub(r"`{1,3}[^`]*`{1,3}", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", t)
    t = re.sub(r"^[\*\-\+]\s+", "", t, flags=re.MULTILINE)
    t = t.replace("&", " and ").replace("%", " percent ")
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------------------
# Web retrieval (DDGS — no API key)
# ---------------------------------------------------------------------------

async def _web_search(query: str, max_results: int = WEB_SNIPPET_LIMIT) -> list[dict]:
    """DDGS web search — runs in thread pool to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()

    def _blocking():
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results + 2))
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": (r.get("body", "") or "")[:300],
                }
                for r in results
            ][:max_results]
        except Exception as e:
            logger.warn("orchestrator.web_search_failed", {"error": str(e)})
            return []

    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _blocking),
            timeout=8.0,
        )
    except asyncio.TimeoutError:
        logger.warn("orchestrator.web_search_timeout", {"query": query[:40]})
        return []


# ---------------------------------------------------------------------------
# Vector DB retrieval
# ---------------------------------------------------------------------------

async def _vector_retrieve(query: str, chat_id: str = "") -> str:
    """Returns concatenated context text from Vector DB (up to RETRIEVAL_CHAR_LIMIT chars)."""
    try:
        from ..retrieval.retrieval_service import retrieve
        result = await retrieve(query, chat_id=chat_id, top_k=5)
        ctx = result.get("contextText", "")
        if ctx:
            return ctx[:RETRIEVAL_CHAR_LIMIT]
    except Exception as e:
        logger.warn("orchestrator.vector_retrieve_failed", {"error": str(e)})
    return ""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_messages(
    query: str,
    context_text: str = "",
    web_sources: Optional[list[dict]] = None,
    conversation_history: Optional[list[dict]] = None,
    is_voice: bool = False,
) -> list[dict]:
    date = _today()
    sys_tmpl = VOICE_SYSTEM_PROMPT if is_voice else SYSTEM_PROMPT
    system = sys_tmpl.format(date=date)

    messages: list[dict] = [{"role": "system", "content": system}]

    # Add conversation history (last 6 turns)
    if conversation_history:
        for turn in conversation_history[-6:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    # Build user message with optional context
    parts = []
    if context_text:
        parts.append(f"[Retrieved Context]\n{context_text[:RETRIEVAL_CHAR_LIMIT]}")
    if web_sources:
        lines = "\n".join(
            f"- {s['title']}: {s['snippet'][:250]}" for s in web_sources[:WEB_SNIPPET_LIMIT]
        )
        parts.append(f"[Live Web Evidence]\n{lines}\nAnswer using this evidence. Be concise and direct.")
    parts.append(f"Question: {query}")

    messages.append({"role": "user", "content": "\n\n".join(parts)})
    return messages


# ---------------------------------------------------------------------------
# Ollama streaming
# ---------------------------------------------------------------------------

async def _stream_ollama(
    messages: list[dict],
    model: str = None,
    max_tokens: int = MAX_TOKENS,
) -> AsyncIterator[str]:
    """Yields text tokens from Ollama /api/chat (streaming)."""
    model = model or OLLAMA_MODEL
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {
            "num_predict": max_tokens,
            "temperature": 0.25,
            "num_ctx": 4096,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_URL}/api/chat",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if chunk.get("done"):
                        break
    except httpx.ConnectError:
        yield "\n\n⚠️ Cannot connect to Ollama. Make sure Ollama is running (`ollama serve`)."
    except Exception as e:
        logger.error("orchestrator.stream_failed", {"error": str(e)})
        yield f"\n\n⚠️ Model error: {e}"


# ---------------------------------------------------------------------------
# Main orchestrate function
# ---------------------------------------------------------------------------

async def orchestrate_stream(
    query: str,
    chat_id: str = "",
    conversation_history: Optional[list[dict]] = None,
    is_voice: bool = False,
) -> AsyncIterator[dict]:
    """
    Main orchestration pipeline. Yields dicts:
      {"sources": [...]}          — web/vector sources (optional)
      {"token": "..."}            — streaming text token
      {"replace": "..."}          — replace full text (on post-processing)
      {"done": True}              — stream complete
      {"error": "..."}            — error
    """
    t0 = time.perf_counter()

    try:
        # 1. Check what knowledge is available
        from ..knowledge.refresh_pipeline import refresh_manager
        kb_chunks = refresh_manager.list_all_chunks()
        has_kb_docs = bool(kb_chunks)

        # 2. Classify intent
        intent = classify_intent(query, has_files=bool(chat_id), has_kb_docs=has_kb_docs)
        logger.info("orchestrator.intent", {"intent": intent, "chatId": chat_id, "query_prefix": query[:40]})

        # 3. Greeting — fast path, no retrieval
        if intent == "greeting":
            yield {"sources": []}
            yield {"token": "Hey! What can I help you with?"}
            yield {"done": True}
            return

        # 4. Coding — delegate to CodeAgent which uses qwen2.5-coder
        if intent == "coding" and not is_voice:
            yield {"sources": []}
            from ..agents.code_agent import CodeAgent
            agent = CodeAgent()
            accumulated = ""
            queue: asyncio.Queue = asyncio.Queue()

            def on_token(tok):
                queue.put_nowait(tok)

            gen_task = asyncio.create_task(agent.run_stream(query, on_token))
            while not gen_task.done():
                try:
                    tok = await asyncio.wait_for(queue.get(), timeout=0.1)
                    accumulated = tok
                    yield {"token": tok}
                except asyncio.TimeoutError:
                    continue
            while not queue.empty():
                tok = queue.get_nowait()
                accumulated = tok
                yield {"token": tok}
            await gen_task
            yield {"done": True}
            return

        # 5. Retrieve context — live web search for all prompts
        context_text = ""
        web_sources = await _web_search(query)
        if web_sources:
            yield {"sources": web_sources}
        else:
            yield {"sources": []}

        if needs_vector_retrieval(intent):
            context_text = await _vector_retrieve(query, chat_id)

        # 6. Build prompt and stream response
        messages = _build_messages(
            query=query,
            context_text=context_text,
            web_sources=web_sources if web_sources else None,
            conversation_history=conversation_history,
            is_voice=is_voice,
        )

        full_text = ""
        async for token in _stream_ollama(messages):
            full_text += token
            yield {"token": token}

        # 7. Post-process: strip training-cutoff disclaimers
        if CUTOFF_RE.search(full_text):
            cleaned = _strip_cutoff_sentences(full_text)
            if cleaned and cleaned != full_text:
                yield {"replace": cleaned}

        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        logger.info("orchestrator.complete", {
            "intent": intent,
            "elapsed_ms": elapsed_ms,
            "web_sources": len(web_sources),
            "context_chars": len(context_text),
        })
        yield {"done": True}

    except Exception as e:
        logger.error("orchestrator.failed", {"error": str(e)})
        yield {"error": str(e)}
        yield {"done": True}


async def orchestrate_full(
    query: str,
    chat_id: str = "",
    conversation_history: Optional[list[dict]] = None,
    is_voice: bool = False,
) -> dict:
    """
    Non-streaming version — collects full response for voice reply.
    Returns {"text": str, "sources": list}
    """
    text_parts = []
    sources = []
    async for event in orchestrate_stream(query, chat_id, conversation_history, is_voice=is_voice):
        if "sources" in event:
            sources = event["sources"]
        elif "token" in event:
            text_parts.append(event["token"])
        elif "replace" in event:
            text_parts = [event["replace"]]
    return {"text": "".join(text_parts), "sources": sources}
