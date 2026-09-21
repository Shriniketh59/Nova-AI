import json
import re
from datetime import datetime, timezone

import httpx

from ..core.config import OLLAMA_URL, OLLAMA_MODEL, get_ollama_options
from ..rag import cosine_similarity, generate_embedding
from .base_agent import BaseAgent

NOT_FOUND_MESSAGE = "Reliable information was not found in the available sources."

CRITIQUE_SYSTEM_PROMPT = """You are the Review stage of a critical-thinking AI pipeline. You did not write this answer — your job is to critique it harshly against the evidence it was supposed to be based on.

Check for:
- Source support: does every claim trace back to the evidence, or is something made up?
- Logic consistency: does the reasoning hold together?
- Missing information: is something important from the evidence left out?
- Hallucination: any specific facts/numbers/names not actually in the evidence?
- Contradictions: does the answer address known source disagreements, or ignore them?
- Completeness: does the answer address every part of the question, not just one piece of a multi-part ask?
- Evidence sufficiency: is the evidence too thin to actually support a confident answer (should more sources be retrieved before answering)?
- Temporal accuracy: for elections, appointments, releases, or any dated event, does the evidence show it as UPCOMING, ONGOING, or COMPLETED? Flag it as an issue if the answer's tense doesn't match — e.g. describing an event with a known result as "expected to happen" or "upcoming" instead of stating the actual outcome. When both a forecast/exit-poll and an official result appear in the evidence, the answer must prefer the official result.

Reply with ONLY a JSON object:
{
  "pass": true|false,
  "issues": ["issue 1", ...],
  "needsMoreEvidence": true|false,
  "confidenceScore": 0-100,
  "confidenceReason": "<short reason, e.g. '8 sources agree' or '2 sources conflict, no resolution'>"
}"""

CODE_CRITIQUE_SYSTEM_PROMPT = """You are the Review stage for a coding answer. The code has already passed static validation (syntax, imports, undefined variables) — your job is to catch what static checks can't:

- Algorithm correctness: does the code actually solve the stated problem, including edge cases it claims to handle?
- Complexity accuracy: does the stated Time/Space Complexity match what the code's loops/recursion/data structures actually do?
- Logic bugs: off-by-one errors, wrong comparison operators, incorrect base cases, mutated-while-iterating bugs.

Reply with ONLY a JSON object:
{
  "pass": true|false,
  "issues": ["issue 1", ...],
  "needsMoreEvidence": false,
  "confidenceScore": 0-100,
  "confidenceReason": "<short reason>"
}"""

_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}")

NO_EVIDENCE_PREFIX = "No external evidence found"

# Lightweight (non-LLM) grounding check: pull out name-like tokens, dates, and
# numbers asserted in the answer and verify a reasonable share of them
# actually appear somewhere in the evidence text. This catches answers that
# state specific offices/names/dates the retrieved evidence never mentioned,
# without a second LLM call.
_CAPITALIZED_RE = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")
_NUMBER_RE = re.compile(r"\b\d{1,4}\b")
_SENTENCE_STARTERS = {
    "The", "This", "That", "These", "Those", "It", "In", "On", "At", "For", "With",
    "As", "However", "Additionally", "Overall", "According", "Based", "Note",
    "Direct", "Answer", "Detailed", "Explanation", "Key", "Findings", "Conclusion",
    "A", "An", "If", "So", "But", "And", "Question",
}
MIN_GROUNDING_RATIO = 0.4
MIN_CLAIM_TOKENS_TO_CHECK = 2


def _extract_claim_tokens(text: str) -> set[str]:
    tokens = set(_CAPITALIZED_RE.findall(text or "")) - _SENTENCE_STARTERS
    tokens |= set(_NUMBER_RE.findall(text or ""))
    return tokens


def _grounding_ratio(answer: str, evidence_summary: str) -> tuple[float, int]:
    """Returns (fraction of answer's claim-tokens found in the evidence, total claim-tokens checked)."""
    claim_tokens = _extract_claim_tokens(answer)
    if len(claim_tokens) < MIN_CLAIM_TOKENS_TO_CHECK:
        return 1.0, len(claim_tokens)
    evidence_lower = (evidence_summary or "").lower()
    present = sum(1 for t in claim_tokens if t.lower() in evidence_lower)
    return present / len(claim_tokens), len(claim_tokens)


def _no_evidence(evidence_summary: str) -> bool:
    return not evidence_summary or evidence_summary.strip().startswith(NO_EVIDENCE_PREFIX)


