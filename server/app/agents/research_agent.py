import asyncio
import re

import httpx

from ..core.config import RAG_API_URL
from ..rag import generate_embedding, cosine_similarity
from ..retrieval.retrieval_service import retrieve
from ..retrieval.complexity import tier_for
from ..retrieval.source_trust import rank_sources, count_trust_tiers
from .base_agent import BaseAgent

CONTRADICTION_THRESHOLD = 0.3

FORCE_WEB_SEARCH_CATEGORIES = {"biography", "politics", "medical", "legal", "finance", "news"}

YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")
DATE_RE = re.compile(
    r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",
    re.I,
)
PROPER_NOUN_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")


def _extract_facts(text: str) -> dict:
    if not text:
        return {"years": [], "dates": []}
    return {"years": list(set(YEAR_RE.findall(text))), "dates": list(set(DATE_RE.findall(text)))}


def _shares_proper_noun(text_a: str, text_b: str) -> bool:
    a = set(PROPER_NOUN_RE.findall(text_a))
    b = set(PROPER_NOUN_RE.findall(text_b))
    return bool(a & b)


def detect_fact_disagreements(evidence: list[dict]) -> list[dict]:
    disagreements = []
    for i in range(len(evidence)):
        for j in range(i + 1, len(evidence)):
            a, b = evidence[i], evidence[j]
            text_a = a.get("snippet", "")
            text_b = b.get("snippet", "")
            if not _shares_proper_noun(text_a, text_b):
                continue

            years_a = _extract_facts(text_a)["years"]
            years_b = _extract_facts(text_b)["years"]
            if years_a and years_b and not any(y in years_b for y in years_a):
                disagreements.append({
                    "sourceA": a.get("title") or a.get("filename"),
                    "sourceB": b.get("title") or b.get("filename"),
                    "factType": "year",
                    "valueA": ", ".join(years_a),
                    "valueB": ", ".join(years_b),
                })
    return disagreements


async def _fetch_web_sources(query: str, max_results: int = 5) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(f"{RAG_API_URL}/search", json={"query": query, "max_results": max_results})
            if res.status_code >= 400:
                return []
            data = res.json()
            return data.get("sources", [])
    except Exception:
        return []


async def _detect_contradictions(evidence: list[dict]) -> list[dict]:
    """Pairwise-compares evidence snippet embeddings; on-topic items whose
    embeddings are far apart are flagged as a probable contradiction."""
    if len(evidence) < 2:
        return []

    async def _embed(e):
        try:
            vec = await generate_embedding(e.get("snippet") or e.get("title") or "")
        except Exception:
            vec = None
        return {**e, "_vec": vec}

    with_embeddings = await asyncio.gather(*[_embed(e) for e in evidence])

    contradictions = []
    for i in range(len(with_embeddings)):
        for j in range(i + 1, len(with_embeddings)):
            a, b = with_embeddings[i], with_embeddings[j]
            if not a["_vec"] or not b["_vec"]:
                continue
            sim = cosine_similarity(a["_vec"], b["_vec"])
            if sim < CONTRADICTION_THRESHOLD:
                contradictions.append({
                    "sourceA": a.get("title") or a.get("filename"),
                    "sourceB": b.get("title") or b.get("filename"),
                    "similarity": round(sim, 2),
                })
    return contradictions


class ResearchAgent(BaseAgent):
    """Second stage of the critical-thinking pipeline: RAG Retrieval + Evidence
    Analysis. Fans out to document retrieval AND web search in parallel, then
    builds one evidence list spanning both."""

    def __init__(self):
        super().__init__("ResearchAgent")

    async def run(self, question: str, context: dict | None = None) -> dict:
        context = context or {}
        chat_id = context.get("chatId")
        plan = context.get("plan", {})
        has_files = context.get("hasFiles", False)
        memories = context.get("memories", [])
        force_top_k = context.get("forceTopK")

        force_web_search = plan.get("category") in FORCE_WEB_SEARCH_CATEGORIES
        skip_web_search = (has_files and not force_web_search) or plan.get("taskType") == "greeting"
        tier = (
            {"topK": force_top_k, "minSources": tier_for(question)["minSources"]}
            if force_top_k
            else tier_for(question)
        )
        try:
            doc_task = (
                retrieve(question, chat_id, top_k=tier["topK"])
                if plan.get("needsDocRetrieval") is not False
                else asyncio.sleep(0, result={"chunks": [], "sources": [], "contextText": "", "confidence": {"score": 0, "label": "low"}})
            )
            web_task = _fetch_web_sources(question, tier["topK"]) if not skip_web_search else asyncio.sleep(0, result=[])
            doc_result, web_sources = await asyncio.gather(doc_task, web_task)

            ranked_web_sources = rank_sources(web_sources)
            evidence = [
                {**s, "snippet": (doc_result["chunks"][i].get("content", "")[:400] if i < len(doc_result["chunks"]) else "")}
                for i, s in enumerate(doc_result["sources"])
            ]
            evidence += [{"title": "Earlier in this conversation", "type": "memory", "snippet": m} for m in memories]
            evidence += [
                {"title": s.get("title"), "type": "web", "url": s.get("url"), "snippet": s.get("snippet"), "trustTier": s.get("trustTier")}
                for s in ranked_web_sources
            ]
            evidence = evidence[: tier["topK"]]

            trust_tiers = count_trust_tiers(evidence)
            embedding_contradictions, fact_disagreements = await asyncio.gather(
                _detect_contradictions(evidence), asyncio.sleep(0, result=detect_fact_disagreements(evidence))
            )
            contradictions = [*embedding_contradictions, *fact_disagreements]

            evidence_summary = (
                "\n\n".join(f"[{i + 1}] ({e['type']}) {e.get('title') or e.get('filename')}: {e.get('snippet', '')}" for i, e in enumerate(evidence))
                if evidence
                else "No external evidence found — answer must rely on general knowledge only."
            )

            return {
                "success": True,
                "output": {
                    "evidence": evidence,
                    "evidenceSummary": evidence_summary,
                    "contradictions": contradictions,
                    "docConfidence": doc_result["confidence"],
                    "sourceCount": len(evidence),
                    "minSources": tier["minSources"],
                    "trustTiers": trust_tiers,
                    "category": plan.get("category") or "general",
                },
            }
        except Exception as err:
            return {"success": False, "output": {"evidence": [], "evidenceSummary": "", "contradictions": []}, "error": str(err)}
