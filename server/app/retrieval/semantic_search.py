from typing import Optional

from ..core.config import QDRANT_URL
from ..core.logger import logger
from ..knowledge.refresh_pipeline import refresh_manager
from ..rag import cosine_similarity, fetch_chunks_for_chat, fetch_file_ids_for_chat, generate_embedding
from .qdrant_client import COLLECTIONS, search as qdrant_search


async def in_memory_cosine_search(
    query_vector: list[float],
    chat_id: str = "",
    top_k: int = 10,
    filters: Optional[dict] = None,
) -> list[dict]:
    chunks = await fetch_chunks_for_chat(chat_id) if chat_id else []
    if not chunks:
        chunks = refresh_manager.list_all_chunks()

    if not chunks:
        return []

    scored = []
    for c in chunks:
        # Apply metadata filters if provided
        if filters:
            match = True
            for k, v in filters.items():
                if k in c and c[k] != v:
                    match = False
                    break
            if not match:
                continue

        emb = c.get("embedding")
        if not emb:
            continue
        sim = cosine_similarity(query_vector, emb)
        scored.append({**c, "similarity": round(sim, 4)})

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


async def semantic_search(
    query: str,
    chat_id: str = "",
    top_k: int = 10,
    query_vector: Optional[list[float]] = None,
    filters: Optional[dict] = None,
) -> list[dict]:
    """Dense semantic vector search across Qdrant with in-memory fallback.
    Supports pre-computed query vectors to avoid redundant Ollama embedding calls,
    and metadata-aware payload filtering."""
    q_vec = query_vector if query_vector is not None else await generate_embedding(query)

    if not QDRANT_URL:
        return await in_memory_cosine_search(q_vec, chat_id, top_k, filters)

    try:
        qdrant_filter: dict = {"must": []}

        # If scoped to a specific chat with uploaded files
        if chat_id:
            file_ids = await fetch_file_ids_for_chat(chat_id)
            if file_ids:
                qdrant_filter["must"].append({"key": "file_id", "match": {"any": file_ids}})

        # Metadata payload filters
        if filters:
            for k, v in filters.items():
                qdrant_filter["must"].append({"key": k, "match": {"value": v}})

        filter_arg = qdrant_filter if qdrant_filter["must"] else None

        results = await qdrant_search(
            COLLECTIONS["documents"]["name"],
            q_vec,
            limit=top_k,
            filter=filter_arg,
        )

        return [
            {
                "id": r["id"],
                "file_id": r.get("payload", {}).get("file_id"),
                "document_id": r.get("payload", {}).get("document_id"),
                "content": r.get("payload", {}).get("content", ""),
                "page_number": r.get("payload", {}).get("page_number"),
                "original_filename": r.get("payload", {}).get("original_filename"),
                "title": r.get("payload", {}).get("title"),
                "source_url": r.get("payload", {}).get("source_url"),
                "source_domain": r.get("payload", {}).get("source_domain"),
                "source_type": r.get("payload", {}).get("source_type"),
                "category": r.get("payload", {}).get("category"),
                "freshness_score": r.get("payload", {}).get("freshness_score"),
                "updated_at": r.get("payload", {}).get("updated_at"),
                "similarity": r["score"],
            }
            for r in results
        ]
    except Exception as err:
        logger.warn("semantic_search.qdrant_fallback", {"error": str(err)})
        return await in_memory_cosine_search(q_vec, chat_id, top_k, filters)


async def embed_query(query: str):
    return await generate_embedding(query)
