import json

import pytest
import respx
from httpx import Response

from .conftest import requires_db
from app.core import db
from app.core.config import DEFAULT_USER_ID


async def _insert_chunk(chat_title, filename, content):
    chat = await db.query("INSERT INTO chats (user_id, title) VALUES ($1, $2) RETURNING *", [DEFAULT_USER_ID, chat_title])
    chat_id = chat["rows"][0]["id"]
    msg = await db.query("INSERT INTO messages (chat_id, role, content) VALUES ($1, $2, $3) RETURNING *", [chat_id, "user", "upload"])
    file = await db.query(
        "INSERT INTO uploaded_files (message_id, user_id, filename, original_filename, mime_type, size_bytes, file_path) VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *",
        [msg["rows"][0]["id"], DEFAULT_USER_ID, filename, filename, "text/plain", 10, f"/tmp/{filename}"],
    )
    await db.query(
        "INSERT INTO document_chunks (file_id, content, embedding, page_number) VALUES ($1, $2, $3, $4)",
        [file["rows"][0]["id"], content, json.dumps([0.5] * 384), None],
    )
    return chat_id


@requires_db
@pytest.mark.asyncio
async def test_retrieves_an_uploaded_chunk_relevant_to_the_query(app_client):
    from app.retrieval.retrieval_service import retrieve

    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/embeddings").mock(return_value=Response(200, json={"embedding": [0.5] * 384}))
        mock.post(url__regex=r".*/api/chat").mock(return_value=Response(200, json={"message": {"content": ""}}))

        chat_id = await _insert_chunk("retrieval test", "a.txt", "Nova AI uses Qdrant for vector search.")
        result = await retrieve("What does Nova AI use for vector search?", chat_id, top_k=5)

    assert len(result["chunks"]) > 0
    assert "Qdrant" in result["contextText"]


@requires_db
@pytest.mark.asyncio
async def test_returns_empty_result_for_a_chat_with_no_uploaded_documents(app_client):
    from app.retrieval.retrieval_service import retrieve

    chat = await db.query("INSERT INTO chats (user_id, title) VALUES ($1, $2) RETURNING *", [DEFAULT_USER_ID, "empty chat"])
    result = await retrieve("anything", chat["rows"][0]["id"], top_k=5)
    assert result["chunks"] == []


@requires_db
@pytest.mark.asyncio
async def test_falls_back_to_cosine_search_when_qdrant_unreachable(app_client, monkeypatch):
    from app.retrieval.semantic_search import semantic_search
    import app.retrieval.semantic_search as semantic_search_module

    monkeypatch.setattr(semantic_search_module, "QDRANT_URL", "http://127.0.0.1:1")

    with respx.mock(assert_all_called=False) as mock:
        mock.post(url__regex=r".*/api/embeddings").mock(return_value=Response(200, json={"embedding": [0.5] * 384}))
        chat_id = await _insert_chunk("qdrant fallback", "b.txt", "fallback content")
        results = await semantic_search("fallback content", chat_id, 5)

    assert len(results) > 0
