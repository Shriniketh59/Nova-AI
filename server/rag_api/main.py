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
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "400"))

app = FastAPI()

GREETING_RE = re.compile(r"^\s*(hi|hello|hey|yo|sup|hii+|hello+|good (morning|evening|afternoon))\W*$", re.I)


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


def build_user_message(query: str, doc_context: str, sources: list[dict]) -> str:
    parts = []
    if doc_context:
        parts.append(f"Document context:\n{doc_context}\n")
    if sources:
        src_text = "\n".join(f"- {s['title']}: {s['snippet']}" for s in sources)
        parts.append(f"Reference snippets (use only if relevant, otherwise ignore):\n{src_text}\n")
    parts.append(f"Question: {query}")
    return "\n".join(parts)


@app.post("/query")
def query(req: QueryRequest):
    sources = web_search(req.query) if (req.web_search and needs_search(req.query, req.context)) else []
    user_msg = build_user_message(req.query, req.context, sources)

    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,
            "options": {"num_predict": MAX_TOKENS, "temperature": 0.3},
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()

    return {
        "answer": data.get("message", {}).get("content", ""),
        "sources": sources,
        "model": OLLAMA_MODEL,
    }


@app.post("/query/stream")
def query_stream(req: QueryRequest):
    sources = web_search(req.query) if (req.web_search and needs_search(req.query, req.context)) else []
    user_msg = build_user_message(req.query, req.context, sources)

    def generate():
        # First line: sources, so the client can render citations immediately
        # without waiting for generation to finish.
        yield json.dumps({"sources": sources}) + "\n"

        with requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "stream": True,
                "options": {"num_predict": MAX_TOKENS, "temperature": 0.3},
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
                    yield json.dumps({"token": token}) + "\n"
                if chunk.get("done"):
                    break

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/health")
def health():
    return {"status": "ok", "model": OLLAMA_MODEL}
