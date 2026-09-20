import asyncio
import os
import time
from unittest.mock import AsyncMock, patch
import pytest
import respx
from httpx import Response

from conftest import requires_db
from app.core import db
from app.core.config import DEFAULT_USER_ID
from app.knowledge.document_schema import (
    DocumentMetadata,
    calculate_freshness_score,
)
from app.knowledge.cleaning import (
    clean_content,
    compute_content_hash,
    validate_document_quality,
)
from app.knowledge.chunking import split_structured_text
from app.knowledge.refresh_pipeline import DataRefreshManager
from app.retrieval.freshness_scorer import (
    calculate_freshness,
    compute_composite_score,
    rank_candidates_with_freshness,
)
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.keyword_search import bm25_score_chunks, keyword_search
from app.retrieval.query_analyzer import analyze_query
from app.retrieval.retrieval_service import retrieve
from app.retrieval.web_retriever import WebSearchResult, DDGSWebRetriever
from app.jobs.cache import BoundedTTLCache


# 1. Fresh document ingestion with full metadata
@pytest.mark.asyncio
async def test_fresh_document_ingestion_with_metadata(monkeypatch):
    manager = DataRefreshManager()
    sample_content = (
        "# Quantum Computing Overview\n\n"
        "Quantum computing utilizes qubits to achieve exponential speedups in specific optimization tasks.\n\n"
        "## Practical Applications\n"
        "Major applications include cryptography, material simulation, and portfolio optimization."
    )

    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/embeddings").mock(
            return_value=Response(200, json={"embedding": [0.1] * 384})
        )

        result = await manager.ingest_or_update(
            source_id="quantum_doc_01",
            content=sample_content,
            title="Quantum Computing Guide",
            source_url="https://research.quantum.org/papers/guide",
            source_type="web",
            category="technology",
            published_at="2026-08-15T00:00:00Z",
        )

    assert result["status"] == "created"
    assert result["reembedded"] is True
    assert result["version"] == 1
    assert result["chunks_count"] >= 2

    doc = manager.get_document("quantum_doc_01")
    assert doc is not None
    assert doc.metadata.source_domain == "research.quantum.org"
    assert doc.metadata.category == "technology"
    assert doc.metadata.content_hash != ""
    assert doc.metadata.freshness_score > 0.5


# 2. Unchanged document content hash skipping re-embedding
@pytest.mark.asyncio
async def test_unchanged_document_skips_reembedding():
    manager = DataRefreshManager()
    content = "Stable historical document text that will not change over repeated ingest cycles."

    with respx.mock(assert_all_called=False) as mock:
        embed_route = mock.post(url__regex=r".*/api/embeddings").mock(
            return_value=Response(200, json={"embedding": [0.2] * 384})
        )

        res1 = await manager.ingest_or_update("doc_stable", content, title="Stable Doc")
        assert res1["status"] == "created"
        assert res1["reembedded"] is True
        initial_calls = embed_route.call_count

        # Second ingestion with identical content
        res2 = await manager.ingest_or_update("doc_stable", content, title="Stable Doc")
        assert res2["status"] == "unchanged"
        assert res2["reembedded"] is False
        # Embedding calls must NOT increase for unchanged content
        assert embed_route.call_count == initial_calls


# 3. Changed document updates version and affected vectors
@pytest.mark.asyncio
async def test_changed_document_updates_version_and_vectors():
    manager = DataRefreshManager()
    v1_content = "# Framework v1.0\n\nThe framework supports basic linear processing."
    v2_content = "# Framework v2.0\n\nThe framework now supports distributed parallel stream processing."

    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/embeddings").mock(
            return_value=Response(200, json={"embedding": [0.3] * 384})
        )

        res1 = await manager.ingest_or_update("framework_doc", v1_content)
        assert res1["version"] == 1

        res2 = await manager.ingest_or_update("framework_doc", v2_content)
        assert res2["status"] == "updated"
        assert res2["reembedded"] is True
        assert res2["version"] == 2

    doc = manager.get_document("framework_doc")
    assert doc.metadata.document_version == 2
    assert "distributed parallel stream" in doc.cleaned_content


