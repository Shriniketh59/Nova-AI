"""Pipeline integrity guarantees.

Covers the architecture requirements that had no test coverage:
  - answer validation / grounding checks
  - assistant-generated answers never reaching the vector store
  - stale-cache prevention in retrieval and web search
  - client-abort propagating to server-side generation

Prompt isolation lives in test_context_contamination.py and Chroma retrieval /
metadata filtering in test_vector_store.py — not duplicated here.
"""

import asyncio

import pytest


# ---------------------------------------------------------------------------
# Answer validation / grounding (spec 6)
# ---------------------------------------------------------------------------

from app.orchestrator.answer_validator import validate_answer


def test_answer_grounded_in_retrieved_evidence_passes():
    result = validate_answer(
        query="What is the capital of France?",
        answer="The capital of France is Paris, which sits on the river Seine "
               "and has been the country's capital since the tenth century.",
        evidence_text="Paris is the capital of France. It lies on the river Seine "
                      "and has served as the capital since the tenth century.",
    )
    assert result.had_evidence is True
    assert result.grounded is True
    assert result.warnings == []
    assert result.overlap_ratio > 0.5


def test_answer_ignoring_its_own_evidence_is_flagged():
    """Evidence was retrieved but the answer talks about something else."""
    result = validate_answer(
        query="What is the capital of France?",
        answer="Quantum entanglement describes correlated particle pairs whose "
               "measurement outcomes remain linked regardless of separation "
               "distance, a phenomenon central to modern cryptography research.",
        evidence_text="Paris is the capital of France. It lies on the river Seine.",
    )
    assert result.had_evidence is True
    assert result.grounded is False
    assert any("ignores_retrieved_evidence" in w for w in result.warnings)


def test_short_answers_are_exempt_from_the_overlap_rule():
    """"Yes." legitimately shares almost no words with its sources."""
    result = validate_answer(
        query="Is Paris the capital of France?",
        answer="Yes, that is correct.",
        evidence_text="Paris is the capital of France. It lies on the river Seine.",
    )
    assert result.warnings == []


def test_confident_factual_answer_with_no_evidence_is_flagged():
    result = validate_answer(
        query="Who is the current CEO of Acme Corporation?",
        answer="The current CEO of Acme Corporation is Jane Doe, who took over "
               "in March and previously led their hardware division.",
        evidence_text="",
    )
    assert result.had_evidence is False
    assert result.is_factual_query is True
    assert result.grounded is False
    assert "confident_factual_answer_without_any_evidence" in result.warnings


def test_hedged_answer_with_no_evidence_is_not_flagged():
    """Admitting uncertainty without evidence is the correct behaviour."""
    result = validate_answer(
        query="Who is the current CEO of Acme Corporation?",
        answer="I'm not sure who currently holds that role — I couldn't find any "
               "sources confirming it, so you may want to check their website.",
        evidence_text="",
    )
    assert result.warnings == []


def test_non_factual_question_without_evidence_is_not_flagged():
    """Explanations and opinions don't require retrieved evidence."""
    result = validate_answer(
        query="Explain recursion in simple terms",
        answer="Recursion is when a function calls itself on a smaller version of "
               "the same problem, stopping at a base case that needs no further calls.",
        evidence_text="",
    )
    assert result.is_factual_query is False
    assert result.warnings == []


def test_web_sources_count_as_evidence():
    result = validate_answer(
        query="What is the latest Python release?",
        answer="The latest Python release is version 3.13, which introduced an "
               "improved interactive interpreter and free-threaded build support.",
        evidence_text="",
        web_sources=[{
            "title": "Python 3.13 released",
            "snippet": "Python 3.13 introduced an improved interactive interpreter "
                       "and free-threaded build support.",
        }],
    )
    assert result.had_evidence is True
    assert result.grounded is True


def test_validation_never_raises_on_empty_input():
    """Advisory checks must never be able to break a turn."""
    assert validate_answer(query="", answer="", evidence_text="").warnings == []


# ---------------------------------------------------------------------------
# Generated answers must never be indexed (spec 4)
# ---------------------------------------------------------------------------

