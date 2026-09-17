import asyncio
from typing import List, Optional

from .keyword_search import keyword_search
from .semantic_search import semantic_search
from .web_retriever import get_web_retriever

RRF_K = 60  # Standard Reciprocal Rank Fusion constant


async def hybrid_search(
    query: str,
    chat_id: str = "",
    top_k: int = 10,
    query_vector: Optional[list[float]] = None,
    filters: Optional[dict] = None,
    include_web: bool = False,
    user_id: Optional[str] = None,
) -> list[dict]:
    """Parallel hybrid retrieval executing Dense Semantic Search, Sparse BM25 Search,
    and Fresh Web Retrieval concurrently with Reciprocal Rank Fusion (RRF)."""
    tasks = [
        semantic_search(query, chat_id, top_k * 2, query_vector=query_vector, filters=filters, user_id=user_id),
        keyword_search(query, chat_id, top_k * 2, filters=filters),
    ]

    if include_web:
        retriever = get_web_retriever()
        tasks.append(retriever.search(query, max_results=max(3, top_k // 2)))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    semantic_results = results[0] if not isinstance(results[0], Exception) else []
    keyword_results = results[1] if not isinstance(results[1], Exception) else []
    web_results = results[2] if len(results) > 2 and not isinstance(results[2], Exception) else []

    fused: dict[str, dict] = {}

    # 1. Fuse Dense Semantic Results
    for rank, chunk in enumerate(semantic_results):
        c_id = str(chunk.get("id") or f"dense_{rank}")
        rrf = 1.0 / (RRF_K + rank + 1)
        fused[c_id] = {
            **chunk,
            "id": c_id,
            "hybridScore": rrf,
            "similarity": chunk.get("similarity", 0.0),
            "source_type": chunk.get("source_type", "document"),
        }

    # 2. Fuse Sparse BM25 Results
    for rank, chunk in enumerate(keyword_results):
        c_id = str(chunk.get("id") or f"sparse_{rank}")
        rrf = 1.0 / (RRF_K + rank + 1)
        if c_id in fused:
            fused[c_id]["hybridScore"] += rrf
            fused[c_id]["keywordScore"] = chunk.get("keywordScore", 0.0)
        else:
            fused[c_id] = {
                **chunk,
                "id": c_id,
                "hybridScore": rrf,
                "keywordScore": chunk.get("keywordScore", 0.0),
                "similarity": 0.0,
                "source_type": chunk.get("source_type", "document"),
            }

    # 3. Fuse Fresh Web Results (temporary retrieval context)
    for rank, web_item in enumerate(web_results):
        web_dict = web_item.to_dict() if hasattr(web_item, "to_dict") else dict(web_item)
        c_id = f"web_{rank}_{hash(web_dict.get('url', '')) % 100000}"
        rrf = 1.0 / (RRF_K + rank + 1)
        fused[c_id] = {
            "id": c_id,
            "content": web_dict.get("content", ""),
            "original_filename": web_dict.get("title") or "Web Search",
            "title": web_dict.get("title") or "Web Search",
            "source_url": web_dict.get("url"),
            "source_domain": web_dict.get("source_domain", "web"),
            "source_type": "web",
            "published_at": web_dict.get("published_at"),
            "similarity": web_dict.get("relevance_score", 0.6),
            "keywordScore": 0.5,
            "hybridScore": rrf,
            "is_web_result": True,
        }

    merged = list(fused.values())
    merged.sort(key=lambda c: c.get("hybridScore", 0.0), reverse=True)
    return merged[:top_k]