# 4. Duplicate document and duplicate chunk prevention
def test_duplicate_chunk_prevention():
    text_with_dups = (
        "# Introduction\n\n"
        "Duplicate paragraph with identical text across multiple sections.\n\n"
        "## Section Two\n\n"
        "Duplicate paragraph with identical text across multiple sections.\n\n"
        "## Section Three\n\n"
        "A completely distinct and unique paragraph with different content."
    )
    chunks = split_structured_text(text_with_dups, target_size=200, document_id="dup_test")
    # Duplicate section body is dropped; only unique sections are kept
    assert len(chunks) == 2
    assert any("completely distinct" in c.content for c in chunks)
    assert any("Duplicate paragraph" in c.content for c in chunks)


# 5. Stale document vs current freshness ranking
def test_freshness_aware_ranking():
    old_doc = {
        "id": "old_1",
        "title": "Old Report 2021",
        "similarity": 0.85,  # High vector similarity
        "keywordScore": 0.70,
        "published_at": "2021-01-01T00:00:00Z",
        "source_type": "web",
    }
    new_doc = {
        "id": "new_1",
        "title": "Latest Report 2026",
        "similarity": 0.80,  # Slightly lower vector similarity
        "keywordScore": 0.65,
        "published_at": "2026-08-01T00:00:00Z",
        "source_type": "web",
    }

    # For a time-sensitive/current_info query, the newer document must outrank the older one
    ranked = rank_candidates_with_freshness([old_doc, new_doc], intent="current_info")
    assert ranked[0]["id"] == "new_1"
    assert ranked[0]["freshness_score"] > ranked[1]["freshness_score"]
    assert ranked[0]["composite_score"] > ranked[1]["composite_score"]


# 6. Hybrid retrieval (dense + sparse BM25 + web fusion)
@pytest.mark.asyncio
async def test_hybrid_retrieval_dense_sparse_web_fusion(monkeypatch):
    mock_semantic = [
        {"id": "doc_dense", "content": "Dense semantic match content", "similarity": 0.90}
    ]
    mock_keyword = [
        {"id": "doc_sparse", "content": "Sparse lexical match content", "keywordScore": 0.85}
    ]
    mock_web = [
        WebSearchResult(
            url="https://example.com/fresh-news",
            title="Fresh News",
            content="Fresh web snippet content",
            source_domain="example.com",
            relevance_score=0.75,
        )
    ]

    async def fake_semantic(*a, **kw):
        return mock_semantic

    async def fake_keyword(*a, **kw):
        return mock_keyword

    class FakeWebRetriever:
        async def search(self, query, max_results=5):
            return mock_web

    monkeypatch.setattr("app.retrieval.hybrid_search.semantic_search", fake_semantic)
    monkeypatch.setattr("app.retrieval.hybrid_search.keyword_search", fake_keyword)
    monkeypatch.setattr("app.retrieval.hybrid_search.get_web_retriever", lambda: FakeWebRetriever())

    fused = await hybrid_search("test query", top_k=5, include_web=True)
    fused_ids = [c["id"] for c in fused]

    assert "doc_dense" in fused_ids
    assert "doc_sparse" in fused_ids
    assert any("web_" in cid for cid in fused_ids)
    assert all("hybridScore" in c for c in fused)


# 7. Metadata-aware filtering
def test_metadata_filtering_bm25():
    corpus = [
        {"content": "Deep learning models for medical image diagnosis.", "category": "medical"},
        {"content": "Deep learning models for financial algorithmic trading.", "category": "finance"},
        {"content": "Deep learning architectures for code generation.", "category": "tech"},
    ]
    terms = ["deep", "learning"]

    # Filter by category = finance
    filtered = [c for c in corpus if c.get("category") == "finance"]
    scored = bm25_score_chunks(terms, filtered)

    assert len(scored) == 1
    assert "financial algorithmic" in scored[0]["content"]


