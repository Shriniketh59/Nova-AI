import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_local_voice_config():
    """Verify local voice config returns offline engines and no Gemini dependency."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.get("/api/voice/config")
        assert res.status_code == 200
        data = res.json()
        assert data["engine"] == "local"
        assert data["stt"] == "faster-whisper"
        assert "espeak-ng" in data["tts"]
        assert "qwen" in data["llm"]
        assert data["geminiConfigured"] is False
        assert data["wsEndpoint"] == "/ws/voice/local"


@pytest.mark.asyncio
async def test_voice_retrieval_endpoint():
    """Verify /api/voice/retrieval returns knowledge grounding from local vector DB/orchestrator."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.post("/api/voice/retrieval", json={"query": "Who is the current Chief Minister of Karnataka?"})
        assert res.status_code == 200
        data = res.json()
        assert "result" in data
        assert isinstance(data["result"], str)
        assert len(data["result"]) > 0


@pytest.mark.asyncio
async def test_voice_chat_local_reply():
    """Verify /api/voice/chat generates local voice reply."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.post("/api/voice/chat", json={"message": "hello Nova voice"})
        assert res.status_code == 200
        data = res.json()
        assert "reply" in data
        assert data["reply"] != ""
