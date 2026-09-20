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
    MAX_OUTPUT_TOKENS,
    DEFAULT_USER_ID,
)
from ..core.logger import logger
from .intent_router import classify_intent, needs_web_search, needs_vector_retrieval, is_coding_question

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TOKENS = int(MAX_OUTPUT_TOKENS)
NUM_THREADS = None  # let Ollama decide based on CPU
RETRIEVAL_CHAR_LIMIT = 4000  # max chars of retrieved context passed to Llama
WEB_SNIPPET_LIMIT = 3        # max web results to include

SYSTEM_PROMPT = (
    "You are Nova AI, an expert, thoughtful, and highly accurate assistant running fully locally. "
    "Answer the CURRENT USER QUERY with clarity, depth, and precision, using rich markdown formatting: "
    "bold key terms, clean bullet points, numbered lists, and structured headings for detailed topics. "
    "Interpret user queries charitably: automatically resolve typos, phonetic errors, spelling mistakes, "
    "and grammatical slips without pedantically pointing them out, and answer accurately based on the intended meaning. "
    "If context, web evidence, or user preferences are provided, ground your answer directly in them. "
    "For code questions, produce complete, runnable code with clear comments and no missing pieces. "
    "Never mention your knowledge cutoff, training limitations, or internal system boundaries. "
    "Today's date: {date}."
)

VOICE_SYSTEM_PROMPT = (
    "You are Nova Voice, a fast, expressive, and clear conversational voice assistant. "
    "Speak naturally in 1-3 short, clear sentences. No markdown, no bullet points, "
    "no asterisks, no code blocks — your response will be spoken aloud. "
    "Be direct, warm, and conversational. Automatically understand any misspoken words or typos. "
    "Today's date: {date}."
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


def _extract_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or url
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return "web"


# ---------------------------------------------------------------------------
# Web retrieval (DDGS — multiple independent clean sources, no API key)
# ---------------------------------------------------------------------------

async def _web_search(query: str, max_results: int = 5) -> list[dict]:
    """DDGS web search — retrieves MULTIPLE independent, clean sources without blocking."""
    loop = asyncio.get_running_loop()

    def _blocking():
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=max_results * 2))

            cleaned_sources = []
            seen_urls = set()
            domain_counts = {}

            for r in raw:
                url = (r.get("href") or r.get("url") or "").strip()
                title = (r.get("title") or "").strip()
                body = (r.get("body") or r.get("snippet") or "").strip()

                if not url or not title or not body or len(body) < 25:
                    continue

                norm_url = url.split("#")[0].rstrip("/")
                if norm_url in seen_urls:
                    continue

                domain = _extract_domain(url)
                # Cap max 2 results per domain to ensure source diversity
                if domain_counts.get(domain, 0) >= 2:
                    continue

                seen_urls.add(norm_url)
                domain_counts[domain] = domain_counts.get(domain, 0) + 1

                cleaned_sources.append({
                    "title": title,
                    "website": domain,
                    "domain": domain,
                    "url": url,
                    "snippet": body[:350],
                    "type": "web",
                })

                if len(cleaned_sources) >= max_results:
                    break

            return cleaned_sources
        except Exception as e:
            logger.warn("orchestrator.web_search_failed", {"error": str(e), "query": query[:40]})
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
# Prompt builder (Requirement 14 Structure)
# ---------------------------------------------------------------------------

