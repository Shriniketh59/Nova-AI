CONTESTED_FACT_CATEGORIES = {"biography", "politics", "medical", "legal", "finance", "news"}

# NOTE on scope: this is CATEGORY-based confidence scoring (source count,
# contradiction count, contested-topic capping), not per-claim fact
# verification. It does not extract individual claims/entities/dates from the
# answer and check each against evidence — it estimates overall answer
# reliability from retrieval signals. Do not present this as claim-level
# fact-checking in docs/UI copy.
def compute_answer_confidence(
    source_count: int = 0,
    contradictions: list | None = None,
    doc_confidence: dict | None = None,
    has_web_sources: bool = False,
    trust_tiers: dict | None = None,
    category: str = "general",
) -> dict:
    contradictions = contradictions or []

    if source_count == 0:
        return {"score": 0, "label": "low", "reason": "No supporting sources found."}

    score = 30
    score += min(source_count, 6) * 8
    if doc_confidence and doc_confidence.get("label") == "high":
        score += 10
    if has_web_sources:
        score += 5
    score -= len(contradictions) * 20

    is_contested = category in CONTESTED_FACT_CATEGORIES
    has_trusted_source = bool(trust_tiers and (trust_tiers.get("official", 0) > 0 or trust_tiers.get("reference", 0) > 0))
    if is_contested and not has_trusted_source:
        score = min(score, 65)

    score = max(0, min(100, score))
    label = "high" if score >= 70 else "medium" if score >= 30 else "low"

    if contradictions:
        reason = f"{len(contradictions)} source conflict(s) detected — sources disagree on a specific fact."
    elif is_contested and has_trusted_source:
        reason = "Supported by official or reference sources."
    elif is_contested and not has_trusted_source:
        reason = "No official or reference sources found for this claim — only community/blog sources available."
    else:
        reason = f"{source_count} supporting source(s) found."

    return {"score": score, "label": label, "reason": reason}
