"""Vector store abstraction.

Defines a backend-agnostic `VectorStore` interface (upsert / search / delete /
filter-by-metadata) and a factory (`get_vector_store`) that picks an
implementation based on `VECTOR_STORE_BACKEND` (see app/core/config.py).

Qdrant is the only fully implemented backend today (it wraps the existing
functional module in qdrant_client.py, which callers can keep importing
directly — this class is an additive wrapper, not a replacement). Chroma,
FAISS and Milvus are stubbed so the factory and call sites are ready, but
they raise NotImplementedError until a real implementation is added.
"""

from abc import ABC, abstractmethod

from ..core.config import VECTOR_STORE_BACKEND
from . import qdrant_client


class VectorStore(ABC):
    """Backend-agnostic interface for vector storage/retrieval."""

    @abstractmethod
    async def ensure_collection(self, collection: dict):
        """Create the collection/index if it doesn't already exist."""

    @abstractmethod
    async def upsert(self, collection_name: str, points: list[dict]):
        """Add or update points (each with id/vector/payload) in a collection."""

    @abstractmethod
    async def search(
        self,
        collection_name: str,
        vector: list[float],
        limit: int = 10,
        filter: dict | None = None,
    ) -> list[dict]:
        """Nearest-neighbour search, optionally constrained by a metadata filter."""

    @abstractmethod
    async def delete(self, collection_name: str, point_ids: list[str] | None = None, filter: dict | None = None):
        """Remove points either by explicit id list or by metadata filter
        (exactly one of point_ids/filter should be given)."""

    @abstractmethod
    async def filter_by_metadata(self, collection_name: str, filter: dict, limit: int = 100) -> list[dict]:
        """Fetch points matching a metadata filter without a query vector."""


class QdrantVectorStore(VectorStore):
    """Class-based adapter over the existing functional qdrant_client module."""

    async def ensure_collection(self, collection: dict):
        return await qdrant_client.ensure_collection(collection)

    async def upsert(self, collection_name: str, points: list[dict]):
        return await qdrant_client.upsert_points(collection_name, points)

    async def search(
        self,
        collection_name: str,
        vector: list[float],
        limit: int = 10,
        filter: dict | None = None,
    ) -> list[dict]:
        return await qdrant_client.search(collection_name, vector, limit=limit, filter=filter)

    async def delete(self, collection_name: str, point_ids: list[str] | None = None, filter: dict | None = None):
        body: dict = {}
        if point_ids is not None:
            body["points"] = point_ids
        if filter is not None:
            body["filter"] = filter
        if not body:
            raise ValueError("delete() requires either point_ids or filter")
        return await qdrant_client._request(
            f"/collections/{collection_name}/points/delete?wait=true",
            method="POST",
            json=body,
        )

    async def filter_by_metadata(self, collection_name: str, filter: dict, limit: int = 100) -> list[dict]:
        data = await qdrant_client._request(
            f"/collections/{collection_name}/points/scroll",
            method="POST",
            json={"filter": filter, "limit": limit, "with_payload": True},
        )
        return data["result"]["points"]


class ChromaVectorStore(VectorStore):
    """Not implemented: chromadb is not in requirements.txt / installed.

    To enable: add `chromadb` to server/requirements.txt, implement the
    methods below against chromadb's client API, and set
    VECTOR_STORE_BACKEND=chroma.
    """

    async def ensure_collection(self, collection: dict):
        raise NotImplementedError("ChromaVectorStore: chromadb dependency not installed")

    async def upsert(self, collection_name: str, points: list[dict]):
        raise NotImplementedError("ChromaVectorStore: chromadb dependency not installed")

    async def search(self, collection_name, vector, limit=10, filter=None):
        raise NotImplementedError("ChromaVectorStore: chromadb dependency not installed")

    async def delete(self, collection_name: str, point_ids: list[str] | None = None, filter: dict | None = None):
        raise NotImplementedError("ChromaVectorStore: chromadb dependency not installed")

    async def filter_by_metadata(self, collection_name: str, filter: dict, limit: int = 100):
        raise NotImplementedError("ChromaVectorStore: chromadb dependency not installed")


class FaissVectorStore(VectorStore):
    """Not implemented: FAISS has no metadata-filtering or HTTP server story
    here; would need a local index file + sidecar payload store. Stubbed for
    future work."""

    async def ensure_collection(self, collection: dict):
        raise NotImplementedError("FaissVectorStore is not implemented")

    async def upsert(self, collection_name: str, points: list[dict]):
        raise NotImplementedError("FaissVectorStore is not implemented")

    async def search(self, collection_name, vector, limit=10, filter=None):
        raise NotImplementedError("FaissVectorStore is not implemented")

    async def delete(self, collection_name: str, point_ids: list[str] | None = None, filter: dict | None = None):
        raise NotImplementedError("FaissVectorStore is not implemented")

    async def filter_by_metadata(self, collection_name: str, filter: dict, limit: int = 100):
        raise NotImplementedError("FaissVectorStore is not implemented")


class MilvusVectorStore(VectorStore):
    """Not implemented: no Milvus client dependency installed."""

    async def ensure_collection(self, collection: dict):
        raise NotImplementedError("MilvusVectorStore is not implemented")

    async def upsert(self, collection_name: str, points: list[dict]):
        raise NotImplementedError("MilvusVectorStore is not implemented")

    async def search(self, collection_name, vector, limit=10, filter=None):
        raise NotImplementedError("MilvusVectorStore is not implemented")

    async def delete(self, collection_name: str, point_ids: list[str] | None = None, filter: dict | None = None):
        raise NotImplementedError("MilvusVectorStore is not implemented")

    async def filter_by_metadata(self, collection_name: str, filter: dict, limit: int = 100):
        raise NotImplementedError("MilvusVectorStore is not implemented")


_BACKENDS = {
    "qdrant": QdrantVectorStore,
    "chroma": ChromaVectorStore,
    "chromadb": ChromaVectorStore,
    "faiss": FaissVectorStore,
    "milvus": MilvusVectorStore,
}


def get_vector_store(backend: str | None = None) -> VectorStore:
    """Factory: returns a VectorStore instance for the given (or configured) backend."""
    name = (backend or VECTOR_STORE_BACKEND).lower()
    cls = _BACKENDS.get(name)
    if cls is None:
        raise ValueError(f"Unknown VECTOR_STORE_BACKEND '{name}'. Options: {sorted(_BACKENDS)}")
    return cls()
