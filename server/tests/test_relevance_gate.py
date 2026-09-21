import pytest

from app.retrieval import relevance_gate as RG


def test_rewrite_query_strips_filler_prefix():
    assert RG.rewrite_query("please tell me what the capital of France is") == "what the capital of France is"
    assert RG.rewrite_query("What is the capital of France?") == "What is the capital of France?"


def test_grade_relevance_labels_relevant_chunk():
    chunks = [{"content": "The maximum retry count is 3.", "composite_score": 0.8}]
    graded = RG.grade_relevance("What is the maximum retry count?", chunks)
    assert graded[0]["relevance_label"] == "relevant"


def test_grade_relevance_labels_irrelevant_chunk():
    chunks = [{"content": "Bananas are a good source of potassium.", "composite_score": 0.05}]
    graded = RG.grade_relevance("What is the maximum retry count?", chunks)
    assert graded[0]["relevance_label"] == "irrelevant"


def test_filter_relevant_drops_irrelevant():
    graded = [
        {"relevance_label": "relevant"},
        {"relevance_label": "irrelevant"},
        {"relevance_label": "marginal"},
    ]
    filtered = RG.filter_relevant(graded)
    assert len(filtered) == 2
    assert all(c["relevance_label"] != "irrelevant" for c in filtered)


def test_detect_insufficient_below_min_sources():
    graded = [{"relevance_label": "relevant"}, {"relevance_label": "irrelevant"}]
    insufficient, usable = RG.detect_insufficient(graded, min_sources=2)
    assert insufficient is True
    assert usable == 1


def test_detect_insufficient_meets_min_sources():
    graded = [{"relevance_label": "relevant"}, {"relevance_label": "relevant"}]
    insufficient, usable = RG.detect_insufficient(graded, min_sources=2)
    assert insufficient is False
    assert usable == 2


def test_detect_stale_only_applies_to_freshness_categories():
    chunks = [{"freshness_score": 0.1, "original_filename": "old.txt"}]
    assert RG.detect_stale(chunks, "general", {"news", "politics"}) == []
    stale = RG.detect_stale(chunks, "news", {"news", "politics"})
    assert len(stale) == 1


def test_needs_correction_on_insufficient():
    assert RG.needs_correction(insufficient=True, graded_chunks=[], stale_items=[]) is True


def test_needs_correction_on_stale():
    assert RG.needs_correction(insufficient=False, graded_chunks=[], stale_items=[{"filename": "x"}]) is True


def test_needs_correction_on_majority_irrelevant():
    graded = [{"relevance_label": "irrelevant"}, {"relevance_label": "irrelevant"}, {"relevance_label": "relevant"}]
    assert RG.needs_correction(insufficient=False, graded_chunks=graded, stale_items=[]) is True


def test_needs_correction_false_when_healthy():
    graded = [{"relevance_label": "relevant"}, {"relevance_label": "relevant"}]
    assert RG.needs_correction(insufficient=False, graded_chunks=graded, stale_items=[]) is False


@pytest.mark.asyncio
async def test_detect_duplicates_no_embeddings_available_returns_all():
    # No "embedding" field and generate_embedding will fail without a
    # reachable Ollama — duplicates simply can't be identified, chunks pass
    # through unchanged rather than being dropped incorrectly.
    chunks = [{"content": "a"}, {"content": "b"}]
    deduped, pairs = await RG.detect_duplicates(chunks)
    assert len(deduped) == 2
    assert pairs == []


@pytest.mark.asyncio
async def test_detect_duplicates_drops_near_identical_embeddings():
    chunks = [
        {"content": "a", "embedding": [1.0, 0.0]},
        {"content": "b", "embedding": [1.0, 0.0001]},
        {"content": "c", "embedding": [0.0, 1.0]},
    ]
    deduped, pairs = await RG.detect_duplicates(chunks)
    assert len(deduped) == 2
    assert len(pairs) == 1