def test_no_route_writes_assistant_answers_into_the_vector_store():
    """The only upsert call sites may be document ingestion paths.

    Indexing an assistant's own answer would let a hallucination be retrieved
    later as if it were a source, which compounds. This pins the call sites so
    a new one has to be deliberate.
    """
    import pathlib

    app_dir = pathlib.Path(__file__).parent.parent / "app"
    allowed = {
        "knowledge/refresh_pipeline.py",  # curated knowledge base ingestion
        "routes/upload.py",               # user-uploaded documents
        "retrieval/vector_store.py",      # the implementation itself
        "retrieval/qdrant_client.py",     # the implementation itself
    }

    found = set()
    for path in app_dir.rglob("*.py"):
        text = path.read_text()
        if ".upsert(" in text or "upsert_points(" in text:
            found.add(path.relative_to(app_dir).as_posix())

    assert found <= allowed, f"unexpected vector-store write sites: {sorted(found - allowed)}"


@pytest.mark.asyncio
async def test_orchestrator_turn_does_not_index_anything(monkeypatch):
    """Running a full turn must not write a single point to the vector store."""
    import app.retrieval.vector_store as vs_module

    upserts = []

    class SpyStore:
        async def ensure_collection(self, collection):
            return {}

        async def upsert(self, collection_name, points):
            upserts.append((collection_name, points))

        async def search(self, collection_name, vector, limit=10, filter=None):
            return []

        async def delete(self, *a, **k):
            return {}

        async def filter_by_metadata(self, *a, **k):
            return []

    monkeypatch.setattr(vs_module, "get_vector_store", lambda backend=None: SpyStore())

    from app.orchestrator.local_orchestrator import orchestrate_full

    await orchestrate_full(query="Explain what a hash map is", chat_id="")
    assert upserts == [], "an assistant turn wrote to the vector store"


# ---------------------------------------------------------------------------
# Stale-cache prevention (spec 5)
# ---------------------------------------------------------------------------

def test_retrieval_cache_key_distinguishes_queries_and_chats():
    from app.jobs.cache import cache_key

    assert cache_key("weather in Paris", "chat-1") != cache_key("weather in Tokyo", "chat-1")
    assert cache_key("weather in Paris", "chat-1") != cache_key("weather in Paris", "chat-2")
    # Same question in the same chat is a legitimate hit.
    assert cache_key("weather in Paris", "chat-1") == cache_key("  Weather in Paris  ", "chat-1")


def test_retrieval_cache_is_not_shared_between_unrelated_queries(monkeypatch):
    """A cached result must never be served to a different question."""
    from app.jobs.cache import cache_key, get_cached, set_cached

    key_a = cache_key("who won the 2024 election::None::True", "chat-x")
    key_b = cache_key("how do I sort a list in python::None::True", "chat-x")
    set_cached(key_a, {"contextText": "election result evidence"})

    assert get_cached(key_b) is None, "unrelated query hit another query's cache entry"
    assert get_cached(key_a)["contextText"] == "election result evidence"


def test_web_search_cache_key_includes_the_full_query():
    """Guards against caching keyed on a generic term (e.g. just the topic),
    which would serve one request's results to an unrelated one."""
    import inspect

    from app.retrieval import web_retriever

    source = inspect.getsource(web_retriever)
    assert 'cache_key = f"ddgs::{query.strip().lower()}::{max_results}"' in source, (
        "web search cache key must be derived from the full query"
    )


def test_retrieval_cache_entries_expire():
    from app.jobs.cache import BoundedTTLCache

    cache = BoundedTTLCache(max_size=10, default_ttl_ms=0)
    cache.set("k", "v")
    assert cache.get("k") is None, "expired entry was served"


# ---------------------------------------------------------------------------
# Client abort must stop server-side generation (spec 8)
# ---------------------------------------------------------------------------

from app.utils.stream_cancel import drain_task_queue


@pytest.mark.asyncio
async def test_drain_task_queue_yields_everything_on_normal_completion():
    queue: asyncio.Queue = asyncio.Queue()

    async def produce():
        for i in range(5):
            queue.put_nowait(i)
            await asyncio.sleep(0.01)
        return "finished"

    task = asyncio.create_task(produce())
    received = [item async for item in drain_task_queue(task, queue, poll_interval=0.01)]

    assert received == [0, 1, 2, 3, 4]
    assert await task == "finished"


