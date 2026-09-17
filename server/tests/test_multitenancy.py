import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.db import init_db, close_db


@pytest.mark.asyncio
async def test_cross_user_isolation_and_idor_prevention():
    await init_db()
    transport = ASGITransport(app=app)

    uid_a = uuid.uuid4().hex[:8]
    uid_b = uuid.uuid4().hex[:8]
    email_a = f"user_a_{uid_a}@nova.ai"
    email_b = f"user_b_{uid_b}@nova.ai"

    # 1. User A creates chat and sends a message
    async with AsyncClient(transport=transport, base_url="http://test") as client_a:
        res_reg_a = await client_a.post("/api/auth/register", json={
            "email": email_a,
            "password": "PasswordUserA123!",
            "name": "User Alpha"
        })
        assert res_reg_a.status_code == 201

        res_chat_a = await client_a.post("/api/chats", json={"title": "Alpha Confidential Project"})
        assert res_chat_a.status_code == 201
        chat_a_id = res_chat_a.json()["id"]

        res_msg_a = await client_a.post(f"/api/chats/{chat_a_id}/messages", json={
            "role": "user",
            "content": "Alpha proprietary research formula: X=42"
        })
        assert res_msg_a.status_code == 201

    # 2. User B creates account
    async with AsyncClient(transport=transport, base_url="http://test") as client_b:
        res_reg_b = await client_b.post("/api/auth/register", json={
            "email": email_b,
            "password": "PasswordUserB123!",
            "name": "User Beta"
        })
        assert res_reg_b.status_code == 201

        # User B lists chats — must NOT see Alpha chat
        res_b_chats = await client_b.get("/api/chats")
        assert res_b_chats.status_code == 200
        b_chat_ids = [c["id"] for c in res_b_chats.json()]
        assert chat_a_id not in b_chat_ids

        # User B attempts to read User A's messages (IDOR attack) -> must return 404
        res_idor_get = await client_b.get(f"/api/chats/{chat_a_id}/messages")
        assert res_idor_get.status_code == 404

        # User B attempts to write a message into User A's chat (IDOR attack) -> must return 404
        res_idor_post = await client_b.post(f"/api/chats/{chat_a_id}/messages", json={
            "role": "user",
            "content": "Malicious injected message"
        })
        assert res_idor_post.status_code == 404

        # User B attempts to rename User A's chat (IDOR attack) -> must return 404
        res_idor_rename = await client_b.put(f"/api/chats/{chat_a_id}", json={
            "title": "Hacked Chat Title"
        })
        assert res_idor_rename.status_code == 404

        # User B attempts to delete User A's chat (IDOR attack) -> must return 404
        res_idor_del = await client_b.delete(f"/api/chats/{chat_a_id}")
        assert res_idor_del.status_code == 404

    # 3. User A can still view their original chat intact
    async with AsyncClient(transport=transport, base_url="http://test") as client_a:
        await client_a.post("/api/auth/login", json={
            "email": email_a,
            "password": "PasswordUserA123!"
        })
        res_a_msgs = await client_a.get(f"/api/chats/{chat_a_id}/messages")
        assert res_a_msgs.status_code == 200
        assert len(res_a_msgs.json()) == 1
        assert "Alpha proprietary research formula" in res_a_msgs.json()[0]["content"]

    await close_db()
