import os
import sys
import tempfile

os.environ.setdefault("NODE_ENV", "test")

# Point the embedded ChromaDB at a throwaway directory BEFORE app.core.config
# is imported, so tests never read from — or write into — the developer's real
# on-disk vector store at server/data/chroma.
_CHROMA_TEST_DIR = tempfile.mkdtemp(prefix="nova-chroma-test-")
os.environ["CHROMA_PATH"] = _CHROMA_TEST_DIR

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


@pytest.fixture(autouse=True)
def isolated_chroma(tmp_path, monkeypatch):
    """Give every test its own empty ChromaDB directory.

    Chroma is now the default backend and is always enabled (unlike Qdrant,
    which used to be a no-op whenever QDRANT_URL was unset), so indexing tests
    genuinely write vectors. Without per-test isolation those vectors leak into
    later tests' retrieval results.
    """
    import app.retrieval.vector_store as vs_module

    monkeypatch.setattr(vs_module, "CHROMA_PATH", str(tmp_path / "chroma"))
    vs_module.ChromaVectorStore.reset_client()
    yield
    vs_module.ChromaVectorStore.reset_client()


@pytest_asyncio.fixture
async def app_client():
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    from app.main import app

    await db_module.init_db()
    from app.services.auth_service import create_access_token
    from app.core.config import DEFAULT_USER_ID, AUTH_COOKIE_NAME
    token = create_access_token(DEFAULT_USER_ID, "dr.john.doe@nova.ai")

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
        cookies={AUTH_COOKIE_NAME: token},
    ) as client:
        yield client
    await db_module.close_db()


requires_db = pytest.mark.requires_db
