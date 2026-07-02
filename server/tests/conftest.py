import os
import sys

os.environ.setdefault("NODE_ENV", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.core import db as db_module

# DB-dependent tests need a real Postgres reachable at DATABASE_URL (see
# docker-compose.yml's `postgres` service) — there is no JSON-file fallback
# in the Python port (dropped deliberately, see migration plan). Point
# DATABASE_URL at a disposable test database before running these.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgres://postgres:postgres@127.0.0.1:54329/nova_ai_test?sslmode=disable"
)


@pytest_asyncio.fixture
async def app_client():
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    from app.main import app

    await db_module.init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await db_module.close_db()


requires_db = pytest.mark.requires_db
