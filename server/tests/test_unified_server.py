import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.config import PORT


@pytest.mark.asyncio
async def test_unified_config_uses_port_5001():
    """Verify that default PORT is 5001."""
    assert PORT == 5001


@pytest.mark.asyncio
async def test_unified_server_serves_health():
    """Verify that /health and /api/health are served directly on the unified app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_unified_server_serves_orchestrator_stream():
    """Verify that the new Local Orchestrator stream endpoint (/api/orchestrator/stream) is available."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.post("/api/orchestrator/stream", json={"query": "hello"})
        assert res.status_code == 200
        assert "text/event-stream" in res.headers.get("content-type", "")
        content = res.text
        assert "Hey! What can I help you with?" in content
        assert "[DONE]" in content


@pytest.mark.asyncio
async def test_chat_query_streaming_unified(app_client):
    """Verify /api/chats/{id}/query executes and streams SSE via local orchestrator."""
    chat_res = await app_client.post("/api/chats", json={"title": "Test Chat"})
    assert chat_res.status_code == 201
    chat_id = chat_res.json()["id"]

    res = await app_client.post(f"/api/chats/{chat_id}/query", json={"query": "hello"})
    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("content-type", "")
    body = res.text
    assert "Hey! What can I help you with?" in body
    assert "[DONE]" in body
