from ..core.config import QDRANT_URL
from ..core.logger import logger
from ..rag import generate_embedding, search_relevant_chunks, fetch_file_ids_for_chat
from .qdrant_client import search as qdrant_search, COLLECTIONS


async def semantic_search(query: str, chat_id: str, top_k: int = 10) -> list[dict]:
    """When QDRANT_URL is set, search the vector DB instead of the in-Python
    cosine loop — falls back to search_relevant_chunks() on any Qdrant error
    (down container, collection not ready yet) so retrieval never hard-fails
    on an infra issue."""
    if not QDRANT_URL:
        return await search_relevant_chunks(query, chat_id, top_k)

    try:
        file_ids = await fetch_file_ids_for_chat(chat_id)
        if not file_ids:
            return []

        query_vector = await generate_embedding(query)
        results = await qdrant_search(
            COLLECTIONS["documents"]["name"],
            query_vector,
            limit=top_k,
            filter={"must": [{"key": "file_id", "match": {"any": file_ids}}]},
        )

        return [
            {
                "id": r["id"],
                "file_id": r["payload"]["file_id"],
                "content": r["payload"]["content"],
                "page_number": r["payload"].get("page_number"),
                "original_filename": r["payload"].get("original_filename"),
                "similarity": r["score"],
            }
            for r in results
        ]
    except Exception as err:
        logger.warn("Qdrant search failed, falling back to in-Python cosine search", {"error": str(err)})
        return await search_relevant_chunks(query, chat_id, top_k)


async def embed_query(query: str):
    return await generate_embedding(query)
