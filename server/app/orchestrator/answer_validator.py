"""Lightweight post-generation grounding check — voice path only.

Text chat now runs through ValidationAgent.critique()'s hard-gated
corrective pipeline (see local_orchestrator.orchestrate_stream, step 5),
which blocks/regenerates on ungrounded answers instead of only logging. This
module remains the check for the voice path, which stays on a fast
single-pass generation: a live spoken turn can't absorb a corrective-
retrieval/regeneration loop without breaking the conversational cadence, so
it keeps this deliberately *advisory* check instead — it logs a warning and
returns a verdict, but never blocks or rewrites an answer. The goal is
observability — surfacing the two failure modes that matter for a
retrieval-grounded assistant:

  1. Evidence was retrieved, but the answer ignores it (possible fabrication
     despite having sources on hand).
  2. No evidence was found at all, yet the question asked for current or
     factual information and the answer states it confidently anyway.

This is heuristic on purpose. A second LLM pass to grade every voice answer
would roughly double latency on a small local box, which is the wrong trade
for a check whose output is a log line.
"""

import re
from dataclasses import dataclass, field

from ..core.config import MIN_EVIDENCE_OVERLAP
from ..core.logger import logger

# Questions whose answers depend on facts that change, or on a specific
# verifiable entity — the cases where an ungrounded answer is most dangerous.
FACTUAL_QUERY_RE = re.compile(
    r"\b("
    r"who\s+(is|was|are|were)|what\s+(is|was|are|were)|when\s+(is|was|did|does)|"
    r"where\s+(is|was|are)|how\s+(many|much|old|long|far)|"
    r"latest|current|currently|recent|recently|today|now|this\s+(year|month|week)|"
    r"price|cost|population|release[ds]?|version|ceo|president|winner|won|"
    r"score|statistics|stats|news"
    r")\b",
    re.I,
)

# Phrasing that signals the model knows it is uncertain. An ungrounded answer
# that hedges is behaving correctly, so it should not be flagged.
HEDGE_RE = re.compile(
    r"\b("
    r"i\s+(don'?t|do\s+not)\s+(know|have)|i'?m\s+not\s+(sure|certain)|"
    r"unable\s+to\s+(verify|confirm)|cannot\s+(verify|confirm)|"
    r"may\s+have\s+changed|might\s+be\s+outdated|as\s+of\s+my|"
    r"you\s+(should|may\s+want\s+to)\s+(check|verify)|please\s+verify|"
    r"i\s+couldn'?t\s+find|no\s+(information|data|sources?)\s+(was|were)?\s*(found|available)"
    r")\b",
    re.I,
)

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "is", "are", "was", "were", "be", "been",
    "of", "to", "in", "on", "for", "with", "as", "at", "by", "from", "that", "this",
    "these", "those", "it", "its", "has", "have", "had", "will", "would", "can",
    "could", "should", "may", "might", "you", "your", "they", "their", "not", "also",
    "which", "what", "when", "where", "who", "how", "why", "than", "then", "there",
    "here", "into", "about", "more", "most", "some", "such", "other", "over", "each",
}



@dataclass
class ValidationResult:
    grounded: bool
    had_evidence: bool
    is_factual_query: bool
    overlap_ratio: float
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.warnings


def _content_words(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z0-9][a-zA-Z0-9\-]{2,}", (text or "").lower())
    return {t for t in tokens if t not in STOPWORDS}


def validate_answer(
    query: str,
    answer: str,
    evidence_text: str = "",
    web_sources: list[dict] | None = None,
    is_voice: bool = False,
) -> ValidationResult:
    """Check whether `answer` is visibly grounded in the evidence retrieved for
    `query`. Advisory only — logs warnings, never blocks."""
    web_sources = web_sources or []

    evidence_parts = [evidence_text or ""]
    for source in web_sources:
        evidence_parts.append(f"{source.get('title', '')} {source.get('snippet', '')}")
    combined_evidence = " ".join(p for p in evidence_parts if p).strip()

    had_evidence = bool(combined_evidence)
    is_factual = bool(FACTUAL_QUERY_RE.search(query or ""))
    answer_words = _content_words(answer)

    overlap_ratio = 0.0
    if had_evidence and answer_words:
        evidence_words = _content_words(combined_evidence)
        if evidence_words:
            overlap_ratio = len(answer_words & evidence_words) / len(answer_words)

    warnings: list[str] = []
    grounded = True

    if had_evidence:
        # Very short answers ("Yes.", "About 12.") legitimately share few words
        # with their sources, so don't flag them.
        if len(answer_words) >= 12 and overlap_ratio < MIN_EVIDENCE_OVERLAP:
            grounded = False
            warnings.append(
                f"answer_ignores_retrieved_evidence (overlap={overlap_ratio:.2%} < "
                f"{MIN_EVIDENCE_OVERLAP:.0%})"
            )
    elif is_factual and answer_words:
        grounded = False
        if not HEDGE_RE.search(answer or ""):
            warnings.append("confident_factual_answer_without_any_evidence")

    result = ValidationResult(
        grounded=grounded,
        had_evidence=had_evidence,
        is_factual_query=is_factual,
        overlap_ratio=round(overlap_ratio, 4),
        warnings=warnings,
    )

    if warnings:
        logger.warn("orchestrator.answer_validation", {
            "warnings": warnings,
            "query_prefix": (query or "")[:60],
            "had_evidence": had_evidence,
            "is_factual_query": is_factual,
            "overlap_ratio": result.overlap_ratio,
            "answer_len": len(answer or ""),
            "web_source_count": len(web_sources),
            "is_voice": is_voice,
        })
    else:
        logger.info("orchestrator.answer_validation_ok", {
            "had_evidence": had_evidence,
            "overlap_ratio": result.overlap_ratio,
        })

    return result
