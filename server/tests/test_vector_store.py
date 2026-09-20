import pytest
import respx
from httpx import Response

from app.retrieval.vector_store import (
    ChromaVectorStore,
    QdrantVectorStore,
    VectorStore,
    get_vector_store,
)


def test_get_vector_store_defaults_to_chroma():
    """ChromaDB is the mandated default backend (fully local, no server)."""
    from app.core.config import VECTOR_STORE_BACKEND

    assert VECTOR_STORE_BACKEND == "chroma"
    store = get_vector_store()
    assert isinstance(store, ChromaVectorStore)
    assert isinstance(store, VectorStore)


def test_qdrant_remains_selectable(monkeypatch):
    """Switching the default must not remove the working Qdrant backend."""
    import app.retrieval.vector_store as vs_module

    monkeypatch.setattr(vs_module, "VECTOR_STORE_BACKEND", "qdrant")
    store = get_vector_store()
    assert isinstance(store, QdrantVectorStore)


@pytest.mark.parametrize("name,cls", [("chroma", ChromaVectorStore), ("chromadb", ChromaVectorStore)])
def test_get_vector_store_resolves_alternate_backends_by_name(name, cls):
    store = get_vector_store(name)
    assert isinstance(store, cls)


def test_get_vector_store_rejects_unknown_backend():
    with pytest.raises(ValueError):
        get_vector_store("not-a-real-backend")


def test_vector_store_is_abstract_and_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        VectorStore()


@pytest.mark.asyncio
async def test_qdrant_vector_store_search_hits_the_expected_endpoint(monkeypatch):
    import app.retrieval.qdrant_client as qdrant_client

    monkeypatch.setattr(qdrant_client, "QDRANT_URL", "http://qdrant.test")

    with respx.mock(assert_all_called=True) as mock:
        mock.post("http://qdrant.test/collections/nova_documents/points/search").mock(
            return_value=Response(200, json={"result": [{"id": "1", "score": 0.9, "payload": {"content": "hi"}}]})
        )
        store = QdrantVectorStore()
        results = await store.search("nova_documents", [0.1, 0.2], limit=5)

    assert results == [{"id": "1", "score": 0.9, "payload": {"content": "hi"}}]


@pytest.mark.asyncio
async def test_qdrant_vector_store_delete_requires_ids_or_filter(monkeypatch):
    import app.retrieval.qdrant_client as qdrant_client

    monkeypatch.setattr(qdrant_client, "QDRANT_URL", "http://qdrant.test")
    store = QdrantVectorStore()
    with pytest.raises(ValueError):
        await store.delete("nova_documents")


@pytest.mark.asyncio
async def test_qdrant_vector_store_delete_by_filter(monkeypatch):
    import app.retrieval.qdrant_client as qdrant_client

    monkeypatch.setattr(qdrant_client, "QDRANT_URL", "http://qdrant.test")

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://qdrant.test/collections/nova_documents/points/delete").mock(
            return_value=Response(200, json={"result": {"status": "acknowledged"}})
        )
        store = QdrantVectorStore()
        await store.delete("nova_documents", filter={"must": [{"key": "file_id", "match": {"value": "abc"}}]})

    assert route.called
    sent_body = route.calls[0].request.content
    assert b"file_id" in sent_body


# ---------------------------------------------------------------------------
# ChromaVectorStore — real, against the embedded chromadb client
# ---------------------------------------------------------------------------

@pytest.fixture
def chroma_store(tmp_path, monkeypatch):
    """A ChromaVectorStore backed by a fresh, throwaway persistent directory."""
    import app.retrieval.vector_store as vs_module

    monkeypatch.setattr(vs_module, "CHROMA_PATH", str(tmp_path / "chroma"))
    ChromaVectorStore.reset_client()
    yield ChromaVectorStore()
    ChromaVectorStore.reset_client()


COLLECTION = {"name": "nova_test_documents", "vectorSize": 4, "distance": "Cosine"}


async def _seed(store):
    await store.ensure_collection(COLLECTION)
    await store.upsert(COLLECTION["name"], [
        {
            "id": 101,  # non-string id — Chroma requires strings, store must coerce
            "vector": [1.0, 0.0, 0.0, 0.0],
            "payload": {
                "content": "Nova uses ChromaDB for local vector retrieval.",
                "document_id": "doc-a", "file_id": "file-a", "category": "architecture",
                "page_number": None,  # None is illegal in Chroma metadata
            },
        },
        {
            "id": "102",
            "vector": [0.0, 1.0, 0.0, 0.0],
            "payload": {
                "content": "Unrelated content about gardening.",
                "document_id": "doc-b", "file_id": "file-b", "category": "hobby",
            },
        },
        {
            "id": "103",
            "vector": [0.95, 0.05, 0.0, 0.0],
            "payload": {
                "content": "ChromaDB stores embeddings on local disk.",
                "document_id": "doc-a", "file_id": "file-a", "category": "architecture",
            },
        },
    ])


@pytest.mark.asyncio
async def test_chroma_upsert_and_semantic_ranking(chroma_store):
    await _seed(chroma_store)
    results = await chroma_store.search(COLLECTION["name"], [1.0, 0.0, 0.0, 0.0], limit=3)

    assert [r["id"] for r in results][:2] == ["101", "103"], "nearest neighbours should rank first"
    assert results[0]["payload"]["content"].startswith("Nova uses ChromaDB")
    # Cosine similarity, not raw distance — identical vector scores ~1.0.
    assert results[0]["score"] == pytest.approx(1.0, abs=1e-3)
    assert results[0]["score"] > results[1]["score"] > results[2]["score"]
    # Payload round-trips (minus the None value Chroma cannot store).
    assert results[0]["payload"]["document_id"] == "doc-a"
    assert "page_number" not in results[0]["payload"]


