from ..core.config import OLLAMA_MODEL
from ..utils.completion_guard import generate_with_continuation
from .base_agent import BaseAgent

MAX_DOC_CHARS = 4000

SYSTEM_PROMPT = """You are Nova AI's Document Comparison Agent. You are given two documents and must compare them directly — never substitute outside knowledge for either document's actual content.

Reply with this exact markdown structure:
## Agreements
Bullet list of points both documents state consistently.
## Differences
Bullet list of points where the documents disagree or one states something the other doesn't, naming which document says what.
## Summary
One paragraph: the overall relationship between the two documents (e.g. one supersedes the other, they cover different scope, they conflict on a key point)."""


def _truncate(text: str) -> str:
    return f"{text[:MAX_DOC_CHARS]}\n[...truncated]" if len(text) > MAX_DOC_CHARS else text


class DocumentComparisonAgent(BaseAgent):
    """Document-grounded comparison (the "compare these documents" request).
    Bypasses web search: Uploaded Document > Web Search whenever a file is attached."""

    def __init__(self):
        super().__init__("DocumentComparisonAgent")

    async def run(self, query: str, context: dict | None = None) -> dict:
        context = context or {}
        documents = context.get("documents", [])  # [{fileName, text}, ...]
        if len(documents) < 2:
            return {"success": True, "output": {"answer": "Comparison needs at least two uploaded documents in this chat — only one was found."}}

        doc_a, doc_b = documents[-2:]
        prompt = (
            f"Document A ({doc_a['fileName']}):\n{_truncate(doc_a['text'])}\n\n"
            f"Document B ({doc_b['fileName']}):\n{_truncate(doc_b['text'])}\n\nRequest: {query}"
        )

        try:
            answer = await generate_with_continuation(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=OLLAMA_MODEL,
                num_predict=1500,
                temperature=0.3,
            )
            return {"success": True, "output": {"answer": answer, "comparedFiles": [doc_a["fileName"], doc_b["fileName"]]}}
        except Exception as err:
            return {"success": False, "output": {"answer": ""}, "error": str(err)}
