import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.db import init_db, close_db


@pytest_asyncio.fixture
async def client():
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await close_db()


@pytest.mark.asyncio
async def test_unauthenticated_request_rejected(client):
    res = await client.get("/api/chats")
    assert res.status_code == 401
    assert res.json()["detail"] == "Authentication required"


@pytest.mark.asyncio
async def test_user_registration_and_login(client):
    uid = uuid.uuid4().hex[:8]
    email = f"user_{uid}@nova.ai"
    password = "StrongPassword123!"

    # 1. Register new user
    res_reg = await client.post("/api/auth/register", json={
        "email": email,
        "password": password,
        "name": "Test Auth User"
    })
    assert res_reg.status_code == 201
    reg_data = res_reg.json()
    assert reg_data["user"]["email"] == email
    assert "token" in reg_data

    # 2. Duplicate registration blocked
    res_dup = await client.post("/api/auth/register", json={
        "email": email,
        "password": password
    })
    assert res_dup.status_code == 409

    # 3. Wrong password fails
    res_wrong = await client.post("/api/auth/login", json={
        "email": email,
        "password": "WrongPassword!"
    })
    assert res_wrong.status_code == 401

    # 4. Correct login succeeds
    res_login = await client.post("/api/auth/login", json={
        "email": email,
        "password": password
    })
    assert res_login.status_code == 200
    assert res_login.json()["user"]["name"] == "Test Auth User"

    # 5. /me endpoint works
    res_me = await client.get("/api/auth/me")
    assert res_me.status_code == 200
    assert res_me.json()["user"]["email"] == email

    # 6. Logout clears session
    res_logout = await client.post("/api/auth/logout")
    assert res_logout.status_code == 200

    # 7. Unauthenticated again
    res_chats = await client.get("/api/chats")
    assert res_chats.status_code == 401


@pytest.mark.asyncio
async def test_forgot_and_reset_password(client):
    uid = uuid.uuid4().hex[:8]
    email = f"reset_{uid}@nova.ai"

    # Register user
    await client.post("/api/auth/register", json={
        "email": email,
        "password": "OldPassword123!",
        "name": "Reset User"
    })

    # Request reset token
    res_forgot = await client.post("/api/auth/forgot-password", json={"email": email})
    assert res_forgot.status_code == 200
    token = res_forgot.json().get("reset_token")
    assert token is not None

    # Reset with token
    res_reset = await client.post("/api/auth/reset-password", json={
        "token": token,
        "new_password": "NewSuperPassword123!"
    })
    assert res_reset.status_code == 200

    # Login with old password fails
    res_old_login = await client.post("/api/auth/login", json={
        "email": email,
        "password": "OldPassword123!"
    })
    assert res_old_login.status_code == 401

    # Login with new password succeeds
    res_new_login = await client.post("/api/auth/login", json={
        "email": email,
        "password": "NewSuperPassword123!"
    })
    assert res_new_login.status_code == 200
