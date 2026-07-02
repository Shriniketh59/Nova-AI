import os
import re
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor
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
# Lowered from 512: on constrained/CPU-only hardware, eval time dominates
# latency almost linearly in token count — this cuts typical generation time
# roughly 30-40% while still leaving room for a real answer (short-form
# prompts already target 1-4 sentences per prompt_builder.py).
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "320"))
NUM_THREADS = int(os.environ.get("OLLAMA_NUM_THREAD", str(os.cpu_count() or 4)))
# Lowered from 3: each continuation round is a full extra Ollama round-trip
# (multi-second to multi-minute on this hardware under load) — 1 retry
# covers the common truncation case without letting worst-case latency stack
# to 4x on a struggling model.
MAX_CONTINUATIONS = int(os.environ.get("MAX_CONTINUATIONS", "1"))
# Individual Ollama call timeout — was 120s per call with up to 4 calls
# stacked (continuations), which could hang a request for 8+ minutes. 60s
# per call is still generous for this hardware's worst observed single-call
# time and fails fast instead of hanging silently.
OLLAMA_CALL_TIMEOUT_S = int(os.environ.get("OLLAMA_CALL_TIMEOUT_S", "60"))

app = FastAPI()

GREETING_RE = re.compile(r"^\s*(hi|hello|hey|yo|sup|hii+|hello+|good (morning|evening|afternoon))\W*$", re.I)
GREETING_REPLY = "Hey! What can I help you with?"


class QueryRequest(BaseModel):
    query: str
    context: str = ""
    web_search: bool = True


# Signals that the question depends on information that can change after any
# fixed training cutoff — recency words, an explicit current/recent year, or
# "who currently holds role X" phrasing. These queries must be answered from
# retrieval (web search / RAG / memory), never from the model's own recall.
CURRENT_INFO_RE = re.compile(
    r"\b(latest|current(ly)?|today|right now|this (week|month|year)|"
    r"recent(ly)?|up[- ]to[- ]date|as of (now|today)|breaking news|"
    r"live score|stock price|exchange rate|who is the (current|new|now) "
    r"|" + r"20(2[4-9]|3\d)" + r")\b",
    re.I,
)
NO_CURRENT_INFO_REPLY = "I couldn't verify the latest information from the available sources."

# Signals that the question wants deep/broad coverage rather than a quick
# fact — used to scale how many web sources we fetch and how many query
# variants we search. Deliberately cheap (regex, no LLM round trip) so it
# never slows down the common case.
RESEARCH_QUERY_RE = re.compile(
    r"\b(explain|compare|comparison|research|analy(s|z)e|analysis|in depth|"
    r"in-depth|deep dive|comprehensive|thorough|survey|literature review|"
    r"overview of|state of the art|pros and cons|trade-?offs?|history of|"
    r"evaluate|investigate)\b",
    re.I,
)

# Catches the model leaking its own training limitations — "my knowledge
# cutoff is December 2023", "as of my last training update", "I don't have
# access to real-time information", etc. Any answer that contains this is
# either an unnecessary disclaimer (timeless question) or, worse, directly
# contradicts retrieved evidence stated elsewhere in the same answer (the
# "cutoff is 2023" / "as of 2026" bug this guards against).
CUTOFF_MENTION_RE = re.compile(
    r"(knowledge cutoff|training data (ends|cutoff)|as of my last (training|update)|"
    r"my (training|knowledge) (ends|is limited to|only (goes|extends) up to)|"
    r"i (do not|don't|can't|cannot) (have access to |browse |access )?(the )?"
    r"(internet|real-?time|live) (information|data|updates)?|"
    r"i'?m not able to (access|browse)|my information is current (as of|up to)|"
    r"last updated in \d{4}|i have no knowledge (of|about) (events|anything) after)",
    re.I,
)