def _build_messages(
    query: str,
    context_text: str = "",
    web_sources: Optional[list[dict]] = None,
    conversation_context: Optional[str] = None,
    user_memories: Optional[list[str]] = None,
    is_voice: bool = False,
) -> list[dict]:
    date = _today()
    if is_voice:
        system = (
            f"You are Nova Voice, a fast, expressive, and clear conversational voice assistant. "
            f"Speak naturally in 1-3 short sentences. No markdown, no bullet points, "
            f"no asterisks, no code blocks — your response will be spoken aloud. "
            f"Be direct, warm, and conversational. Today's date: {date}."
        )
    else:
        system = (
            f"You are Nova AI, an expert, thoughtful, and highly accurate assistant running fully locally. "
            f"Answer the CURRENT USER QUERY with clarity, depth, and precision, using rich markdown formatting: "
            f"bold key terms, clean bullet points, numbered lists, and structured headings for detailed topics. "
            f"Interpret user queries charitably: automatically resolve typos, phonetic errors, spelling mistakes, "
            f"and grammatical slips without pedantically pointing them out, and answer accurately based on the intended meaning. "
            f"If context, web evidence, or user preferences are provided, ground your answer directly in them. "
            f"Focus strictly on the question asked. Do NOT introduce unrelated topics or past discussions. "
            f"For code questions, produce complete, runnable code with clear comments and no missing pieces. "
            f"Never mention your knowledge cutoff, training limitations, or internal system boundaries. "
            f"Today's date: {date}."
        )

    messages: list[dict] = [{"role": "system", "content": system}]

    # Requirement 14 Prompt Structure:
    # SYSTEM INSTRUCTIONS
    # CURRENT USER QUERY
    # RELEVANT CONVERSATION CONTEXT (only if needed)
    # USER MEMORY & PREFERENCES (only if present)
    # VECTOR DB CONTEXT (only if relevant)
    # CURRENT WEB SOURCES (only if relevant)
    prompt_blocks = [f"CURRENT USER QUERY:\n{query}"]

    if conversation_context and conversation_context.strip():
        prompt_blocks.append(
            f"[RELEVANT CONVERSATION CONTEXT]\n{conversation_context.strip()}"
        )

    if user_memories:
        valid_mems = [m.strip() for m in user_memories if m and m.strip()]
        if valid_mems:
            mem_text = "\n".join(f"- {m}" for m in valid_mems)
            prompt_blocks.append(
                f"[USER MEMORY & PREFERENCES]\n{mem_text}\n\n"
                f"Instruction: Tailor your response to respect the user's stated preferences and facts above."
            )

    if context_text and context_text.strip():
        prompt_blocks.append(
            f"[VECTOR DB CONTEXT]\n{context_text.strip()[:RETRIEVAL_CHAR_LIMIT]}"
        )

    if web_sources:
        source_lines = []
        for i, s in enumerate(web_sources, 1):
            domain_label = f" ({s['website']})" if s.get('website') else ""
            source_lines.append(
                f"[Source {i}] {s.get('title', '')}{domain_label}\n"
                f"URL: {s.get('url', '')}\n"
                f"Content: {s.get('snippet', '')}"
            )
        web_evidence_text = "\n\n".join(source_lines)
        prompt_blocks.append(
            f"[CURRENT WEB SOURCES]\n{web_evidence_text}\n\n"
            f"Instruction: Ground your answer to the CURRENT USER QUERY in the relevant evidence above. "
            f"Do not include unrelated topics."
        )

    user_message_content = "\n\n".join(prompt_blocks)
    messages.append({"role": "user", "content": user_message_content})

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
    user_id: str = DEFAULT_USER_ID,
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
        # Check daily token budget
        from ..services.token_budget_service import token_budget_service
        allowed, budget_msg = await token_budget_service.check_allowance(user_id, estimated_tokens=30)
        if not allowed:
            yield {"sources": []}
            yield {"token": f"⚠️ {budget_msg}"}
            yield {"done": True}
            return

        # 1. Check what knowledge is available
        has_files = False
        if chat_id:
            try:
                from ..rag import fetch_chunks_for_chat
                chat_chunks = await fetch_chunks_for_chat(chat_id)
                has_files = len(chat_chunks) > 0
            except Exception:
                has_files = False

        from ..knowledge.refresh_pipeline import refresh_manager
        kb_chunks = refresh_manager.list_all_chunks()
        has_kb_docs = bool(kb_chunks)

        # 2. Classify intent (with query regularizer)
        intent = classify_intent(query, has_files=has_files, has_kb_docs=has_kb_docs)
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
            # Cancels gen_task if the consumer stops early (client abort), so
            # code generation doesn't keep running server-side unseen.
            from ..utils.stream_cancel import drain_task_queue
            async for tok in drain_task_queue(gen_task, queue):
                accumulated = tok
                yield {"token": tok}
            await gen_task
            yield {"done": True}
            return

        # 5. Follow-up evaluation: isolate unrelated queries
        from .context_filter import detect_follow_up
        is_follow_up, conversation_context, meta = detect_follow_up(query, conversation_history)
        logger.info("orchestrator.follow_up", {
            "chatId": chat_id,
            "is_follow_up": is_follow_up,
            "reason": meta.get("reason"),
            "query_prefix": query[:40],
        })

        # 6. Retrieve context concurrently for maximum generation speed (low TTFT)
        from ..agents.memory_agent import memory_agent

        async def _fetch_memories():
            try:
                return await memory_agent.get_relevant_memories(chat_id, query, top_k=3, user_id=user_id)
            except Exception:
                return []

        async def _fetch_web():
            if needs_web_search(intent):
                return await _web_search(query, max_results=5)
            return []

        async def _fetch_vector():
            if needs_vector_retrieval(intent, has_files=has_files, has_kb_docs=has_kb_docs):
                return await _vector_retrieve(query, chat_id)
            return ""

        user_memories, web_sources, context_text = await asyncio.gather(
            _fetch_memories(),
            _fetch_web(),
            _fetch_vector(),
        )

        yield {"sources": web_sources if web_sources else []}

        # 7. Build prompt strictly according to Requirement 14 and stream response
        messages = _build_messages(
            query=query,
            context_text=context_text,
            web_sources=web_sources if web_sources else None,
            conversation_context=conversation_context if is_follow_up else None,
            user_memories=user_memories if user_memories else None,
            is_voice=is_voice,
        )

        full_text = ""
        prompt_tokens = token_budget_service.estimate_tokens(str(messages))
        completion_tokens = 0

        async for token in _stream_ollama(messages, max_tokens=MAX_TOKENS):
            full_text += token
            completion_tokens += max(1, len(token) // 4)
            yield {"token": token}

        # 8. Post-process: strip training-cutoff disclaimers
        if CUTOFF_RE.search(full_text):
            cleaned = _strip_cutoff_sentences(full_text)
            if cleaned and cleaned != full_text:
                yield {"replace": cleaned}
                full_text = cleaned

        # 9. Grounding check — advisory. Logs when an answer ignores the
        # evidence it was given, or confidently answers a factual/current
        # question with no evidence at all. Never blocks or rewrites.
        from .answer_validator import validate_answer
        validation = validate_answer(
            query=query,
            answer=full_text,
            evidence_text=context_text,
            web_sources=web_sources,
            is_voice=is_voice,
        )

        # Record daily token usage asynchronously
        asyncio.create_task(token_budget_service.record_usage(user_id, prompt_tokens, completion_tokens))

        elapsed_ms = round((time.perf_counter() - t0) * 1000)
        logger.info("orchestrator.complete", {
            "intent": intent,
            "elapsed_ms": elapsed_ms,
            "web_sources": len(web_sources),
            "context_chars": len(context_text),
            "memories_count": len(user_memories),
            "completion_tokens": completion_tokens,
            "grounded": validation.grounded,
            "validation_warnings": validation.warnings,
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
    user_id: str = DEFAULT_USER_ID,
) -> dict:
    """
    Non-streaming version — collects full response for voice reply.
    Returns {"text": str, "sources": list}
    """
    text_parts = []
    sources = []
    async for event in orchestrate_stream(
        query=query,
        chat_id=chat_id,
        conversation_history=conversation_history,
        is_voice=is_voice,
        user_id=user_id,
    ):
        if "sources" in event:
            sources = event["sources"]
        elif "token" in event:
            text_parts.append(event["token"])
        elif "replace" in event:
            text_parts = [event["replace"]]
    return {"text": "".join(text_parts), "sources": sources}
