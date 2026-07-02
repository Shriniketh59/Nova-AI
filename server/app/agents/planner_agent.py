import json
import re

import httpx

from ..core.config import OLLAMA_URL, OLLAMA_MODEL
from ..services.task_router import classify_topic
from .base_agent import BaseAgent

PLANNER_SYSTEM_PROMPT = """You are the Planner stage of a critical-thinking AI pipeline.
Given a user question, decide HOW to answer it well, before any answer is generated.

Reply with ONLY a JSON object, no other text:
{
  "intent": "<one sentence: what the user actually wants>",
  "taskType": "factual" | "comparison" | "howto" | "opinion" | "code" | "greeting" | "other",
  "category": "biography" | "politics" | "coding" | "algorithms" | "medical" | "legal" | "finance" | "news" | "research" | "document_analysis" | "general",
  "steps": ["step 1", "step 2", ...],
  "needsDocRetrieval": true|false,
  "needsWebSearch": true|false
}

Rules:
- "greeting" or trivial small talk: steps should be minimal (1 step), needsDocRetrieval=false, needsWebSearch=false, category="general".
- "comparison" tasks: steps must cover each thing being compared separately, then a synthesis step.
- category drives which sources are trusted and whether facts get cross-checked — pick the closest match, "general" only when nothing else fits.
- Keep steps to 3-6 items, each a short actionable phrase."""

VALID_CATEGORIES = {
    "biography", "politics", "coding", "algorithms", "medical", "legal",
    "finance", "news", "research", "document_analysis", "general",
}

_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}")

# classify_topic()'s categories aren't a 1:1 match with the planner's
# VALID_CATEGORIES (no "math"/"chat" there, but "politics"/"finance"/
# "algorithms"/"document_analysis" have no classify_topic equivalent) — map
# the ones that do overlap so an LLM-planner failure still gets a real
# category instead of silently downgrading to "general" (which would bypass
# contested-fact trust checks in confidence_engine.py).
_TOPIC_TO_CATEGORY = {
    "coding": "coding",
    "math": "general",
    "medical": "medical",
    "legal": "legal",
    "biography": "biography",
    "news": "news",
    "research": "research",
    "chat": "general",
}


def _fallback_plan(question: str) -> dict:
    category = _TOPIC_TO_CATEGORY.get(classify_topic(question), "general")
    return {
        "intent": question,
        "taskType": "other",
        "category": category,
        "steps": ["Retrieve relevant evidence", "Reason about the evidence", "Generate answer"],
        "needsDocRetrieval": True,
        "needsWebSearch": True,
    }


def _parse_plan(raw: str, question: str) -> dict:
    match = _JSON_OBJ_RE.search(raw)
    if not match:
        return _fallback_plan(question)
    try:
        parsed = json.loads(match.group(0))
        return {
            "intent": parsed.get("intent") or question,
            "taskType": parsed.get("taskType") or "other",
            "category": parsed.get("category") if parsed.get("category") in VALID_CATEGORIES else "general",
            "steps": parsed.get("steps") if isinstance(parsed.get("steps"), list) and parsed.get("steps") else ["Answer the question directly"],
            "needsDocRetrieval": parsed.get("needsDocRetrieval") is not False,
            "needsWebSearch": parsed.get("needsWebSearch") is not False,
        }
    except Exception:
        return _fallback_plan(question)


class PlannerAgent(BaseAgent):
    """First stage of the critical-thinking pipeline: Question -> Intent
    Analysis -> Task Classification -> reasoning plan -> tool decisions."""

    def __init__(self):
        super().__init__("PlannerAgent")

    async def run(self, question: str, context: dict | None = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                res = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "stream": False,
                        "options": {"temperature": 0.1},
                        "messages": [
                            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                            {"role": "user", "content": question},
                        ],
                    },
                )
                if res.status_code >= 400:
                    raise RuntimeError(f"Planner LLM call failed: {res.status_code}")

                data = res.json()
                raw = (data.get("message") or {}).get("content", "")
                plan = _parse_plan(raw, question)
                return {"success": True, "output": plan}
        except Exception as err:
            return {"success": True, "output": _fallback_plan(question), "error": str(err)}
