import httpx

from ..core.config import OLLAMA_URL, OLLAMA_MODEL, RAG_TOP_K
from ..core.logger import logger
from ..retrieval.retrieval_service import retrieve
from .prompt_builder import build_rag_prompt
from ..agents.review_agent import ReviewAgent

DEFAULT_TOP_K = RAG_TOP_K

review_agent = ReviewAgent()


def _estimate_tokens(text: str) -> int:
    return -(-len(text or "") // 4)


async def _call_llm(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=180) as client:
        res = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.2},
            },
        )
        if res.status_code >= 400:
            raise RuntimeError(f"LLM request failed with status {res.status_code}")
        data = res.json()
        return (data.get("message") or {}).get("content", "")


async def run_rag_query(question: str, chat_id: str, top_k: int | None = None) -> dict:
    """Document-grounded RAG pipeline: hybrid+expanded+reranked retrieval ->
    grounded prompt -> generate -> review (confidence override + conflict
    check). This is the strict path — ReviewAgent can replace the answer
    entirely with the "not found" fallback when confidence is low, unlike the
    general assistant route which allows web/model fallback."""
    top_k = top_k or DEFAULT_TOP_K

    result = await retrieve(question, chat_id, top_k=top_k)
    chunks, context_text, sources, confidence = (
        result["chunks"], result["contextText"], result["sources"], result["confidence"],
    )

    logger.info("rag.retrieval", {
        "chatId": chat_id,
        "final": len(chunks),
        "confidence": confidence,
        "scores": [
            {"file": c.get("original_filename"), "similarity": round(c.get("similarity") or 0, 3)} for c in chunks
        ],
    })

    if not chunks:
        reviewed = await review_agent.run("", {"chunks": chunks, "sources": sources, "confidence": confidence})
        return {"answer": reviewed["output"]["answer"], "sources": [], "confidence": confidence, "conflict": False}

    logger.info("rag.context", {"contextChars": len(context_text), "estTokens": _estimate_tokens(context_text)})

    prompt = build_rag_prompt(context_text, question)
    raw_answer = await _call_llm(prompt)

    logger.info("rag.response", {"estTokens": _estimate_tokens(raw_answer)})

    reviewed = await review_agent.run(raw_answer, {"chunks": chunks, "sources": sources, "confidence": confidence})
    return {
        "answer": reviewed["output"]["answer"],
        "sources": reviewed["output"]["evidence"],
        "confidence": reviewed["output"]["confidence"],
        "conflict": reviewed["output"]["conflict"],
    }
