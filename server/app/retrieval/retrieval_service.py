import asyncio
import time
from typing import Optional

from ..core.config import RAG_TOP_K, RAG_SIMILARITY_THRESHOLD, RAG_MAX_CONTEXT_CHARS
from ..core.logger import logger
from ..jobs.cache import cache_key, get_cached, set_cached
from ..knowledge.refresh_pipeline import refresh_manager
from ..rag import generate_embedding, fetch_chunks_for_chat
from .context_compression import dedupe_chunks, compress_context
from .freshness_scorer import rank_candidates_with_freshness
from .hybrid_search import hybrid_search
from .query_analyzer import analyze_query
from .reranker import rerank
from .source_attribution import attribute_sources

DEFAULT_TOP_K = RAG_TOP_K
DEFAULT_THRESHOLD = RAG_SIMILARITY_THRESHOLD
MAX_CONTEXT_CHARS = RAG_MAX_CONTEXT_CHARS


def _compute_confidence(chunks: list[dict]) -> dict:
    """Confidence score derived from top candidate relevance, freshness, and agreement."""
    if not chunks:
        return {"score": 0, "label": "low"}
    top = chunks[0]
    top_score = top.get("composite_score") or top.get("similarity") or top.get("hybridScore", 0.0)
    support_bonus = min(len(chunks), 5) * 0.03
    score = max(0.0, min(1.0, top_score + support_bonus))
    label = "high" if score >= 0.6 else "medium" if score >= 0.35 else "low"
    return {"score": round(score * 100), "label": label}


async def retrieve(
    query: str,
    chat_id: str = "",
    top_k: int | None = None,
    threshold: float | None = None,
    filters: Optional[dict] = None,
    include_web: Optional[bool] = None,
) -> dict:
    """Modern RAG Retrieval Pipeline:
    1. Query Analysis (normalization, intent detection, entities, routing)
    2. Parallel Retrieval (Dense Vector DB + Sparse BM25 + Fresh Web)
    3. Deduplication
    4. Freshness-Aware Scoring (semantic + lexical + freshness + authority)
    5. Lightweight Reranking (MMR for relevance and diversity)
    6. Context Compression & Structured Source Attribution"""
    t_start = time.perf_counter()
    top_k = top_k or DEFAULT_TOP_K
    threshold = DEFAULT_THRESHOLD if threshold is None else threshold

    key = cache_key(f"{query}::{filters}::{include_web}", chat_id)
    cached = get_cached(key)
    if cached:
        logger.info("retrieval.cache_hit", {"chatId": chat_id, "query_prefix": query[:30]})
        return cached

    # 1. Query Analysis
    t0 = time.perf_counter()
    available_chat_chunks = await fetch_chunks_for_chat(chat_id) if chat_id else []
    has_files = len(available_chat_chunks) > 0
    kb_chunks = refresh_manager.list_all_chunks()
    has_local_docs = bool(available_chat_chunks or kb_chunks)

    analysis = analyze_query(query, has_attached_files=has_files)
    t_analysis = round((time.perf_counter() - t0) * 1000, 2)

    # Determine if fresh web retrieval should run
    should_include_web = bool(include_web)

    # If a specific chat has no uploaded files, or no local documents exist and web search is not triggered, return empty immediately
    if ((chat_id and not has_files) or not has_local_docs) and not should_include_web:
        result = {
            "chunks": [],
            "contextText": "",
            "sources": [],
            "confidence": {"score": 0, "label": "low"},
            "metrics": {"total_ms": round((time.perf_counter() - t_start) * 1000, 2)},
        }
        set_cached(key, result)
        return result

    if analysis.is_greeting:
        result = {
            "chunks": [],
            "contextText": "",
            "sources": [],
            "confidence": {"score": 100, "label": "high"},
            "metrics": {"total_ms": round((time.perf_counter() - t_start) * 1000, 2)},
        }
        set_cached(key, result)
        return result

    # 2. Embedding Generation (graceful fallback if Ollama embedding service is temporarily unreachable)
    t1 = time.perf_counter()
    try:
        query_vector = await generate_embedding(analysis.normalized_query)
    except Exception as err:
        logger.warn("retrieval.embed_failed_fallback", {"error": str(err)})
        query_vector = None
    t_embed = round((time.perf_counter() - t1) * 1000, 2)

    # 3. Parallel Retrieval
    t2 = time.perf_counter()
    search_tasks = [
        hybrid_search(
            q_var,
            chat_id=chat_id,
            top_k=top_k * 2,
            query_vector=query_vector if q_var == analysis.normalized_query else None,
            filters=filters,
            include_web=(should_include_web and idx == 0),
        )
        for idx, q_var in enumerate(analysis.retrieval_queries)
    ]

    variant_results = await asyncio.gather(*search_tasks)
    t_search = round((time.perf_counter() - t2) * 1000, 2)

    # Merge candidates across variants
    candidate_map: dict[str, dict] = {}
    for results in variant_results:
        for chunk in results:
            c_id = chunk.get("id") or chunk.get("content", "")[:50]
            existing = candidate_map.get(c_id)
            score = chunk.get("hybridScore", 0.0)
            if not existing or score > existing.get("hybridScore", 0.0):
                candidate_map[c_id] = chunk

    candidates = list(candidate_map.values())

    # 4. Deduplication
    deduped = dedupe_chunks(candidates)

    # Filter out near-zero relevance results
    above_threshold = [
        c for c in deduped
        if (c.get("similarity") or 0) >= threshold
        or c.get("keywordScore", 0) > 0
        or c.get("hybridScore", 0) > 0
        or c.get("is_web_result")
    ]

    # 5. Freshness-Aware Scoring
    t3 = time.perf_counter()
    freshness_scored = rank_candidates_with_freshness(above_threshold, intent=analysis.intent)

    # 6. Reranking
    reranked = await rerank(query_vector, freshness_scored, top_k=top_k * 2)
    t_rerank = round((time.perf_counter() - t3) * 1000, 2)

    # 7. Context Compression
    final_chunks = compress_context(reranked, MAX_CONTEXT_CHARS)[:top_k]

    t_total = round((time.perf_counter() - t_start) * 1000, 2)

    metrics = {
        "analysis_ms": t_analysis,
        "embed_ms": t_embed,
        "search_ms": t_search,
        "rerank_ms": t_rerank,
        "total_ms": t_total,
        "candidates_count": len(candidates),
        "above_threshold_count": len(above_threshold),
        "final_count": len(final_chunks),
        "intent": analysis.intent,
        "web_searched": should_include_web,
    }

    logger.info("retrieval.pipeline_complete", {
        "chatId": chat_id,
        "query_prefix": query[:40],
        **metrics,
    })

    context_text = "\n---\n".join(c["content"] for c in final_chunks)
    sources = attribute_sources(final_chunks)
    confidence = _compute_confidence(final_chunks)

    result = {
        "chunks": final_chunks,
        "contextText": context_text,
        "sources": sources,
        "confidence": confidence,
        "metrics": metrics,
    }
    set_cached(key, result)
    return result
