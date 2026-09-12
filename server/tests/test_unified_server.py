import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import PORT, RAG_API_URL
from rag_api.main import stream_query_events


@pytest.mark.asyncio
async def test_unified_config_uses_port_5001():
    """Verify that default PORT is 5001 and RAG_API_URL points to 5001, not 8008."""
    assert PORT == 5001
    assert "5001" in RAG_API_URL
    assert "8008" not in RAG_API_URL


@pytest.mark.asyncio
async def test_unified_server_serves_health():
    """Verify that /health and /api/health are served directly on the unified app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_unified_server_serves_rag_endpoints():
    """Verify that RAG endpoints (/search, /query/stream) are available on the unified app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        # Search endpoint
        search_res = await client.post("/search", json={"query": "python", "max_results": 2})
        assert search_res.status_code == 200
        assert "sources" in search_res.json()

        # Query stream greeting (executes without external Ollama)
        stream_res = await client.post("/query/stream", json={"query": "hello"})
        assert stream_res.status_code == 200
        assert "application/x-ndjson" in stream_res.headers.get("content-type", "")
        content = stream_res.text
        assert "Hey! What can I help you with?" in content


def test_in_process_stream_query_events_greeting():
    """Verify stream_query_events can be consumed in-process without network overhead."""
    events = list(stream_query_events("hi", "", False))
    assert len(events) >= 2
    assert events[0] == {"sources": []}
    assert events[1]["token"] == "Hey! What can I help you with?"


@pytest.mark.asyncio
async def test_chat_query_streaming_unified(app_client):
    """Verify /api/chats/{id}/query executes and streams SSE without needing port 8008."""
    # 1. Create a chat
    chat_res = await app_client.post("/api/chats", json={"title": "Test Chat"})
    assert chat_res.status_code == 201
    chat_id = chat_res.json()["id"]

    # 2. Query the chat with a greeting (in-process streaming)
    res = await app_client.post(f"/api/chats/{chat_id}/query", json={"query": "hello"})
    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("content-type", "")
    body = res.text
    assert "Hey! What can I help you with?" in body
    assert "[DONE]" in body

