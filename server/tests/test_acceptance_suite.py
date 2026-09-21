import asyncio
import os
import time
from unittest.mock import AsyncMock, patch
import pytest
import respx
from httpx import Response

from app.core import db
from app.core.config import DEFAULT_USER_ID, OLLAMA_MODEL
from app.knowledge.refresh_pipeline import refresh_manager
from app.retrieval.query_analyzer import analyze_query
from app.retrieval.retrieval_service import retrieve
from app.services.rag_service import run_rag_query
from app.routes.nova_route import nova_task, NovaTaskBody
from app.knowledge.cleaning import validate_document_quality


@pytest.mark.asyncio
async def test_acceptance_end_to_end_scenarios():
    """Comprehensive acceptance test executing the required matrix of queries:
    current, historical, factual, semantic, exact keyword, long, short,
    web-requiring, and knowledge-base answerable."""

    # 1. Verification of Ingestion & Refresh Pipeline
    kb_doc_text = (
        "# Nova AI Platform Specifications\n\n"
        "Nova AI uses Qdrant for vector storage and cosine_similarity dot_product norm computation.\n\n"
        "## Architecture\n"
        "The architecture implements parallel hybrid retrieval with Reciprocal Rank Fusion.\n\n"
        "## Release History\n"
        "Version 1.0 released in 2024. Version 2.0 released in 2026 with real-time freshness scoring."
    )
    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/embeddings").mock(
            return_value=Response(200, json={"embedding": [0.05] * 384})
        )

        # Ingestion test
        ingest_res = await refresh_manager.ingest_or_update(
            source_id="nova_specs",
            content=kb_doc_text,
            title="Nova AI Specifications",
            category="architecture",
            published_at="2026-08-01T00:00:00Z",
        )
        assert ingest_res["status"] == "created"
        assert ingest_res["reembedded"] is True

        # Idempotency test (skip re-embedding)
        ingest_unchanged = await refresh_manager.ingest_or_update(
            source_id="nova_specs",
            content=kb_doc_text,
            title="Nova AI Specifications",
        )
        assert ingest_unchanged["status"] == "unchanged"
        assert ingest_unchanged["reembedded"] is False

    # 2. Query Matrix Testing
    queries = [
        # Current question
        {"q": "What are the latest updates on space exploration in 2026?", "type": "current"},
        # Historical question
        {"q": "When did the Apollo 11 lunar module land on the moon in 1969?", "type": "historical"},
        # Factual question
        {"q": "What is the speed of light in vacuum?", "type": "factual"},
        # Semantic question
        {"q": "How does multi-head attention mechanism route contextual information?", "type": "semantic"},
        # Exact keyword question
        {"q": "cosine_similarity dot_product norm", "type": "keyword"},
        # Long question
        {"q": "Can you provide a comprehensive, in-depth architectural breakdown comparing dense vector search and sparse BM25 indexing with their trade-offs in low-resource environments?", "type": "long"},
        # Short question
        {"q": "Python GIL?", "type": "short"},
        # Question answerable from knowledge base
        {"q": "What does Nova AI use for vector storage and similarity computation?", "type": "kb"},
    ]

    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/embeddings").mock(
            return_value=Response(200, json={"embedding": [0.05] * 384})
        )

        for item in queries:
            q = item["q"]
            analysis = analyze_query(q)
            assert analysis.normalized_query != ""

            if item["type"] == "current":
                assert analysis.intent == "current_info"
                assert analysis.requires_fresh_web is True
            elif item["type"] == "long":
                assert analysis.is_research is True

            res = await retrieve(q, top_k=3, include_web=False)
            assert "chunks" in res
            assert "metrics" in res
            assert res["metrics"]["total_ms"] >= 0

    # 3. Verify Knowledge Base retrieval works for internal facts
    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/embeddings").mock(
            return_value=Response(200, json={"embedding": [0.05] * 384})
        )
        kb_res = await retrieve("Nova AI vector storage cosine_similarity", top_k=3, include_web=False)
        assert len(kb_res["chunks"]) > 0
        assert any("Qdrant" in c["content"] for c in kb_res["chunks"])

    # 4. Confirmation local Qwen model remains configured and is NOT replaced
    assert "qwen" in OLLAMA_MODEL.lower()

    # 5. Confirmation generated answers are NOT stored in project files
    fake_code_answer = "```python\n# FILE: test_generated.py\nprint('hello world')\n```"
    with patch("app.routes.nova_route.planner_agent.run", AsyncMock(return_value={"output": {"intent": "code", "steps": []}})), \
         patch("app.routes.nova_route.code_agent.run", AsyncMock(return_value={"output": {"answer": fake_code_answer}})), \
         patch("app.routes.nova_route.validation_agent.critique", AsyncMock(return_value={"pass": True, "issues": [], "confidenceScore": 95})):

        task_res = await nova_task(NovaTaskBody(prompt="generate code"))
        assert len(task_res["files"]) == 1
        assert task_res["files"][0]["path"] == "test_generated.py"

        # Assert no file on disk
        assert not os.path.exists("/home/linux/Desktop/Nova-AI/generated/test_generated.py")

    # 6. Confirmation generated answers are NOT inserted into vector DB
    valid, reason = validate_document_quality("As an AI assistant, I generated this response to help you.")
    assert not valid
    assert "AI-generated" in reason
