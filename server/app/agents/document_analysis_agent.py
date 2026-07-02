import httpx

from ..core.config import OLLAMA_URL, OLLAMA_MODEL
from .base_agent import BaseAgent

SYSTEM_PROMPT = """You are Nova AI's Document Analysis Agent.
Analyze ONLY the document content provided below. Never reference external websites, tools, or generic advice not grounded in this document.
If the document doesn't contain enough information to answer, say so explicitly — never fabricate or substitute web knowledge."""


class DocumentAnalysisAgent(BaseAgent):
    """Document-grounded analysis (review/summarize/evaluate an uploaded file).
    Deliberately bypasses web search entirely."""

    def __init__(self):
        super().__init__("DocumentAnalysisAgent")

    async def run(self, query: str, context: dict | None = None) -> dict:
        context = context or {}
        document_text = context.get("documentText", "")
        file_name = context.get("fileName", "document")
        if not document_text.strip():
            return {"success": True, "output": {"answer": f"Could not extract any text from {file_name}."}}

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                res = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "stream": False,
                        "options": {"temperature": 0.3, "num_predict": 1200},
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": f"Document ({file_name}):\n{document_text}\n\nRequest: {query}"},
                        ],
                    },
                )
                if res.status_code >= 400:
                    raise RuntimeError(f"Document analysis LLM call failed: {res.status_code}")

                data = res.json()
                return {"success": True, "output": {"answer": (data.get("message") or {}).get("content", "")}}
        except Exception as err:
            return {"success": False, "output": {"answer": ""}, "error": str(err)}
