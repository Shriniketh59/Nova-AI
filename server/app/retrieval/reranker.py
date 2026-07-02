from ..rag import cosine_similarity

MMR_LAMBDA = 0.7  # weight toward relevance vs diversity


async def rerank(query_vector: list[float], candidates: list[dict], top_k: int = 8) -> list[dict]:
    """No cross-encoder model is available locally (CPU-only Ollama box), so
    this reranks using Maximal Marginal Relevance over the embeddings already
    computed during retrieval."""
    if not candidates:
        return []

    pool = [
        {**c, "relevance": cosine_similarity(query_vector, c["embedding"]) if c.get("embedding") else c.get("hybridScore", 0)}
        for c in candidates
    ]

    selected: list[dict] = []
    remaining = list(pool)

    while len(selected) < top_k and remaining:
        best_idx = 0
        best_score = float("-inf")

        for i, candidate in enumerate(remaining):
            if not selected:
                max_sim_to_selected = 0
            else:
                max_sim_to_selected = max(
                    (
                        cosine_similarity(candidate["embedding"], s["embedding"])
                        if candidate.get("embedding") and s.get("embedding")
                        else 0
                    )
                    for s in selected
                )
            mmr_score = MMR_LAMBDA * candidate["relevance"] - (1 - MMR_LAMBDA) * max_sim_to_selected
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i

        picked = remaining.pop(best_idx)
        selected.append({**picked, "rerankScore": best_score})

    return selected
