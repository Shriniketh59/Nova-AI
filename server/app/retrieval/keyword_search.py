import math
import re
from typing import List, Optional

from ..knowledge.refresh_pipeline import refresh_manager
from ..rag import fetch_chunks_for_chat

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for",
    "and", "or", "with", "what", "how", "do", "does", "i", "can", "tell", "about",
    "by", "from", "at", "as", "it", "its", "that", "this",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _apply_metadata_filter(chunks: list[dict], filters: dict | None) -> list[dict]:
    if not filters:
        return chunks
    filtered = []
    for c in chunks:
        match = True
        for k, v in filters.items():
            if k in c and c[k] != v:
                match = False
                break
        if match:
            filtered.append(c)
    return filtered


def bm25_score_chunks(query_terms: list[str], chunks: list[dict], k1: float = 1.5, b: float = 0.75) -> list[dict]:
    """Computes Okapi BM25 score for each chunk across the corpus."""
    if not query_terms or not chunks:
        return []

    # 1. Tokenize corpus chunks
    tokenized_corpus = []
    doc_freqs: dict[str, int] = {t: 0 for t in query_terms}
    total_len = 0

    for chunk in chunks:
        terms = _tokenize(chunk.get("content", ""))
        tokenized_corpus.append(terms)
        total_len += len(terms)
        term_set = set(terms)
        for qt in query_terms:
            if qt in term_set:
                doc_freqs[qt] += 1

    n_docs = len(chunks)
    avgdl = total_len / max(1, n_docs)

    # 2. Compute IDF for query terms
    idf: dict[str, float] = {}
    for qt in query_terms:
        df = doc_freqs.get(qt, 0)
        # Standard BM25 IDF formula with smoothing
        idf[qt] = max(0.1, math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0))

    # 3. Score each chunk
    scored = []
    for idx, chunk in enumerate(chunks):
        terms = tokenized_corpus[idx]
        dl = len(terms)
        if dl == 0:
            continue

        term_counts: dict[str, int] = {}
        for t in terms:
            term_counts[t] = term_counts.get(t, 0) + 1

        bm25_val = 0.0
        for qt in query_terms:
            tf = term_counts.get(qt, 0)
            if tf > 0:
                numerator = tf * (k1 + 1.0)
                denominator = tf + k1 * (1.0 - b + b * (dl / avgdl))
                bm25_val += idf[qt] * (numerator / denominator)

        if bm25_val > 0:
            # Normalize BM25 score to [0, 1] range for composite scoring
            norm_score = round(min(1.0, bm25_val / (len(query_terms) * 4.0)), 4)
            scored.append({
                **chunk,
                "keywordScore": norm_score,
                "raw_bm25": bm25_val,
            })

    scored.sort(key=lambda c: c["keywordScore"], reverse=True)
    return scored


async def keyword_search(
    query: str,
    chat_id: str = "",
    top_k: int = 10,
    filters: Optional[dict] = None,
    candidate_chunks: Optional[List[dict]] = None,
) -> list[dict]:
    query_terms = list({t for t in _tokenize(query) if t not in STOPWORDS and len(t) > 1})
    if not query_terms:
        return []

    chunks = candidate_chunks
    if chunks is None:
        chunks = await fetch_chunks_for_chat(chat_id) if chat_id else []
        # If no chat-specific chunks, fall back to global knowledge base
        if not chunks:
            chunks = refresh_manager.list_all_chunks()

    if not chunks:
        return []

    filtered = _apply_metadata_filter(chunks, filters)
    if not filtered:
        return []

    scored = bm25_score_chunks(query_terms, filtered)
    return scored[:top_k]