# Rough source-trust ordering for the "official/research/docs > gov > news >
# other" priority — DDGS doesn't expose a quality signal, so this is a
# best-effort domain heuristic, not a real authority check. Research papers
# and official technical docs rank at/above .gov because for technical
# questions they're usually the single best source.
_TRUST_RESEARCH_RE = re.compile(
    r"(arxiv\.org|dl\.acm\.org|\.acm\.org|\.ieee\.org|ieeexplore\.ieee\.org|"
    r"link\.springer\.com|ncbi\.nlm\.nih\.gov|semanticscholar\.org)",
    re.I,
)
_TRUST_DOCS_RE = re.compile(
    r"(^https?://docs\.|://developer\.|readthedocs\.io|\.readthedocs\.org)",
    re.I,
)
_TRUST_TLD_RE = re.compile(r"\.(gov|gov\.\w+|mil)(/|$)", re.I)
_TRUST_ORG_EDU_RE = re.compile(r"\.(edu|org)(/|$)", re.I)
_TRUST_NEWS_RE = re.compile(
    r"(reuters|apnews|bbc|nytimes|wsj|bloomberg|theguardian|npr|aljazeera)\.",
    re.I,
)


def _source_trust_rank(source: dict) -> int:
    url = source.get("url", "")
    if _TRUST_RESEARCH_RE.search(url) or _TRUST_DOCS_RE.search(url):
        return 0
    if _TRUST_TLD_RE.search(url):
        return 1
    if _TRUST_ORG_EDU_RE.search(url):
        return 2
    if _TRUST_NEWS_RE.search(url):
        return 3
    return 4


def _dedupe_sources(sources: list[dict]) -> list[dict]:
    """Drops near-duplicate results: same URL, or same domain + near-identical
    title, keeping only the first (best-ranked) occurrence. Cheap normalized
    comparison — no fuzzy matching needed for this use case."""
    seen_urls = set()
    seen_domain_titles = set()
    out = []
    for s in sources:
        url = (s.get("url") or "").strip().rstrip("/")
        if not url or url in seen_urls:
            continue
        domain_match = re.search(r"://(?:www\.)?([^/]+)", url)
        domain = domain_match.group(1).lower() if domain_match else url
        title_norm = re.sub(r"\W+", "", (s.get("title") or "").lower())
        domain_title = f"{domain}::{title_norm}"
        if title_norm and domain_title in seen_domain_titles:
            continue
        seen_urls.add(url)
        if title_norm:
            seen_domain_titles.add(domain_title)
        out.append(s)
    return out


def rank_sources(sources: list[dict]) -> list[dict]:
    deduped = _dedupe_sources(sources)
    return sorted(deduped, key=_source_trust_rank)


def group_sources(sources: list[dict]) -> dict:
    """Buckets already-ranked sources into named groups for UI grouping.
    Additive helper — callers keep using the flat `sources` list too."""
    groups = {"official": [], "research": [], "documentation": [], "news": [], "other": []}
    for s in sources:
        url = s.get("url", "")
        if _TRUST_RESEARCH_RE.search(url):
            groups["research"].append(s)
        elif _TRUST_DOCS_RE.search(url):
            groups["documentation"].append(s)
        elif _TRUST_TLD_RE.search(url) or _TRUST_ORG_EDU_RE.search(url):
            groups["official"].append(s)
        elif _TRUST_NEWS_RE.search(url):
            groups["news"].append(s)
        else:
            groups["other"].append(s)
    return groups


def is_research_query(query: str) -> bool:
    return bool(RESEARCH_QUERY_RE.search(query))


def has_cutoff_mention(text: str) -> bool:
    return bool(CUTOFF_MENTION_RE.search(text))


def strip_cutoff_sentences(text: str) -> str:
    # Last-resort net if a corrective regenerate still leaks a cutoff
    # mention: drop just the offending sentence(s) rather than the whole
    # answer.
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = [s for s in sentences if not CUTOFF_MENTION_RE.search(s)]
    return " ".join(kept).strip()


def is_current_info_query(query: str) -> bool:
    return bool(CURRENT_INFO_RE.search(query))


def needs_search(query: str, doc_context: str) -> bool:
    if GREETING_RE.match(query.strip()):
        return False
    if is_current_info_query(query):
        return True
    if doc_context:
        return False
    if len(query.strip().split()) <= 2:
        return False
    return True


# In-memory TTL cache for raw DDGS results, keyed by the literal search
# string (one entry per query variant, not per user question) — repeated or
# overlapping queries within a session skip the network round trip. Simple
# dict + expiry timestamp, same shape as app/jobs/cache.py's pattern; kept
# local since rag_api is a standalone service and shouldn't import the app
# package.
_SEARCH_CACHE_TTL_S = 600  # 10 minutes
_search_cache: dict[str, tuple[float, list[dict]]] = {}