# Temporal-status mismatch: an answer using forecast/future language for an
# event the evidence already shows completed. This is the "described a
# completed election as upcoming" failure mode — catch it deterministically
# rather than relying on the LLM judge to always notice on its own.
_FUTURE_LANGUAGE_RE = re.compile(
    r"\b(will\s+(be|take\s+place|happen|occur)|is\s+(expected|set|scheduled|slated|predicted|forecast)\s+to|"
    r"upcoming|is\s+likely\s+to|projected\s+to|due\s+to\s+(happen|occur|take\s+place))\b",
    re.I,
)
_COMPLETION_EVIDENCE_RE = re.compile(
    r"\b(won|winner|elected|re-elected|appointed|sworn\s+in|inaugurated|announced|declared|"
    r"result[s]?\s+(were|was|announced|declared)|concluded|held\s+on|took\s+place\s+on|final\s+result)\b",
    re.I,
)


def _temporal_mismatch(answer: str, evidence_summary: str) -> bool:
    """True when the answer talks about an event in future/forecast terms
    while the evidence describes it as already resolved."""
    if not _FUTURE_LANGUAGE_RE.search(answer or ""):
        return False
    return bool(_COMPLETION_EVIDENCE_RE.search(evidence_summary or ""))


def _parse_critique(raw: str) -> dict:
    fallback = {"pass": True, "issues": [], "needsMoreEvidence": False, "confidenceScore": 50, "confidenceReason": "Could not parse review output"}
    match = _JSON_OBJ_RE.search(raw)
    if not match:
        return fallback
    try:
        parsed = json.loads(match.group(0))
        return {
            "pass": parsed.get("pass") is not False,
            "issues": parsed.get("issues") if isinstance(parsed.get("issues"), list) else [],
            "needsMoreEvidence": parsed.get("needsMoreEvidence") is True,
            "confidenceScore": parsed.get("confidenceScore") if isinstance(parsed.get("confidenceScore"), (int, float)) else 50,
            "confidenceReason": parsed.get("confidenceReason") or "",
        }
    except Exception:
        return fallback


MAX_CONFLICT_CANDIDATES = 5
# Two chunks about the same topic have HIGH cosine similarity — near-identical
# sentences differing only in one fact (e.g. "the deadline is March 1" vs
# "the deadline is April 1") embed close together, not far apart. So "far
# apart embeddings" is the wrong signal for conflicting facts; it only
# catches chunks that are off-topic from each other, which isn't a conflict.
TOPIC_SIMILARITY_THRESHOLD = 0.5


async def _detect_conflict(chunks: list[dict]) -> dict:
    """Two chunks from different files that are clearly about the same topic
    (high embedding similarity — same subject/entity) but assert different
    specific facts (their extracted name/date/number claim-tokens diverge)
    are a proxy for conflicting information.

    Chunks coming back from the vector-store-backed retrieval path (Chroma,
    the default backend) never carry a raw "embedding" field — only the
    in-memory/Postgres fallback path does. Without an on-demand fallback,
    conflict detection was silently a no-op whenever Chroma answered the
    query, i.e. in production. generate_embedding is cached, so this costs a
    real Ollama call only the first time a given chunk's text is seen, and is
    bounded to a handful of top, distinct-file candidates."""
    distinct_file_chunks = []
    seen_files = set()
    for c in chunks:
        if not c.get("content") or c.get("original_filename") in seen_files:
            continue
        seen_files.add(c["original_filename"])
        distinct_file_chunks.append(c)
        if len(distinct_file_chunks) >= MAX_CONFLICT_CANDIDATES:
            break

    embeddings = []
    for c in distinct_file_chunks:
        emb = c.get("embedding")
        if not emb:
            try:
                emb = await generate_embedding(c["content"])
            except Exception:
                emb = None
        embeddings.append(emb)

    for i in range(len(distinct_file_chunks)):
        for j in range(i + 1, len(distinct_file_chunks)):
            if not embeddings[i] or not embeddings[j]:
                continue
            sim = cosine_similarity(embeddings[i], embeddings[j])
            if sim < TOPIC_SIMILARITY_THRESHOLD:
                continue  # not even about the same thing — no conflict to surface

            tokens_i = _extract_claim_tokens(distinct_file_chunks[i]["content"])
            tokens_j = _extract_claim_tokens(distinct_file_chunks[j]["content"])
            diff = (tokens_i ^ tokens_j)  # symmetric difference: facts asserted by one but not the other
            if diff:
                return {
                    "found": True,
                    "detail": (
                        f"{distinct_file_chunks[i]['original_filename']} vs "
                        f"{distinct_file_chunks[j]['original_filename']} (differing facts: {', '.join(sorted(diff))})"
                    ),
                }
    return {"found": False, "detail": None}