@pytest.mark.asyncio
async def test_abandoning_the_stream_cancels_background_generation():
    """The regression this guards: the client aborts, the SSE generator is
    closed, but Ollama keeps generating because the task was detached."""
    queue: asyncio.Queue = asyncio.Queue()
    completed = False

    async def long_generation():
        nonlocal completed
        for i in range(1000):
            queue.put_nowait(i)
            await asyncio.sleep(0.01)
        completed = True
        return "should never finish"

    task = asyncio.create_task(long_generation())

    # Consume two items, then abandon the stream (as aclose() does on abort).
    stream = drain_task_queue(task, queue, poll_interval=0.01)
    await stream.__anext__()
    await stream.__anext__()
    await stream.aclose()

    await asyncio.sleep(0.05)
    assert task.cancelled() or task.done(), "background generation outlived the stream"
    assert completed is False, "generation ran to completion after the client left"


@pytest.mark.asyncio
async def test_cancelling_the_consumer_cancels_generation():
    """Same guarantee, via task cancellation rather than an explicit close."""
    queue: asyncio.Queue = asyncio.Queue()

    async def long_generation():
        for i in range(1000):
            queue.put_nowait(i)
            await asyncio.sleep(0.01)
        return "done"

    gen_task = asyncio.create_task(long_generation())

    async def consumer():
        async for _ in drain_task_queue(gen_task, queue, poll_interval=0.01):
            pass

    consumer_task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass

    await asyncio.sleep(0.05)
    assert gen_task.cancelled() or gen_task.done()


# ---------------------------------------------------------------------------
# Code generation is retrieval-aware (spec 7)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_library_questions_trigger_documentation_retrieval(monkeypatch):
    from app.agents.code_agent import CodeAgent

    calls = []

    async def fake_retrieve(query, **kwargs):
        calls.append((query, kwargs))
        return {"contextText": "FastAPI: use @app.get('/path') to declare a route."}

    monkeypatch.setattr("app.retrieval.retrieval_service.retrieve", fake_retrieve)

    context = await CodeAgent()._retrieve_documentation("How do I add a route in FastAPI?")

    assert len(calls) == 1
    assert calls[0][1]["include_web"] is True, "library docs should consult the web too"
    assert "FastAPI" in context


@pytest.mark.asyncio
async def test_self_contained_algorithm_questions_skip_retrieval(monkeypatch):
    """A retrieval round-trip would only add latency here."""
    from app.agents.code_agent import CodeAgent

    called = False

    async def fake_retrieve(query, **kwargs):
        nonlocal called
        called = True
        return {"contextText": "x"}

    monkeypatch.setattr("app.retrieval.retrieval_service.retrieve", fake_retrieve)

    context = await CodeAgent()._retrieve_documentation("Write a function to reverse a string")

    assert context == ""
    assert called is False


@pytest.mark.asyncio
async def test_documentation_retrieval_failure_never_blocks_code_generation(monkeypatch):
    from app.agents.code_agent import CodeAgent

    async def boom(query, **kwargs):
        raise RuntimeError("vector store down")

    monkeypatch.setattr("app.retrieval.retrieval_service.retrieve", boom)

    assert await CodeAgent()._retrieve_documentation("How do I use the React useEffect API?") == ""


def test_retrieved_docs_are_injected_before_generation():
    """Evidence-first: documentation must be in the prompt, not requested after."""
    from app.agents.code_agent import _build_doc_grounded_prompt

    prompt = _build_doc_grounded_prompt(
        "How do I add a route in FastAPI?",
        "FastAPI: use @app.get('/path') to declare a route.",
    )
    assert "How do I add a route in FastAPI?" in prompt
    assert "[RETRIEVED LIBRARY/API DOCUMENTATION]" in prompt
    assert "@app.get" in prompt
    assert prompt.index("How do I add a route") < prompt.index("[RETRIEVED LIBRARY")


# ---------------------------------------------------------------------------
# No external AI APIs anywhere (spec: fully local)
# ---------------------------------------------------------------------------

def test_no_external_ai_provider_is_referenced_in_server_code():
    import pathlib
    import re

    app_dir = pathlib.Path(__file__).parent.parent / "app"
    forbidden = re.compile(
        r"\b(openai|anthropic|api\.gemini|generativelanguage|edge_tts|edge-tts|"
        r"elevenlabs|azure\.cognitiveservices|deepgram|assemblyai)\b",
        re.I,
    )

    offenders = []
    for path in app_dir.rglob("*.py"):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            # Comments explaining what was removed are fine.
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            if forbidden.search(line):
                offenders.append(f"{path.relative_to(app_dir)}:{i}: {stripped}")

    assert offenders == [], "external AI provider referenced:\n" + "\n".join(offenders)
