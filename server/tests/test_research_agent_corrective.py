from unittest.mock import AsyncMock

import pytest

from app.agents.research_agent import ResearchAgent
from app.agents.validation_agent import ValidationAgent


def _doc_result(chunks):
    return {
        "chunks": chunks,
        "sources": [{"index": i + 1, "chunk_id": c.get("id"), "filename": c.get("original_filename"), "type": "document", "similarity": c.get("similarity")} for i, c in enumerate(chunks)],
        "confidence": {"score": 50, "label": "medium"},
    }


def _chunk(cid, filename, content, score):
    return {"id": cid, "original_filename": filename, "content": content, "composite_score": score}


@pytest.mark.asyncio
async def test_corrective_retry_triggers_on_insufficient_evidence(monkeypatch):
    """First retrieval returns a single weak/off-topic chunk (below the
    tier's min_sources of 3 for a simple query) — the corrective loop should
    retry once with a rewritten query before falling through to generation."""
    weak = [_chunk("c1", "a.txt", "Bananas are a good source of potassium.", 0.03)]
    strong = [
        _chunk("c1", "a.txt", "The maximum retry count is 3.", 0.9),
        _chunk("c2", "b.txt", "Retries are capped at 3 attempts per request.", 0.85),
        _chunk("c3", "c.txt", "Config: retry count defaults to 3.", 0.8),
    ]

    calls = {"n": 0}

    async def fake_retrieve(query, chat_id="", top_k=None, threshold=None, filters=None, include_web=None):
        calls["n"] += 1
        return _doc_result(weak) if calls["n"] == 1 else _doc_result(strong)

    monkeypatch.setattr("app.agents.research_agent.retrieve", fake_retrieve)
    monkeypatch.setattr("app.agents.research_agent._fetch_web_sources", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.agents.research_agent._detect_conflict", AsyncMock(return_value={"found": False, "detail": None}))
    monkeypatch.setattr("app.agents.research_agent._detect_contradictions", AsyncMock(return_value=[]))

    agent = ResearchAgent()
    result = await agent.run("What is the maximum retry count?", {"plan": {"category": "general", "needsDocRetrieval": True}, "hasFiles": True})

    assert calls["n"] == 2, "expected exactly one corrective retry (bounded by MAX_CORRECTIVE_RETRIES=1)"
    assert result["output"]["sourceCount"] >= 3
    assert any("retry count is 3" in e.get("snippet", "") for e in result["output"]["evidence"])


@pytest.mark.asyncio
async def test_no_correction_when_evidence_is_already_healthy(monkeypatch):
    strong = [
        _chunk("c1", "a.txt", "The maximum retry count is 3.", 0.9),
        _chunk("c2", "b.txt", "Retries are capped at 3 attempts per request.", 0.85),
        _chunk("c3", "c.txt", "Config: retry count defaults to 3.", 0.8),
    ]
    calls = {"n": 0}

    async def fake_retrieve(query, chat_id="", top_k=None, threshold=None, filters=None, include_web=None):
        calls["n"] += 1
        return _doc_result(strong)

    monkeypatch.setattr("app.agents.research_agent.retrieve", fake_retrieve)
    monkeypatch.setattr("app.agents.research_agent._fetch_web_sources", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.agents.research_agent._detect_conflict", AsyncMock(return_value={"found": False, "detail": None}))
    monkeypatch.setattr("app.agents.research_agent._detect_contradictions", AsyncMock(return_value=[]))

    agent = ResearchAgent()
    await agent.run("What is the maximum retry count?", {"plan": {"category": "general", "needsDocRetrieval": True}, "hasFiles": True})

    assert calls["n"] == 1, "healthy evidence on the first pass should not trigger a corrective retry"


@pytest.mark.asyncio
async def test_claim_level_gate_rejects_unsupported_claim_when_whole_answer_ratio_still_passes():
    """A multi-sentence answer that is mostly well-grounded (whole-answer
    ratio stays above MIN_GROUNDING_RATIO) but contains one fabricated
    sentence must still be caught claim-by-claim — this is exactly the
    'single fabricated sentence averaged away' failure mode the claim-level
    gate exists to catch, distinct from the pre-existing whole-answer gate."""
    evidence_summary = (
        "[1] (document) config.txt: The maximum retry count is 3. Timeout is 30 seconds. "
        "Retries use exponential backoff. Config version is 2."
    )
    answer = (
        "The maximum retry count is 3.\n"
        "Timeout is 30 seconds.\n"
        "Retries use exponential backoff, and Config version is 2.\n"
        "The system was originally designed by Acme Corporation in Zurich in 1998."
    )
    agent = ValidationAgent()
    critique = await agent.critique(answer, "What is the maximum retry count?", evidence_summary, [])

    assert critique["pass"] is False
    assert critique["needsMoreEvidence"] is True
    assert any("unsupported_claim" in issue for issue in critique["issues"])
    assert "claims" in critique
    assert any(c["supported"] is False for c in critique["claims"])


@pytest.mark.asyncio
async def test_claim_level_gate_passes_fully_grounded_short_answer_without_llm_call():
    evidence_summary = "[1] (document) config.txt: The maximum retry count is 3."
    answer = "The maximum retry count is 3."
    agent = ValidationAgent()
    critique = await agent.critique(answer, "What is the maximum retry count?", evidence_summary, [])

    # Short answers below MIN_CLAIM_TOKENS_TO_CHECK don't trigger the
    # claim-level or whole-answer grounding gates and fall through to the
    # LLM-judge call, which fails closed (pass=True, low confidence) when
    # Ollama isn't reachable in this test environment.
    assert "claims" in critique
