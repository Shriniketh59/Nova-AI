import pytest

from .conftest import requires_db


@requires_db
@pytest.mark.asyncio
async def test_creates_chat_saves_messages_and_lists_multiple_conversations(app_client):
    chat_a = await app_client.post("/api/chats", json={"title": "Chat A"})
    assert chat_a.status_code == 201
    assert chat_a.json()["id"]

    chat_b = await app_client.post("/api/chats", json={"title": "Chat B"})
    assert chat_b.status_code == 201

    msg = await app_client.post(f"/api/chats/{chat_a.json()['id']}/messages", json={"role": "user", "content": "hello nova"})
    assert msg.status_code == 201
    assert msg.json()["content"] == "hello nova"

    messages = await app_client.get(f"/api/chats/{chat_a.json()['id']}/messages")
    assert messages.status_code == 200
    assert len(messages.json()) == 1

    all_chats = await app_client.get("/api/chats")
    assert all_chats.status_code == 200
    ids = [c["id"] for c in all_chats.json()]
    assert chat_a.json()["id"] in ids
    assert chat_b.json()["id"] in ids
