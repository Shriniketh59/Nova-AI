from typing import Optional

from ..core.config import QDRANT_URL, VECTOR_STORE_BACKEND
from ..core.logger import logger
from ..knowledge.refresh_pipeline import refresh_manager
from ..rag import cosine_similarity, fetch_chunks_for_chat, fetch_file_ids_for_chat, generate_embedding
from .qdrant_client import COLLECTIONS
from .vector_store import get_vector_store, vector_store_enabled


async def in_memory_cosine_search(
    query_vector: list[float],
    chat_id: str = "",
    top_k: int = 10,
    filters: Optional[dict] = None,
    user_id: Optional[str] = None,
) -> list[dict]:
    chunks = await fetch_chunks_for_chat(chat_id) if chat_id else []
    if not chunks:
        chunks = refresh_manager.list_all_chunks()

    if not chunks:
        return []

    scored = []
    for c in chunks:
        # Multi-tenancy check: only allow caller's own documents or global public knowledge
        chunk_uid = c.get("user_id")
        chunk_scope = c.get("scope", "global" if not chunk_uid else "user")
        if user_id and chunk_uid and chunk_uid != user_id and chunk_scope != "global":
            continue

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
    user_id: Optional[str] = None,
) -> list[dict]:
    """Dense semantic vector search through the configured VectorStore backend
    (ChromaDB by default, Qdrant optionally) with an in-memory cosine fallback.

    Supports pre-computed query vectors to avoid redundant Ollama embedding calls,
    metadata-aware payload filtering, and user isolation.

    Falls back to the in-memory knowledge base both when the backend errors and
    when it returns no hits, so an empty/unbuilt vector index never silently
    yields a context-free answer.

    NOTE: `QDRANT_URL` is still referenced here (rather than only inside
    vector_store_enabled) because tests monkeypatch it on this module to
    simulate an unreachable backend.
    """
    q_vec = query_vector if query_vector is not None else await generate_embedding(query)

    backend_ready = vector_store_enabled()
    if VECTOR_STORE_BACKEND == "qdrant" and not QDRANT_URL:
        backend_ready = False
    if not backend_ready:
        return await in_memory_cosine_search(q_vec, chat_id, top_k, filters, user_id=user_id)

    try:
        store_filter: dict = {"must": []}

        # If scoped to a specific chat with uploaded files
        if chat_id:
            file_ids = await fetch_file_ids_for_chat(chat_id)
            if file_ids:
                store_filter["must"].append({"key": "file_id", "match": {"any": file_ids}})

        # Metadata payload filters
        if filters:
            for k, v in filters.items():
                store_filter["must"].append({"key": k, "match": {"value": v}})

        filter_arg = store_filter if store_filter["must"] else None

        store = get_vector_store()
        results = await store.search(
            COLLECTIONS["documents"]["name"],
            q_vec,
            limit=top_k,
            filter=filter_arg,
        )

        if not results:
            # Index is empty or nothing matched — fall back rather than
            # returning a context-free result.
            return await in_memory_cosine_search(q_vec, chat_id, top_k, filters, user_id=user_id)

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
        logger.warn(
            "semantic_search.vector_store_fallback",
            {"backend": VECTOR_STORE_BACKEND, "error": str(err)},
        )
        return await in_memory_cosine_search(q_vec, chat_id, top_k, filters, user_id=user_id)


async def embed_query(query: str):
    return await generate_embedding(query)
