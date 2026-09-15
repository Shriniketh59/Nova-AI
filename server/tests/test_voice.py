import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.voice_service import _clean_spoken_text, generate_voice_reply


def test_clean_spoken_text():
    raw = "Here is **bold** and *italic* text with `code` and # Header\n* Item 1\n* Item 2"
    cleaned = _clean_spoken_text(raw)
    assert "**" not in cleaned
    assert "*" not in cleaned
    assert "#" not in cleaned
    assert "`" not in cleaned
    assert "bold and italic text with and Header Item 1 Item 2" in cleaned


@pytest.mark.asyncio
async def test_voice_config_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.get("/api/voice/config")
        assert res.status_code == 200
        data = res.json()
        assert data["engine"] == "local"
        assert data["stt"] == "faster-whisper"
        assert data["geminiConfigured"] is False
        assert "wsEndpoint" in data


@pytest.mark.asyncio
async def test_voice_chat_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.post("/api/voice/chat", json={"message": "hello Nova voice"})
        assert res.status_code == 200
        data = res.json()
        assert "reply" in data
        assert data["reply"] != ""
        assert data["success"] is True


@pytest.mark.asyncio
async def test_voice_retrieval_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.post("/api/voice/retrieval", json={"query": "tallest player in NBA history"})
        assert res.status_code == 200
        data = res.json()
        assert "result" in data
        assert isinstance(data["result"], str)
        assert len(data["result"]) > 0
        assert "sources" in data