# 8. Web retrieval failure and graceful fallback
@pytest.mark.asyncio
async def test_web_retriever_failure_and_fallback(monkeypatch):
    class FailingWebRetriever:
        async def search(self, query, max_results=5):
            raise TimeoutError("Web retrieval timed out")

    monkeypatch.setattr("app.retrieval.hybrid_search.get_web_retriever", lambda: FailingWebRetriever())

    async def fake_semantic(*a, **kw):
        return [{"id": "fallback_doc", "content": "Fallback document content", "similarity": 0.8}]

    async def fake_keyword(*a, **kw):
        return []

    monkeypatch.setattr("app.retrieval.hybrid_search.semantic_search", fake_semantic)
    monkeypatch.setattr("app.retrieval.hybrid_search.keyword_search", fake_keyword)

    # Should not raise an exception, returns available local candidates
    fused = await hybrid_search("query", top_k=5, include_web=True)
    assert len(fused) == 1
    assert fused[0]["id"] == "fallback_doc"


# 9. Vector DB failure and graceful fallback
@pytest.mark.asyncio
async def test_vector_db_failure_and_fallback(monkeypatch):
    from app.retrieval.semantic_search import semantic_search
    import app.retrieval.semantic_search as ss_module

    # Point QDRANT_URL to an invalid unreachable host
    monkeypatch.setattr(ss_module, "QDRANT_URL", "http://127.0.0.1:9")

    # In-memory knowledge base has one chunk
    test_chunk = {
        "id": "mem_1",
        "content": "In-memory fallback knowledge content",
        "embedding": [0.5] * 384,
        "title": "Fallback",
    }
    monkeypatch.setattr(ss_module.refresh_manager, "list_all_chunks", lambda: [test_chunk])

    # Should not crash, returns in-memory cosine matches
    results = await semantic_search("query", query_vector=[0.5] * 384, top_k=3)
    assert len(results) > 0
    assert results[0]["id"] == "mem_1"


# 10. Empty results handling
@pytest.mark.asyncio
async def test_empty_results_handling(monkeypatch):
    # Empty knowledge base and empty chat
    monkeypatch.setattr("app.retrieval.retrieval_service.fetch_chunks_for_chat", AsyncMock(return_value=[]))
    monkeypatch.setattr("app.retrieval.retrieval_service.refresh_manager.list_all_chunks", lambda: [])

    result = await retrieve("unrelated question", chat_id="empty_chat_id", top_k=5, include_web=False)
    assert result["chunks"] == []
    assert result["contextText"] == ""
    assert result["confidence"]["label"] == "low"


# 11. Llama generation failure handling
@pytest.mark.asyncio
async def test_llama_failure_handling(monkeypatch):
    from app.services.rag_service import run_rag_query

    # Mock retrieve to return a valid chunk
    mock_retrieval = {
        "chunks": [{"content": "Grounded document text", "original_filename": "doc.txt"}],
        "contextText": "Grounded document text",
        "sources": [{"filename": "doc.txt"}],
        "confidence": {"score": 80, "label": "high"},
    }
    monkeypatch.setattr("app.services.rag_service.retrieve", AsyncMock(return_value=mock_retrieval))

    # Mock Ollama generation failing with 500
    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/chat").mock(return_value=Response(500, json={"error": "LLM overloaded"}))

        with pytest.raises(RuntimeError) as exc_info:
            await run_rag_query("What is in the document?", chat_id="chat_1")
        assert "LLM request failed" in str(exc_info.value)


