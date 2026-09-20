import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.orchestrator.intent_router import classify_intent, needs_web_search, needs_vector_retrieval
from app.orchestrator.local_orchestrator import orchestrate_full, orchestrate_stream


def test_intent_router_classifications():
    """Verify that user queries are correctly routed to local sub-paths."""
    # Greetings
    assert classify_intent("hello there") == "greeting"
    assert classify_intent("hey nova") == "greeting"
    assert classify_intent("good morning") == "greeting"

    # Coding
    assert classify_intent("write a python binary search function") == "coding"
    assert classify_intent("debug this javascript code") == "coding"
    assert classify_intent("implement a fast LRU cache in Go") == "coding"

    # Math — trivial arithmetic skips retrieval/web entirely
    assert classify_intent("what is 12 * 8") == "math"
    assert classify_intent("2+2") == "math"

    # Live web retrieval is reserved for queries that actually need current
    # info — general/knowledge queries are served from the model/RAG without
    # paying for a DDGS round trip on every request.
    assert needs_web_search("current_info") is True
    assert needs_web_search("greeting") is False
    assert needs_web_search("general") is False
    assert needs_web_search("doc_query") is False


@pytest.mark.asyncio
async def test_orchestrator_greeting_fast_path():
    """Verify that greetings return instantly without external calls."""
    events = []
    async for event in orchestrate_stream(query="hello"):
        events.append(event)

    tokens = [e["token"] for e in events if "token" in e]
    assert len(tokens) > 0
    assert "Hey! What can I help you with?" in "".join(tokens)
    assert any(e.get("done") for e in events)


@pytest.mark.asyncio
async def test_orchestrator_stream_endpoint():
    """Verify POST /api/orchestrator/stream returns SSE stream."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.post("/api/orchestrator/stream", json={"query": "hi"})
        assert res.status_code == 200
        assert "text/event-stream" in res.headers.get("content-type", "")
        body = res.text
        assert "Hey! What can I help you with?" in body
        assert "[DONE]" in body
