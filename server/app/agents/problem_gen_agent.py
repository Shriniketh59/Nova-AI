import json
import re

import httpx

from ..core.config import OLLAMA_URL, OLLAMA_CODE_MODEL
from .base_agent import BaseAgent

PROBLEM_SYSTEM_PROMPT = """You are a coding-interview problem author. Given a category and difficulty, invent ONE original DSA/algorithm problem (not a word-for-word copy of a famous one, but inspired by the category).

Reply with ONLY a JSON object, no other text:
{
  "title": "<short problem title>",
  "description": "<1-3 paragraph problem statement, precise about input/output>",
  "constraints": "<bullet-style constraints as a single string, e.g. '1 <= n <= 10^5; -10^9 <= arr[i] <= 10^9'>",
  "example_input": "<one concrete example input>",
  "example_output": "<the corresponding correct output>"
}

Keep it solvable and unambiguous — a candidate should be able to start coding immediately from this statement alone."""

_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}")


def _fallback_problem(category: str, difficulty: str) -> dict:
    return {
        "title": f"{category.title()} Practice Problem ({difficulty})",
        "description": (
            f"Given an input relevant to {category}, write a solution appropriate for a {difficulty} "
            "difficulty coding interview. (The problem generator couldn't reach the model — try 'New Problem' again.)"
        ),
        "constraints": "Not specified.",
        "example_input": "N/A",
        "example_output": "N/A",
    }


def _parse_problem(raw: str, category: str, difficulty: str) -> dict:
    match = _JSON_OBJ_RE.search(raw)
    if not match:
        return _fallback_problem(category, difficulty)
    try:
        parsed = json.loads(match.group(0))
        return {
            "title": parsed.get("title") or f"{category.title()} Problem",
            "description": parsed.get("description") or "",
            "constraints": parsed.get("constraints"),
            "example_input": parsed.get("example_input"),
            "example_output": parsed.get("example_output"),
        }
    except Exception:
        return _fallback_problem(category, difficulty)


class ProblemGenAgent(BaseAgent):
    """Invents a fresh DSA/coding-interview problem for a given category +
    difficulty, on request — feeds the Interview Coach practice page."""

    def __init__(self):
        super().__init__("ProblemGenAgent")

    async def run(self, category: str, difficulty: str = "medium") -> dict:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                res = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_CODE_MODEL,
                        "stream": False,
                        "options": {"temperature": 0.7},
                        "messages": [
                            {"role": "system", "content": PROBLEM_SYSTEM_PROMPT},
                            {"role": "user", "content": f"Category: {category}\nDifficulty: {difficulty}"},
                        ],
                    },
                )
                if res.status_code >= 400:
                    raise RuntimeError(f"Problem generation LLM call failed: {res.status_code}")

                data = res.json()
                raw = (data.get("message") or {}).get("content", "")
                problem = _parse_problem(raw, category, difficulty)
                return {"success": True, "output": problem}
        except Exception as err:
            return {"success": True, "output": _fallback_problem(category, difficulty), "error": str(err)}
