"""Corrective-RAG relevance gate: grades retrieved chunks for relevance,
sufficiency, duplication, and staleness, and decides whether corrective
retrieval should run before evidence reaches generation. Reuses the
composite/freshness scoring already computed by freshness_scorer.py and the
dedup pass already run in retrieval_service.py — this module adds the
*decision* layer on top, not a second scoring system."""

import re

from ..core.config import RELEVANCE_THRESHOLD, STALENESS_HALF_LIFE_DAYS
from .freshness_scorer import calculate_freshness

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "to", "in", "on", "for",
    "and", "or", "but", "with", "about", "what", "when", "where", "who", "how",
    "why", "does", "do", "did", "it", "its", "this", "that", "these", "those",
    "be", "been", "has", "have", "had", "can", "will", "would", "should",
}
_FILLER_PREFIX_RE = re.compile(
    r"^\s*(please\s+|can\s+you\s+|could\s+you\s+|i\s+want\s+to\s+know\s+|i\s+need\s+to\s+know\s+|"
    r"tell\s+me\s+|i'd\s+like\s+to\s+know\s+)+",
    re.I,
)

MAX_DUPLICATE_CANDIDATES = 8
DUPLICATE_SIMILARITY_THRESHOLD = 0.97
STALE_FRESHNESS_THRESHOLD = 0.3


def _keywords(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "") if len(w) > 2} - _STOPWORDS


def rewrite_query(query: str) -> str:
    """Strips leading filler phrasing so a corrective retry searches on the
    actual information need rather than the conversational wrapper around it."""
    stripped = _FILLER_PREFIX_RE.sub("", query or "").strip()
    return stripped or query


def grade_relevance(query: str, chunks: list[dict]) -> list[dict]:
    """Labels each chunk relevant/marginal/irrelevant using its existing
    composite/similarity score plus a keyword-overlap cross-check, so a chunk
    that scores well only because of freshness/authority weighting (not
    actual topical match) still gets caught."""
    query_terms = _keywords(query)
    graded = []
    for c in chunks:
        score = c.get("composite_score")
        if score is None:
            score = c.get("similarity")
        if score is None:
            score = min(1.0, c.get("hybridScore", 0.0) * 25.0)

        overlap = 0.0
        if query_terms:
            chunk_terms = _keywords(c.get("content", ""))
            overlap = len(query_terms & chunk_terms) / len(query_terms)

        if c.get("is_web_result") or score >= RELEVANCE_THRESHOLD or overlap >= 0.15:
            label = "relevant"
        elif score >= RELEVANCE_THRESHOLD * 0.5 or overlap > 0:
            label = "marginal"
        else:
            label = "irrelevant"

        graded.append({**c, "relevance_label": label, "relevance_score": round(score, 4), "keyword_overlap": round(overlap, 4)})
    return graded


def filter_relevant(graded_chunks: list[dict]) -> list[dict]:
    """Drops irrelevant chunks before they reach context building; keeps
    marginal ones (still usable, just not strong)."""
    return [c for c in graded_chunks if c.get("relevance_label") != "irrelevant"]


def detect_insufficient(graded_chunks: list[dict], min_sources: int) -> tuple[bool, int]:
    usable = sum(1 for c in graded_chunks if c.get("relevance_label") != "irrelevant")
    return usable < min_sources, usable


async def detect_duplicates(chunks: list[dict]) -> tuple[list[dict], list[tuple[int, int, float]]]:
    """Near-duplicate detection via embedding cosine similarity (catches
    semantic duplicates dedupe_chunks' literal-prefix match misses), bounded
    to a handful of candidates to avoid O(n^2) cost on large evidence sets.
    Returns (deduped_chunks, dropped_pairs) — the later chunk in each
    duplicate pair is dropped, keeping the higher-ranked one."""
    from ..rag import generate_embedding, cosine_similarity

    if len(chunks) < 2:
        return chunks, []

    candidates = chunks[:MAX_DUPLICATE_CANDIDATES]
    embeddings = []
    for c in candidates:
        emb = c.get("embedding")
        if not emb:
            try:
                emb = await generate_embedding(c.get("content", ""))
            except Exception:
                emb = None
        embeddings.append(emb)

    dropped_pairs = []
    drop_idx = set()
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if j in drop_idx or not embeddings[i] or not embeddings[j]:
                continue
            sim = cosine_similarity(embeddings[i], embeddings[j])
            if sim >= DUPLICATE_SIMILARITY_THRESHOLD:
                dropped_pairs.append((i, j, round(sim, 4)))
                drop_idx.add(j)

    deduped = [c for idx, c in enumerate(candidates) if idx not in drop_idx] + chunks[MAX_DUPLICATE_CANDIDATES:]
    return deduped, dropped_pairs


def detect_stale(chunks: list[dict], category: str, freshness_matters_categories: set[str]) -> list[dict]:
    """Flags chunks whose freshness score falls below the staleness
    threshold, only for categories where recency actually matters — a
    decades-old textbook definition isn't 'stale', but a decades-old news
    snippet answering a current-events question is."""
    if category not in freshness_matters_categories:
        return []
    stale = []
    for c in chunks:
        freshness = c.get("freshness_score")
        if freshness is None:
            date_val = c.get("published_at") or c.get("updated_at") or c.get("created_at")
            freshness = calculate_freshness(date_val, half_life_days=STALENESS_HALF_LIFE_DAYS)
        if freshness < STALE_FRESHNESS_THRESHOLD:
            stale.append({"filename": c.get("original_filename") or c.get("title"), "freshness_score": freshness})
    return stale


def needs_correction(insufficient: bool, graded_chunks: list[dict], stale_items: list[dict]) -> bool:
    """Corrective retrieval is triggered by quality problems retrieval can
    actually fix — too few relevant sources, a majority-irrelevant result
    set, or stale evidence where freshness matters. Conflicts and duplicates
    are handled by filtering/disclosure downstream, not by re-retrieving
    (retrieving again won't resolve two sources disagreeing)."""
    if insufficient or stale_items:
        return True
    if graded_chunks:
        irrelevant_ratio = sum(1 for c in graded_chunks if c.get("relevance_label") == "irrelevant") / len(graded_chunks)
        if irrelevant_ratio >= 0.5:
            return True
    return False
