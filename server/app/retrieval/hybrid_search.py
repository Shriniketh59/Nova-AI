import asyncio

from .semantic_search import semantic_search
from .keyword_search import keyword_search

RRF_K = 60  # standard reciprocal-rank-fusion constant


async def hybrid_search(query: str, chat_id: str, top_k: int = 10) -> list[dict]:
    """Fuses semantic (embedding cosine) and keyword (lexical) result lists via
    Reciprocal Rank Fusion: a chunk's score is the sum of 1/(k+rank) across
    whichever list(s) it appears in."""
    semantic_results, keyword_results = await asyncio.gather(
        semantic_search(query, chat_id, top_k * 2),
        keyword_search(query, chat_id, top_k * 2),
    )

    fused: dict = {}

    for rank, chunk in enumerate(semantic_results):
        rrf = 1 / (RRF_K + rank + 1)
        fused[chunk["id"]] = {**chunk, "hybridScore": rrf, "similarity": chunk.get("similarity")}

    for rank, chunk in enumerate(keyword_results):
        rrf = 1 / (RRF_K + rank + 1)
        existing = fused.get(chunk["id"])
        if existing:
            existing["hybridScore"] += rrf
            existing["keywordScore"] = chunk["keywordScore"]
        else:
            fused[chunk["id"]] = {**chunk, "hybridScore": rrf}

    merged = list(fused.values())
    merged.sort(key=lambda c: c["hybridScore"], reverse=True)
    return merged[:top_k]
