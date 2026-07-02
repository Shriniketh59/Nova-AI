def dedupe_chunks(chunks: list[dict]) -> list[dict]:
    """Removes near-duplicate chunks (same leading text) that retrieval
    sometimes returns when a document has repeated boilerplate or overlapping chunks."""
    seen = set()
    out = []
    for chunk in chunks:
        key = chunk["content"].strip()[:200]
        if key in seen:
            continue
        seen.add(key)
        out.append(chunk)
    return out


def compress_context(chunks: list[dict], max_chars: int) -> list[dict]:
    """Keeps adding chunks (already sorted by relevance) until the context
    budget is used up, instead of sending every retrieved chunk to the LLM."""
    used = 0
    kept = []
    for chunk in chunks:
        if used + len(chunk["content"]) > max_chars:
            break
        kept.append(chunk)
        used += len(chunk["content"])
    return kept


def estimate_tokens(text: str) -> int:
    return -(-len(text or "") // 4)  # ceil division
