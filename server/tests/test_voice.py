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
        assert "geminiConfigured" in data
        assert "defaultModel" in data
        assert "availableModels" in data


@pytest.mark.asyncio
async def test_voice_chat_endpoint_fallback():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.post("/api/voice/chat", json={"message": "hello Nova voice"})
        assert res.status_code == 200
        data = res.json()
        assert "reply" in data
        assert data["reply"] != ""
        assert data["success"] is True


@pytest.mark.asyncio
async def test_save_gemini_key():
    import os
    env_path = os.path.join(os.path.dirname(__file__), "../../.env")
    orig_env_content = None
    orig_env_var = os.environ.get("GEMINI_API_KEY")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            orig_env_content = f.read()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
            res = await client.post("/api/settings/gemini", json={"apiKey": "test_temp_key_verify"})
            assert res.status_code == 200
            assert res.json()["status"] == "ok"
    finally:
        if orig_env_var is not None:
            os.environ["GEMINI_API_KEY"] = orig_env_var
        if orig_env_content is not None and os.path.exists(env_path):
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(orig_env_content)