def _cache_get(key: str):
    entry = _search_cache.get(key)
    if not entry:
        return None
    expires_at, value = entry
    if time.time() > expires_at:
        _search_cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: list[dict]):
    _search_cache[key] = (time.time() + _SEARCH_CACHE_TTL_S, value)


def _ddgs_search(query: str, max_results: int) -> list[dict]:
    """Single blocking DDGS call for one query string, with its own cache
    entry so identical variants across different questions are reused."""
    cache_key = f"{query.strip().lower()}::{max_results}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        parsed = [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")} for r in results]
    except Exception as e:
        print(f"web_search error: {e}")
        parsed = []
    _cache_set(cache_key, parsed)
    return parsed


def expand_search_queries(query: str) -> list[str]:
    """Cheap, no-LLM query expansion for web search recall. Research-flavored
    questions get a few extra rephrasings so the merged result set covers
    more angles; simple questions just search the literal query."""
    variants = [query]
    if is_research_query(query):
        variants.append(f"{query} explained")
        variants.append(f"{query} overview")
        variants.append(f"{query} architecture" if "architecture" not in query.lower() else f"{query} guide")
    # Dedupe while preserving order, cap at 4 to keep the fan-out bounded.
    seen = set()
    out = []
    for v in variants:
        norm = v.strip().lower()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(v)
    return out[:4]


