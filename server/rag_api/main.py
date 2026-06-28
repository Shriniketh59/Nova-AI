import os
import re
import json
import requests
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from ddgs import DDGS

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
# This path is general chat only now — coding questions are routed to
# CodeAgent (Node side) before ever reaching here, so 512 is enough budget
# for a normal conversational answer. The auto-continue loop below still
# catches the rare long answer that needs more room, so dropping this back
# down from 2048 doesn't reintroduce truncation, it just keeps the common
# case fast.
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "512"))
NUM_THREADS = int(os.environ.get("OLLAMA_NUM_THREAD", str(os.cpu_count() or 4)))
MAX_CONTINUATIONS = int(os.environ.get("MAX_CONTINUATIONS", "3"))

app = FastAPI()

GREETING_RE = re.compile(r"^\s*(hi|hello|hey|yo|sup|hii+|hello+|good (morning|evening|afternoon))\W*$", re.I)
GREETING_REPLY = "Hey! What can I help you with?"


class QueryRequest(BaseModel):
    query: str
    context: str = ""
    web_search: bool = True


def needs_search(query: str, doc_context: str) -> bool:
    if doc_context:
        return False
    if GREETING_RE.match(query.strip()):
        return False
    if len(query.strip().split()) <= 2:
        return False
    return True


def web_search(query: str, max_results: int = 2) -> list[dict]:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")} for r in results]
    except Exception as e:
        print(f"web_search error: {e}")
        return []


SYSTEM_PROMPT = (
    "You are Nova AI, a helpful, factual, detailed assistant. Write thorough, well-structured answers, "
    "like a knowledgeable expert explaining to a curious person — multiple sentences, not one-liners. "
    "Discussing real public figures, history, science, or general knowledge is always allowed "
    "and is not harmful — never refuse a normal factual question. "
    "If reference snippets are provided, use them only as supporting facts and rewrite them in your own "
    "words combined with your own knowledge — never copy snippet text verbatim, and ignore any snippet "
    "that is irrelevant to the question. "
    "Keep answers under {max_tokens} tokens. Do not repeat URLs in the answer text."
).format(max_tokens=MAX_TOKENS)


def is_truncated(text: str, done_reason: str) -> bool:
    # Ollama sets done_reason="length" when it hit num_predict, the
    # authoritative truncation signal — but also catch generations that
    # stopped cleanly mid code-block (odd fence count) since those still
    # render broken in the UI even though the model thinks it's "done".
    if done_reason == "length":
        return True
    if text.count("```") % 2 != 0:
        return True
    return False


def close_unbalanced_fences(text: str) -> str:
    # Last-resort safety net if continuation rounds run out — never ship an
    # unclosed code block to the markdown renderer.
    if text.count("```") % 2 != 0:
        return text.rstrip() + "\n```"
    return text


def build_user_message(query: str, doc_context: str, sources: list[dict]) -> str:
    parts = []
    if doc_context:
        parts.append(f"Document context:\n{doc_context}\n")
    if sources:
        src_text = "\n".join(f"- {s['title']}: {s['snippet']}" for s in sources)
        parts.append(f"Reference snippets (use only if relevant, otherwise ignore):\n{src_text}\n")
    parts.append(f"Question: {query}")
    return "\n".join(parts)


def generate_with_continuation(messages: list[dict]) -> str:
    # Auto-continue: if Ollama stopped because it hit num_predict (or left a
    # code fence unclosed), ask it to pick up exactly where it left off
    # instead of returning a truncated answer. Bounded by MAX_CONTINUATIONS
    # so a model that never emits a clean stop can't loop forever.
    answer = ""
    convo = list(messages)
    for _ in range(MAX_CONTINUATIONS + 1):
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": convo,
                "stream": False,
                "options": {"num_predict": MAX_TOKENS, "temperature": 0.3},
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        piece = data.get("message", {}).get("content", "")
        answer += piece
        done_reason = data.get("done_reason", "stop")

        if not is_truncated(answer, done_reason):
            return answer

        convo = convo + [
            {"role": "assistant", "content": piece},
            {"role": "user", "content": "Continue exactly where you left off. Do not repeat anything already written, do not restart the answer."},
        ]

    return close_unbalanced_fences(answer)


@app.post("/query")
def query(req: QueryRequest):
    if GREETING_RE.match(req.query.strip()):
        return {"answer": GREETING_REPLY, "sources": [], "model": OLLAMA_MODEL}

    sources = web_search(req.query) if (req.web_search and needs_search(req.query, req.context)) else []
    user_msg = build_user_message(req.query, req.context, sources)

    answer = generate_with_continuation([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])

    return {
        "answer": answer,
        "sources": sources,
        "model": OLLAMA_MODEL,
    }


@app.post("/query/stream")
def query_stream(req: QueryRequest):
    # Plain greetings never need the LLM — skip generation entirely instead
    # of burning a multi-second round trip on "hi".
    if GREETING_RE.match(req.query.strip()):
        def greet():
            yield json.dumps({"sources": []}) + "\n"
            yield json.dumps({"token": GREETING_REPLY}) + "\n"
        return StreamingResponse(greet(), media_type="application/x-ndjson")

    sources = web_search(req.query) if (req.web_search and needs_search(req.query, req.context)) else []
    user_msg = build_user_message(req.query, req.context, sources)

    def generate():
        # First line: sources, so the client can render citations immediately
        # without waiting for generation to finish.
        yield json.dumps({"sources": sources}) + "\n"

        convo = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]
        full_answer = ""

        for _ in range(MAX_CONTINUATIONS + 1):
            piece = ""
            done_reason = "stop"
            with requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": convo,
                    "stream": True,
                    "options": {"num_predict": MAX_TOKENS, "temperature": 0.3, "num_thread": NUM_THREADS},
                },
                stream=True,
                timeout=120,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        piece += token
                        full_answer += token
                        yield json.dumps({"token": token}) + "\n"
                    if chunk.get("done"):
                        done_reason = chunk.get("done_reason", "stop")
                        break

            if not is_truncated(full_answer, done_reason):
                return

            # Stream recovery: the model stopped mid-answer (hit the token
            # cap or left a code fence open) — silently continue generation
            # in a follow-up round instead of handing the client a cut-off
            # response. The client only ever sees one continuous token stream.
            convo = convo + [
                {"role": "assistant", "content": piece},
                {"role": "user", "content": "Continue exactly where you left off. Do not repeat anything already written, do not restart the answer."},
            ]

        if full_answer.count("```") % 2 != 0:
            yield json.dumps({"token": "\n```"}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


class SearchRequest(BaseModel):
    query: str
    max_results: int = 5


# Sources-only endpoint for ResearchAgent's evidence-gathering step — no
# generation, just the web half of "5-10 high quality sources" (doc half
# comes from retrievalService.js on the Node side).
@app.post("/search")
def search(req: SearchRequest):
    return {"sources": web_search(req.query, max_results=req.max_results)}


@app.get("/health")
def health():
    return {"status": "ok", "model": OLLAMA_MODEL}
