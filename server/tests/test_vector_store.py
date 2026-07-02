import pytest
import respx
from httpx import Response

from app.retrieval.vector_store import (
    ChromaVectorStore,
    FaissVectorStore,
    MilvusVectorStore,
    QdrantVectorStore,
    VectorStore,
    get_vector_store,
)


def test_get_vector_store_defaults_to_qdrant(monkeypatch):
    import app.retrieval.vector_store as vs_module

    monkeypatch.setattr(vs_module, "VECTOR_STORE_BACKEND", "qdrant")
    store = get_vector_store()
    assert isinstance(store, QdrantVectorStore)
    assert isinstance(store, VectorStore)


@pytest.mark.parametrize("name,cls", [("chroma", ChromaVectorStore), ("faiss", FaissVectorStore), ("milvus", MilvusVectorStore)])
def test_get_vector_store_resolves_alternate_backends_by_name(name, cls):
    store = get_vector_store(name)
    assert isinstance(store, cls)


def test_get_vector_store_rejects_unknown_backend():
    with pytest.raises(ValueError):
        get_vector_store("not-a-real-backend")


@pytest.mark.asyncio
@pytest.mark.parametrize("store_cls", [ChromaVectorStore, FaissVectorStore, MilvusVectorStore])
async def test_unimplemented_backends_raise_not_implemented_on_every_method(store_cls):
    store = store_cls()
    with pytest.raises(NotImplementedError):
        await store.ensure_collection({"name": "x", "vectorSize": 4, "distance": "Cosine"})
    with pytest.raises(NotImplementedError):
        await store.upsert("x", [])
    with pytest.raises(NotImplementedError):
        await store.search("x", [0.1, 0.2])
    with pytest.raises(NotImplementedError):
        await store.delete("x", point_ids=["1"])
    with pytest.raises(NotImplementedError):
        await store.filter_by_metadata("x", {})


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
