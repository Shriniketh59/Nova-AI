import re

import httpx

from ..core.config import OLLAMA_URL, MAX_CONTINUATIONS

REQUIRED_SECTIONS = ["Direct Answer", "Detailed Explanation", "Key Findings", "Conclusion"]

# Sentence-ending punctuation, or a trailing markdown/list artifact that's a
# legitimate stopping point (closing fence, list item, colon before a block).
_VALID_ENDING_RE = re.compile(r"[.!?…\"'`)\]}]\s*$|```\s*$|:\s*$")
# A line that looks like an abandoned mid-word/mid-token cutoff, e.g. ends
# with a dangling connective or an obviously incomplete clause.
_DANGLING_WORD_RE = re.compile(
    r"\b(and|or|but|the|a|an|to|of|in|on|with|is|are|was|were|that|which|because|so|if|for)\s*$",
    re.I,
)


def _ends_mid_sentence(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return False
    if _VALID_ENDING_RE.search(stripped):
        return False
    # Inside an open code fence, punctuation rules don't apply the same way —
    # let the fence-balance check handle that case instead.
    if len(re.findall(r"```", stripped)) % 2 != 0:
        return False
    if _DANGLING_WORD_RE.search(stripped):
        return True
    # No terminal punctuation at all on a reasonably long answer is a strong
    # signal of a mid-sentence cutoff.
    return len(stripped) > 40 and stripped[-1] not in ".!?…\"'`)]}:"


def is_truncated(text: str, done_reason: str | None = None, require_sections: bool = False) -> bool:
    if done_reason == "length":
        return True
    if len(re.findall(r"```", text)) % 2 != 0:
        return True
    if require_sections and any(s not in text for s in REQUIRED_SECTIONS):
        return True
    if _ends_mid_sentence(text):
        return True
    return False


def close_unbalanced_fences(text: str) -> str:
    fence_count = len(re.findall(r"```", text))
    return f"{text.rstrip()}\n```" if fence_count % 2 != 0 else text


async def generate_with_continuation(
    messages: list[dict],
    model: str,
    num_predict: int = 1500,
    temperature: float = 0.4,
    require_sections: bool = False,
) -> str:
    """Auto-continue: if the model hit the token cap, left a code block open,
    or skipped a required section, ask it to pick up exactly where it left
    off instead of returning a truncated answer."""
    answer = ""
    convo = list(messages)

    async with httpx.AsyncClient(timeout=180) as client:
        for _ in range(MAX_CONTINUATIONS + 1):
            res = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": num_predict},
                    "messages": convo,
                },
            )
            if res.status_code >= 400:
                raise RuntimeError(f"Generation call failed: {res.status_code}")

            data = res.json()
            piece = (data.get("message") or {}).get("content", "")
            answer += piece
            done_reason = data.get("done_reason", "stop")

            if not is_truncated(answer, done_reason, require_sections):
                return answer

            convo = [
                *convo,
                {"role": "assistant", "content": piece},
                {"role": "user", "content": "Continue exactly where you left off. Do not repeat anything already written, do not restart the answer."},
            ]

    return close_unbalanced_fences(answer)