@pytest.mark.asyncio
async def test_chroma_search_respects_metadata_filter(chroma_store):
    await _seed(chroma_store)
    # Query vector points at doc-a, but the filter restricts to the hobby doc.
    results = await chroma_store.search(
        COLLECTION["name"], [1.0, 0.0, 0.0, 0.0], limit=5,
        filter={"must": [{"key": "category", "match": {"value": "hobby"}}]},
    )
    assert [r["id"] for r in results] == ["102"]


@pytest.mark.asyncio
async def test_chroma_search_supports_any_and_combined_filters(chroma_store):
    await _seed(chroma_store)
    results = await chroma_store.search(
        COLLECTION["name"], [1.0, 0.0, 0.0, 0.0], limit=5,
        filter={"must": [
            {"key": "file_id", "match": {"any": ["file-a", "file-zzz"]}},
            {"key": "category", "match": {"value": "architecture"}},
        ]},
    )
    assert sorted(r["id"] for r in results) == ["101", "103"]


@pytest.mark.asyncio
async def test_chroma_filter_by_metadata_without_a_query_vector(chroma_store):
    await _seed(chroma_store)
    rows = await chroma_store.filter_by_metadata(
        COLLECTION["name"], {"must": [{"key": "document_id", "match": {"value": "doc-a"}}]}
    )
    assert sorted(r["id"] for r in rows) == ["101", "103"]
    assert all("content" in r["payload"] for r in rows)


@pytest.mark.asyncio
async def test_chroma_delete_by_filter_and_by_id(chroma_store):
    await _seed(chroma_store)
    await chroma_store.delete(
        COLLECTION["name"], filter={"must": [{"key": "document_id", "match": {"value": "doc-a"}}]}
    )
    remaining = await chroma_store.search(COLLECTION["name"], [1.0, 0.0, 0.0, 0.0], limit=5)
    assert [r["id"] for r in remaining] == ["102"]

    await chroma_store.delete(COLLECTION["name"], point_ids=["102"])
    assert await chroma_store.search(COLLECTION["name"], [1.0, 0.0, 0.0, 0.0], limit=5) == []


@pytest.mark.asyncio
async def test_chroma_delete_requires_ids_or_filter(chroma_store):
    await chroma_store.ensure_collection(COLLECTION)
    with pytest.raises(ValueError):
        await chroma_store.delete(COLLECTION["name"])


@pytest.mark.asyncio
async def test_chroma_search_on_empty_collection_returns_empty(chroma_store):
    await chroma_store.ensure_collection(COLLECTION)
    assert await chroma_store.search(COLLECTION["name"], [1.0, 0.0, 0.0, 0.0]) == []


@pytest.mark.asyncio
async def test_chroma_ensure_collection_is_idempotent(chroma_store):
    await chroma_store.ensure_collection(COLLECTION)
    await chroma_store.ensure_collection(COLLECTION)  # must not raise
    await _seed(chroma_store)
    await chroma_store.ensure_collection(COLLECTION)
    assert len(await chroma_store.search(COLLECTION["name"], [1.0, 0.0, 0.0, 0.0], limit=5)) == 3


# ---------------------------------------------------------------------------
# Filter dialect translation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("qdrant_filter,expected", [
    (None, None),
    ({}, None),
    ({"must": []}, None),
    ({"must": [{"key": "a", "match": {"value": 1}}]}, {"a": {"$eq": 1}}),
    ({"must": [{"key": "a", "match": {"any": ["x", "y"]}}]}, {"a": {"$in": ["x", "y"]}}),
    ({"must": [{"key": "a", "match": {"any": []}}]}, None),
    (
        {"must": [{"key": "a", "match": {"value": 1}}, {"key": "b", "match": {"value": 2}}]},
        {"$and": [{"a": {"$eq": 1}}, {"b": {"$eq": 2}}]},
    ),
])
def test_qdrant_filter_dialect_translates_to_chroma_where(qdrant_filter, expected):
    from app.retrieval.vector_store import _to_chroma_where

    assert _to_chroma_where(qdrant_filter) == expected


def test_scalar_metadata_drops_content_and_nulls():
    from app.retrieval.vector_store import _scalar_metadata

    meta = _scalar_metadata({
        "content": "body text", "page_number": None, "title": "t",
        "freshness_score": 0.5, "indexed": True, "tags": ["a", "b"],
    })
    assert "content" not in meta and "page_number" not in meta
    assert meta["title"] == "t" and meta["freshness_score"] == 0.5 and meta["indexed"] is True
    assert isinstance(meta["tags"], str), "non-scalars must be stringified for Chroma"


# ---------------------------------------------------------------------------
# Backend enablement gate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("backend,qdrant_url,expected", [
    ("chroma", None, True),       # embedded — always available, needs no URL
    ("chromadb", None, True),
    ("qdrant", None, False),      # remote — needs QDRANT_URL
    ("qdrant", "http://localhost:6333", True),
    ("faiss", None, False),
])
def test_vector_store_enabled_follows_the_configured_backend(monkeypatch, backend, qdrant_url, expected):
    import app.retrieval.vector_store as vs_module
    from app.retrieval.vector_store import vector_store_enabled

    monkeypatch.setattr(vs_module, "QDRANT_URL", qdrant_url)
    assert vector_store_enabled(backend) is expected
