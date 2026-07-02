import math
import re

from ..rag import fetch_chunks_for_chat

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for",
    "and", "or", "with", "what", "how", "do", "does", "i",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _term_freq_score(query_terms: list[str], chunk_text: str) -> float:
    chunk_terms = _tokenize(chunk_text)
    if not chunk_terms:
        return 0
    chunk_term_counts: dict[str, int] = {}
    for t in chunk_terms:
        chunk_term_counts[t] = chunk_term_counts.get(t, 0) + 1

    score = 0.0
    for qt in query_terms:
        tf = chunk_term_counts.get(qt, 0)
        if tf > 0:
            score += (1 + math.log(tf)) / math.sqrt(len(chunk_terms))
    return score


async def keyword_search(query: str, chat_id: str, top_k: int = 10) -> list[dict]:
    query_terms = list({t for t in _tokenize(query) if t not in STOPWORDS and len(t) > 1})
    if not query_terms:
        return []

    chunks = await fetch_chunks_for_chat(chat_id)
    if not chunks:
        return []

    scored = [
        {**chunk, "keywordScore": _term_freq_score(query_terms, chunk["content"])} for chunk in chunks
    ]
    scored = [c for c in scored if c["keywordScore"] > 0]
    scored.sort(key=lambda c: c["keywordScore"], reverse=True)
    return scored[:top_k]
