import re
from typing import List, Optional
from ..rag import cosine_similarity

MMR_LAMBDA = 0.7  # weight toward relevance vs diversity


def _token_jaccard(text_a: str, text_b: str) -> float:
    set_a = set(re.findall(r"\w+", text_a.lower()))
    set_b = set(re.findall(r"\w+", text_b.lower()))
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


async def rerank(query_vector: Optional[list[float]], candidates: List[dict], top_k: int = 8) -> List[dict]:
    """Lightweight MMR reranker combining semantic/composite relevance and inter-chunk
    diversity. Operates efficiently without loading expensive local cross-encoders."""
    if not candidates:
        return []

    pool = []
    for c in candidates:
        # If composite_score is present from freshness_scorer, use it; otherwise compute cosine
        if "composite_score" in c:
            rel = float(c["composite_score"])
        elif query_vector and c.get("embedding"):
            rel = float(cosine_similarity(query_vector, c["embedding"]))
        else:
            rel = float(c.get("hybridScore", 0.0) * 10.0 or c.get("similarity", 0.0))

        pool.append({**c, "relevance": rel})

    selected: List[dict] = []
    remaining = list(pool)

    while len(selected) < top_k and remaining:
        best_idx = 0
        best_score = float("-inf")

        for i, candidate in enumerate(remaining):
            if not selected:
                max_sim = 0.0
            else:
                max_sim = 0.0
                for s in selected:
                    if candidate.get("embedding") and s.get("embedding"):
                        sim = cosine_similarity(candidate["embedding"], s["embedding"])
                    else:
                        sim = _token_jaccard(candidate.get("content", ""), s.get("content", ""))
                    if sim > max_sim:
                        max_sim = sim

            mmr_score = MMR_LAMBDA * candidate["relevance"] - (1.0 - MMR_LAMBDA) * max_sim
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i

        picked = remaining.pop(best_idx)
        selected.append({**picked, "rerankScore": round(best_score, 4)})

    return selected
