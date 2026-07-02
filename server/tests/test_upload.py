import pytest
import respx
from httpx import Response

from .conftest import requires_db


@requires_db
@pytest.mark.asyncio
async def test_parses_chunks_and_embeds_an_uploaded_text_file(app_client):
    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/embeddings").mock(
            return_value=Response(200, json={"embedding": [0.01] * 384})
        )

        res = await app_client.post(
            "/api/upload",
            files={"file": ("note.txt", b"Nova AI is a local-first agentic assistant.", "text/plain")},
        )

    assert res.status_code == 201
    body = res.json()
    assert body["success"] is True
    assert body["file"]["name"] == "note.txt"