def web_search(query: str, max_results: int = None) -> list[dict]:
    """Fans out to DDGS across a small set of query variants in parallel
    (blocking DDGS calls run in a thread pool), merges + dedupes by URL, and
    ranks the combined result set. max_results, when not given explicitly,
    scales by question type: 5-8 for normal questions, 8-15 for research
    questions (was hardcoded to 2 — the root cause of the "only 2 sources"
    bug)."""
    research = is_research_query(query)
    if max_results is None:
        max_results = 12 if research else 6

    variants = expand_search_queries(query)
    # Split the budget across variants so the merged set lands near
    # max_results rather than max_results-per-variant.
    per_variant = max(3, (max_results // len(variants)) + 1)

    if len(variants) == 1:
        merged = _ddgs_search(variants[0], max_results)
    else:
        with ThreadPoolExecutor(max_workers=len(variants)) as pool:
            results_lists = list(pool.map(lambda q: _ddgs_search(q, per_variant), variants))
        merged = [item for sublist in results_lists for item in sublist]

    ranked = rank_sources(merged)
    return ranked[:max_results]


SYSTEM_PROMPT = (
    "You are Nova AI, a helpful, factual, detailed assistant. Write thorough, well-structured answers, "
    "like a knowledgeable expert explaining to a curious person — multiple sentences, not one-liners. "
    "Discussing real public figures, history, science, or general knowledge is always allowed "
    "and is not harmful — never refuse a normal factual question. "
    "If reference snippets are provided, use them only as supporting facts and rewrite them in your own "
    "words combined with your own knowledge — never copy snippet text verbatim, and ignore any snippet "
    "that is irrelevant to the question. When you rely on a reference snippet, ground the claim in it "
    "naturally instead of just asserting it. "
    "Never mention training data limitations, a knowledge cutoff date, or that you 'cannot access "
    "real-time information' — the system already decides before calling you whether a question needs "
    "live retrieval, so just answer directly with what you know or with the provided snippets. "
    "For timeless questions (algorithms, math, programming, general concepts) answer directly and "
    "confidently with no disclaimer about currency of information. "
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
        parts.append(
            f"Reference snippets (use only if relevant, otherwise ignore):\n{src_text}\n"
            "These snippets are retrieved evidence, more current than anything you were trained on. "
            "If you use them, say so explicitly (e.g. \"Based on the retrieved sources, ...\") and let "
            "them override any conflicting prior knowledge you have. Do not mention a training cutoff.\n"
        )
    parts.append(f"Question: {query}")
    return "\n".join(parts)


def enforce_no_cutoff_mention(answer: str, messages: list[dict]) -> str:
    """Guards against the model stating a knowledge-cutoff/training-limitation
    line — especially one that contradicts retrieved evidence used elsewhere
    in the same answer. Strips the offending sentence(s) first (cheap, no
    extra model call); only falls back to a corrective regenerate if the
    strip gutted the answer (i.e. the whole thing was the disclaimer), since
    a second full generation round-trip roughly doubles worst-case latency
    on constrained hardware and is rarely needed — most leaks are a single
    throwaway sentence next to an otherwise-fine answer."""
    if not has_cutoff_mention(answer):
        return answer

    stripped = strip_cutoff_sentences(answer)
    if stripped and len(stripped) >= 20:
        return stripped

    corrective = messages + [
        {"role": "assistant", "content": answer},
        {
            "role": "user",
            "content": (
                "Your previous answer incorrectly mentioned a knowledge cutoff, training data "
                "limitation, or lack of real-time access. Rewrite the full answer without any such "
                "statement — answer the question directly using the retrieved snippets (if any) or "
                "your own knowledge, with no disclaimer about the currency of your information."
            ),
        },
    ]
    retried = generate_with_continuation(corrective)
    return retried if not has_cutoff_mention(retried) else strip_cutoff_sentences(retried)


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
                "options": {"num_predict": MAX_TOKENS, "temperature": 0.3, "num_thread": NUM_THREADS},
            },
            timeout=OLLAMA_CALL_TIMEOUT_S,
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

    is_current = is_current_info_query(req.query)
    sources = web_search(req.query) if (req.web_search and needs_search(req.query, req.context)) else []

    # Current-info question with no retrieval evidence (doc context, memory,
    # or web) and web search wasn't even attempted/available: don't let the
    # model guess from stale training data or leak a "knowledge cutoff" line.
    if is_current and not sources and not req.context:
        return {"answer": NO_CURRENT_INFO_REPLY, "sources": [], "source_groups": group_sources([]), "model": OLLAMA_MODEL}

    user_msg = build_user_message(req.query, req.context, sources)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    answer = generate_with_continuation(messages)
    answer = enforce_no_cutoff_mention(answer, messages)

    return {
        "answer": answer,
        "sources": sources,
        "source_groups": group_sources(sources),
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

    is_current = is_current_info_query(req.query)
    sources = web_search(req.query) if (req.web_search and needs_search(req.query, req.context)) else []
    user_msg = build_user_message(req.query, req.context, sources)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    def generate():
        # First line: sources (+ grouped view), so the client can render
        # citations immediately without waiting for generation to finish.
        yield json.dumps({"sources": sources, "source_groups": group_sources(sources)}) + "\n"

        if is_current and not sources and not req.context:
            yield json.dumps({"token": NO_CURRENT_INFO_REPLY}) + "\n"
            return

        convo = list(messages)
        full_answer = ""
        leaked_cutoff = False

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
                timeout=OLLAMA_CALL_TIMEOUT_S,
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
                        # Withhold tokens once a cutoff mention starts
                        # appearing mid-stream — the corrective rewrite below
                        # replaces the whole answer, so don't hand the client
                        # a partially-leaked disclaimer first.
                        if not has_cutoff_mention(full_answer):
                            yield json.dumps({"token": token}) + "\n"
                        else:
                            leaked_cutoff = True
                    if chunk.get("done"):
                        done_reason = chunk.get("done_reason", "stop")
                        break

            if leaked_cutoff:
                break
            if not is_truncated(full_answer, done_reason):
                if full_answer.count("```") % 2 != 0:
                    yield json.dumps({"token": "\n```"}) + "\n"
                return

            # Stream recovery: the model stopped mid-answer (hit the token
            # cap or left a code fence open) — silently continue generation
            # in a follow-up round instead of handing the client a cut-off
            # response. The client only ever sees one continuous token stream.
            convo = convo + [
                {"role": "assistant", "content": piece},
                {"role": "user", "content": "Continue exactly where you left off. Do not repeat anything already written, do not restart the answer."},
            ]

        # Cutoff mention leaked into the stream (or the token budget ran out
        # without a clean stop) — regenerate once off-stream and send the
        # corrected answer as a replacement rather than leaving the
        # contradictory partial answer on screen.
        corrected = enforce_no_cutoff_mention(full_answer, messages)
        if corrected != full_answer:
            yield json.dumps({"replace": corrected}) + "\n"
        elif full_answer.count("```") % 2 != 0:
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