# 12. Concurrent retrieval performance and thread-safe caching
@pytest.mark.asyncio
async def test_concurrent_retrieval_performance(monkeypatch):
    sample_chunk = {
        "id": "c1",
        "content": "Concurrent search sample data",
        "embedding": [0.1] * 384,
        "title": "Doc",
    }
    monkeypatch.setattr("app.retrieval.retrieval_service.fetch_chunks_for_chat", AsyncMock(return_value=[sample_chunk]))
    monkeypatch.setattr("app.retrieval.retrieval_service.generate_embedding", AsyncMock(return_value=[0.1] * 384))

    # Run 10 concurrent retrieval requests
    queries = [f"query variant {i}" for i in range(10)]
    tasks = [retrieve(q, chat_id="concurrent_chat", top_k=3, include_web=False) for q in queries]
    start = time.perf_counter()
    results = await asyncio.gather(*tasks)
    elapsed = time.perf_counter() - start

    assert len(results) == 10
    # Should complete concurrently within a small timeframe on local test
    assert elapsed < 3.0


# 13. Generated output NOT written to project files
@pytest.mark.asyncio
async def test_generated_output_not_written_to_project_files(app_client):
    from app.routes.nova_route import nova_task, NovaTaskBody

    fake_answer = (
        "Here is the solution:\n\n"
        "```python\n"
        "// FILE: solver.py\n"
        "def solve():\n"
        "    return 42\n"
        "```"
    )

    with patch("app.routes.nova_route.planner_agent.run", AsyncMock(return_value={"output": {"intent": "code", "steps": []}})), \
         patch("app.routes.nova_route.code_agent.run", AsyncMock(return_value={"output": {"answer": fake_answer}})), \
         patch("app.routes.nova_route.validation_agent.critique", AsyncMock(return_value={"pass": True, "issues": [], "confidenceScore": 90})):

        body = NovaTaskBody(prompt="Write solver.py")
        res = await nova_task(body)

    # Generated files must be in-memory in response
    assert len(res["files"]) == 1
    assert res["files"][0]["path"] == "solver.py"
    assert "def solve():" in res["files"][0]["content"]

    # Verify NO file was written to disk!
    disk_path = "/home/linux/Desktop/Nova-AI/generated/solver.py"
    assert not os.path.exists(disk_path)


# 14. Anti-contamination: generated text rejected from entering vector DB
def test_anti_contamination_rejects_ai_generated_text():
    ai_text_1 = "As an AI language model, I don't have feelings, but I can help you with programming."
    ai_text_2 = "Here is a summary of the uploaded document: The report outlines key strategies."

    valid, reason = validate_document_quality(ai_text_1)
    assert not valid
    assert "AI-generated" in reason

    valid, reason = validate_document_quality(ai_text_2)
    assert not valid
    assert "AI-generated" in reason

    # Genuine technical content passes
    valid, reason = validate_document_quality("PostgreSQL supports GIN and GiST indexes for full-text search.")
    assert valid


# 15. Cache expiry and bounded size
def test_cache_expiry_and_bounded_size():
    cache = BoundedTTLCache(max_size=3, default_ttl_ms=50)

    cache.set("k1", "v1")
    cache.set("k2", "v2")
    cache.set("k3", "v3")
    assert len(cache) == 3

    # Add 4th item, oldest (k1) should be evicted
    cache.set("k4", "v4")
    assert len(cache) == 3
    assert cache.get("k1") is None
    assert cache.get("k4") == "v4"

    # Test TTL expiry
    time.sleep(0.06)
    assert cache.get("k4") is None


# 16. Current vs Historical information query analysis
def test_current_vs_historical_query_analysis():
    current_q = analyze_query("What is the latest stock price of Apple today?")
    assert current_q.intent == "current_info"
    assert current_q.requires_fresh_web is True

    historical_q = analyze_query("When was the Magna Carta signed in England?")
    assert historical_q.intent in ("factual", "general")
    assert "Magna Carta" in historical_q.entities or "England" in historical_q.entities
