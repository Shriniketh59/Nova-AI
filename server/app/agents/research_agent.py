import asyncio
import re

import httpx

from ..core.config import OLLAMA_URL, CONTRADICTION_THRESHOLD, MAX_CORRECTIVE_RETRIES
from ..rag import generate_embedding, cosine_similarity
from ..retrieval.retrieval_service import retrieve
from ..retrieval.complexity import tier_for
from ..retrieval.source_trust import rank_sources, count_trust_tiers
from ..retrieval import relevance_gate
from ..retrieval.source_attribution import attribute_sources
from .base_agent import BaseAgent
from .validation_agent import _detect_conflict

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
    """DDGS web search — no API key, fully local. Runs the blocking DDGS
    call in a worker thread (never on the event loop) and is bounded by a
    timeout so a hung search can't stall the whole request."""
    loop = asyncio.get_running_loop()

    def _blocking():
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": (r.get("body", "") or "")[:400],
                    "type": "web",
                }
                for r in results
            ][:max_results]
        except Exception:
            return []

    for attempt in range(2):  # bounded retry: 1 retry on timeout/empty transient failure
        try:
            results = await asyncio.wait_for(loop.run_in_executor(None, _blocking), timeout=8.0)
            if results or attempt == 1:
                return results
        except asyncio.TimeoutError:
            if attempt == 1:
                return []
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


async def _corrective_retrieve(question: str, chat_id: str, tier: dict, needs_doc_retrieval, category: str) -> tuple[dict, list[dict], dict]:
    """Corrective-RAG retrieval step: retrieve, grade relevance, and — if
    evidence is insufficient, mostly irrelevant, or stale where freshness
    matters — retry once with a rewritten query and (if staleness was the
    trigger) a forced web fallback. Bounded by MAX_CORRECTIVE_RETRIES so a
    query with no good evidence anywhere fails fast instead of looping."""
    if needs_doc_retrieval is False:
        empty = {"chunks": [], "sources": [], "confidence": {"score": 0, "label": "low"}}
        return empty, [], {"corrected": False, "retries": 0, "duplicatesDropped": 0}

    doc_result = await retrieve(question, chat_id, top_k=tier["topK"])
    graded = relevance_gate.grade_relevance(question, doc_result["chunks"])

    retries = 0
    corrected = False
    while retries < MAX_CORRECTIVE_RETRIES:
        insufficient, _usable = relevance_gate.detect_insufficient(graded, tier["minSources"])
        stale_items = relevance_gate.detect_stale(graded, category, FORCE_WEB_SEARCH_CATEGORIES)
        if not relevance_gate.needs_correction(insufficient, graded, stale_items):
            break
        retries += 1
        corrected = True
        retry_query = relevance_gate.rewrite_query(question)
        doc_result = await retrieve(retry_query, chat_id, top_k=tier["minSources"] * 2, include_web=bool(stale_items))
        graded = relevance_gate.grade_relevance(retry_query, doc_result["chunks"])

    relevant_chunks = relevance_gate.filter_relevant(graded)
    deduped_chunks, dropped_pairs = await relevance_gate.detect_duplicates(relevant_chunks)

    return doc_result, deduped_chunks, {"corrected": corrected, "retries": retries, "duplicatesDropped": len(dropped_pairs)}


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
        category = plan.get("category") or "general"

        force_web_search = category in FORCE_WEB_SEARCH_CATEGORIES
        skip_web_search = (has_files and not force_web_search) or plan.get("taskType") == "greeting"
        tier = (
            {"topK": force_top_k, "minSources": tier_for(question)["minSources"]}
            if force_top_k
            else tier_for(question)
        )
        try:
            doc_task = _corrective_retrieve(question, chat_id, tier, plan.get("needsDocRetrieval"), category)
            web_task = _fetch_web_sources(question, tier["topK"]) if not skip_web_search else asyncio.sleep(0, result=[])
            (doc_result, doc_chunks, correction), web_sources = await asyncio.gather(doc_task, web_task)

            doc_sources = attribute_sources(doc_chunks) if doc_chunks else []
            conflict = await _detect_conflict(doc_chunks) if doc_chunks else {"found": False, "detail": None}

            ranked_web_sources = rank_sources(web_sources)
            doc_evidence = [
                {**s, "snippet": (doc_chunks[i].get("content", "")[:400] if i < len(doc_chunks) else "")}
                for i, s in enumerate(doc_sources)
            ]
            web_evidence = [
                {"title": s.get("title"), "type": "web", "url": s.get("url"), "snippet": s.get("snippet"), "trustTier": s.get("trustTier")}
                for s in ranked_web_sources
            ]
            # For time-sensitive/forced-web-search categories (politics, news,
            # biography, ...), live web evidence must win over any cached/
            # stale doc (RAG) chunks — put it first so it's never the part
            # truncated away by the topK cap below.
            evidence = (web_evidence + doc_evidence) if force_web_search else (doc_evidence + web_evidence)
            evidence = evidence[: tier["topK"]]

            trust_tiers = count_trust_tiers(evidence)
            embedding_contradictions, fact_disagreements = await asyncio.gather(
                _detect_contradictions(evidence), asyncio.sleep(0, result=detect_fact_disagreements(evidence))
            )
            contradictions = [*embedding_contradictions, *fact_disagreements]
            if conflict["found"]:
                contradictions.append({"sourceA": "document evidence", "sourceB": "document evidence", "detail": conflict["detail"]})

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
                    "category": category,
                    "correction": correction,
                },
            }
        except Exception as err:
            return {"success": False, "output": {"evidence": [], "evidenceSummary": "", "contradictions": []}, "error": str(err)}
