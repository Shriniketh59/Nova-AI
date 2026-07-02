import asyncio

from ..core.config import RAG_TOP_K, RAG_SIMILARITY_THRESHOLD, RAG_MAX_CONTEXT_CHARS
from ..core.logger import logger
from ..jobs.cache import cache_key, get_cached, set_cached
from ..rag import generate_embedding, fetch_chunks_for_chat
from .hybrid_search import hybrid_search
from .query_expansion import expand_query
from .reranker import rerank
from .context_compression import dedupe_chunks, compress_context
from .source_attribution import attribute_sources

DEFAULT_TOP_K = RAG_TOP_K
DEFAULT_THRESHOLD = RAG_SIMILARITY_THRESHOLD
MAX_CONTEXT_CHARS = RAG_MAX_CONTEXT_CHARS


def _compute_confidence(chunks: list[dict]) -> dict:
    """Confidence is derived purely from retrieval signal (top score + how
    many chunks agree), not a second LLM call — keeps this on the hot path cheap."""
    if not chunks:
        return {"score": 0, "label": "low"}
    top_score = chunks[0].get("similarity") if chunks[0].get("similarity") is not None else chunks[0].get("hybridScore", 0)
    support_bonus = min(len(chunks), 5) * 0.03
    score = max(0, min(1, top_score + support_bonus))
    label = "high" if score >= 0.6 else "medium" if score >= 0.35 else "low"
    return {"score": round(score * 100), "label": label}


async def retrieve(query: str, chat_id: str, top_k: int | None = None, threshold: float | None = None) -> dict:
    """Single entry point for "go get me relevant, deduplicated, ranked context".
    Pipeline: multi-query expansion -> hybrid (semantic+keyword) search per
    variant -> merge -> MMR rerank -> dedupe -> context-budget compression ->
    confidence scoring. Cached per (query, chatId) for repeat questions."""
    top_k = top_k or DEFAULT_TOP_K
    threshold = DEFAULT_THRESHOLD if threshold is None else threshold

    key = cache_key(query, chat_id)
    cached = get_cached(key)
    if cached:
        return cached

    available_chunks = await fetch_chunks_for_chat(chat_id)
    if not available_chunks:
        result = {"chunks": [], "contextText": "", "sources": [], "confidence": {"score": 0, "label": "low"}}
        set_cached(key, result)
        return result

    query_vector, expansions = await asyncio.gather(generate_embedding(query), expand_query(query))

    variants = [query, *expansions]

    variant_results = await asyncio.gather(*[hybrid_search(v, chat_id, top_k * 3) for v in variants])
    candidate_map: dict = {}
    for results in variant_results:
        for chunk in results:
            existing = candidate_map.get(chunk["id"])
            if not existing or chunk["hybridScore"] > existing["hybridScore"]:
                candidate_map[chunk["id"]] = chunk

    candidates = list(candidate_map.values())
    above_threshold = [c for c in candidates if (c.get("similarity") or 0) >= threshold or c.get("keywordScore", 0) > 0]

    reranked = await rerank(query_vector, above_threshold, top_k * 2)
    deduped = dedupe_chunks(reranked)
    final_chunks = compress_context(deduped, MAX_CONTEXT_CHARS)[:top_k]

    logger.info("retrieval.pipeline", {
        "chatId": chat_id,
        "variants": len(variants),
        "candidates": len(candidates),
        "aboveThreshold": len(above_threshold),
        "final": len(final_chunks),
    })

    context_text = "\n---\n".join(c["content"] for c in final_chunks)
    sources = attribute_sources(final_chunks)
    confidence = _compute_confidence(final_chunks)

    result = {"chunks": final_chunks, "contextText": context_text, "sources": sources, "confidence": confidence}
    set_cached(key, result)
    return result
