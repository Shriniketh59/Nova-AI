import json
import re

import httpx

from ..core.config import OLLAMA_URL, OLLAMA_MODEL
from ..rag import cosine_similarity
from .base_agent import BaseAgent

NOT_FOUND_MESSAGE = "Reliable information was not found in the available sources."
CONFLICT_SIMILARITY_THRESHOLD = 0.3

CRITIQUE_SYSTEM_PROMPT = """You are the Review stage of a critical-thinking AI pipeline. You did not write this answer — your job is to critique it harshly against the evidence it was supposed to be based on.

Check for:
- Source support: does every claim trace back to the evidence, or is something made up?
- Logic consistency: does the reasoning hold together?
- Missing information: is something important from the evidence left out?
- Hallucination: any specific facts/numbers/names not actually in the evidence?
- Contradictions: does the answer address known source disagreements, or ignore them?
- Completeness: does the answer address every part of the question, not just one piece of a multi-part ask?
- Evidence sufficiency: is the evidence too thin to actually support a confident answer (should more sources be retrieved before answering)?

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


def _detect_conflict(chunks: list[dict]) -> dict:
    """Two chunks from different files that both scored above the retrieval
    threshold for the same query, but whose embeddings are far apart, are
    "on-topic but divergent" — a proxy for conflicting information."""
    distinct_file_chunks = []
    seen_files = set()
    for c in chunks:
        if not c.get("embedding") or c.get("original_filename") in seen_files:
            continue
        seen_files.add(c["original_filename"])
        distinct_file_chunks.append(c)

    for i in range(len(distinct_file_chunks)):
        for j in range(i + 1, len(distinct_file_chunks)):
            sim = cosine_similarity(distinct_file_chunks[i]["embedding"], distinct_file_chunks[j]["embedding"])
            if sim < CONFLICT_SIMILARITY_THRESHOLD:
                return {
                    "found": True,
                    "detail": f"{distinct_file_chunks[i]['original_filename']} vs {distinct_file_chunks[j]['original_filename']}",
                }
    return {"found": False, "detail": None}


class ReviewAgent(BaseAgent):
    """Final decision-making step: Question -> Retrieve -> Validate -> Compare
    -> Generate -> Review -> Return."""

    def __init__(self):
        super().__init__("ReviewAgent")

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

        conflict = _detect_conflict(chunks)

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
        """Real LLM-judge critique for the critical-thinking pipeline (SupervisorAgent)."""
        contradictions = contradictions or []
        is_code = domain == "code"
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
                        "options": {"temperature": 0.1},
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
                return _parse_critique(raw)
        except Exception as err:
            return {"pass": True, "issues": [], "needsMoreEvidence": False, "confidenceScore": 50, "confidenceReason": f"Review unavailable: {err}"}