class ValidationAgent(BaseAgent):
    """Final decision-making step: Question -> Retrieve -> Validate -> Compare
    -> Generate -> Review -> Return."""

    def __init__(self):
        super().__init__("ValidationAgent")

    async def run(self, answer: str, context: dict | None = None) -> dict:
        context = context or {}
        chunks = context.get("chunks", [])
        sources = context.get("sources", [])
        confidence = context.get("confidence", {"score": 0, "label": "low"})

        if confidence.get("label") == "low" or not chunks:
            return {
                "success": True,
                "output": {"answer": NOT_FOUND_MESSAGE, "evidence": sources, "confidence": confidence, "conflict": False},
            }

        conflict = await _detect_conflict(chunks)

        final_answer = answer
        if conflict["found"]:
            final_answer = f"{answer}\n\nNote: sources disagree on this point ({conflict['detail']}) — treat with caution."

        return {
            "success": True,
            "output": {
                "answer": final_answer,
                "evidence": sources,
                "confidence": confidence,
                "conflict": conflict["found"],
                "conflictDetail": conflict["detail"] if conflict["found"] else None,
            },
        }

    async def critique(self, answer: str, question: str, evidence_summary: str = "", contradictions: list | None = None, domain: str = "document") -> dict:
        """Real LLM-judge critique for the critical-thinking pipeline (ToolAgent)."""
        contradictions = contradictions or []
        is_code = domain == "code"

        # Fast heuristic gates — run before any LLM call, never block on them
        # taking longer than a regex pass. Both cases get the same treatment
        # as "no_evidence": low confidence + needsMoreEvidence, so ToolAgent's
        # existing escalate-then-fail loop handles them without new plumbing.
        if not is_code:
            if _no_evidence(evidence_summary):
                return {
                    "pass": False,
                    "issues": ["no_evidence: no external evidence was retrieved to support a factual claim"],
                    "needsMoreEvidence": True,
                    "confidenceScore": 15,
                    "confidenceReason": "No evidence retrieved — claims cannot be verified.",
                }
            ratio, total_claims = _grounding_ratio(answer, evidence_summary)
            if total_claims >= MIN_CLAIM_TOKENS_TO_CHECK and ratio < MIN_GROUNDING_RATIO:
                return {
                    "pass": False,
                    "issues": [
                        f"ungrounded_claims: only {ratio:.0%} of the names/dates/numbers asserted in the "
                        f"answer appear in the retrieved evidence"
                    ],
                    "needsMoreEvidence": True,
                    "confidenceScore": 20,
                    "confidenceReason": f"Answer entities not well-supported by evidence ({ratio:.0%} grounded).",
                }
            if _temporal_mismatch(answer, evidence_summary):
                return {
                    "pass": False,
                    "issues": [
                        "temporal_mismatch: answer describes the event in future/forecast terms, "
                        "but the evidence shows it has already been resolved (result/appointment/announcement) — "
                        "state the actual outcome, not a prediction"
                    ],
                    "needsMoreEvidence": False,
                    "confidenceScore": 25,
                    "confidenceReason": "Answer tense conflicts with evidence showing the event already completed.",
                }

        if is_code:
            user_content = f"Question: {question}\n\nCode answer to review:\n{answer}"
        else:
            disagreements = ", ".join(f"{c['sourceA']} vs {c['sourceB']}" for c in contradictions) if contradictions else "none"
            user_content = (
                f"Question: {question}\n\nEvidence:\n{evidence_summary}\n\n"
                f"Known source disagreements: {disagreements}\n\nAnswer to review:\n{answer}"
            )

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                res = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "stream": False,
                        "options": get_ollama_options({"temperature": 0.1}),
                        "messages": [
                            {"role": "system", "content": CODE_CRITIQUE_SYSTEM_PROMPT if is_code else CRITIQUE_SYSTEM_PROMPT},
                            {"role": "user", "content": user_content},
                        ],
                    },
                )
                if res.status_code >= 400:
                    raise RuntimeError(f"Review LLM call failed: {res.status_code}")
                data = res.json()
                raw = (data.get("message") or {}).get("content", "")
                result = _parse_critique(raw)
        except Exception as err:
            result = {"pass": True, "issues": [], "needsMoreEvidence": False, "confidenceScore": 50, "confidenceReason": f"Review unavailable: {err}"}

        # Sources disagreeing shouldn't be silently blocked, but the answer
        # must not read as confidently settled — surface it in the reasoning
        # and cap confidence instead of failing the answer outright.
        if not is_code and contradictions:
            result["confidenceScore"] = min(result.get("confidenceScore", 50), 55)
            disputed_note = "Sources disagree on key facts — treat as disputed/uncertain."
            existing_reason = result.get("confidenceReason") or ""
            result["confidenceReason"] = f"{existing_reason} {disputed_note}".strip()

        return result
