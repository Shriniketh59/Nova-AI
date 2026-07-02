import json
import re
import httpx

from ..core.config import OLLAMA_URL, OLLAMA_MODEL

EXPANSION_TIMEOUT_S = 4.0
_ARRAY_RE = re.compile(r"\[[\s\S]*\]")


async def expand_query(query: str) -> list[str]:
    """Asks the LLM for 2 alternate phrasings/sub-questions of the user query,
    so retrieval also runs against wording the user didn't use. Bounded by a
    short timeout with empty-list fallback — expansion is a recall booster,
    never allowed to block or fail the main retrieval path."""
    try:
        async with httpx.AsyncClient(timeout=EXPANSION_TIMEOUT_S) as client:
            res = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 100},
                    "messages": [{
                        "role": "user",
                        "content": (
                            "Rewrite this question as 2 alternate phrasings that preserve its "
                            "meaning, for search recall. Reply with ONLY a JSON array of 2 strings, "
                            f"nothing else.\n\nQuestion: {query}"
                        ),
                    }],
                },
            )
            if res.status_code >= 400:
                return []
            data = res.json()
            raw = (data.get("message") or {}).get("content", "")
            match = _ARRAY_RE.search(raw)
            if not match:
                return []
            parsed = json.loads(match.group(0))
            if not isinstance(parsed, list):
                return []
            return [s for s in parsed if isinstance(s, str) and s.strip()][:2]
    except Exception:
        return []
