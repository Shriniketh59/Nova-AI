"""Vector store abstraction.

Defines a backend-agnostic `VectorStore` interface (upsert / search / delete /
filter-by-metadata) and a factory (`get_vector_store`) that picks an
implementation based on `VECTOR_STORE_BACKEND` (see app/core/config.py).

Chroma is the default backend: a fully local, embedded, persistent store
(no server process, no network, no API key). Qdrant is also fully implemented
(it wraps the existing functional module in qdrant_client.py, which callers
can keep importing directly) and stays selectable via
VECTOR_STORE_BACKEND=qdrant. FAISS and Milvus are stubbed so the factory and
call sites are ready, but raise NotImplementedError.

All backends speak the same wire shapes so call sites are backend-agnostic:

  point   {"id": str, "vector": list[float], "payload": dict}
  result  {"id": str, "score": float, "payload": dict}
  filter  Qdrant-style, e.g.
          {"must": [{"key": "document_id", "match": {"value": "x"}},
                    {"key": "file_id",     "match": {"any": ["a", "b"]}}]}

ChromaVectorStore translates that filter dialect into Chroma `where` clauses.
"""

import asyncio
import os
import threading
from abc import ABC, abstractmethod

from ..core.config import CHROMA_PATH, QDRANT_URL, VECTOR_STORE_BACKEND
from ..core.logger import logger
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


# ---------------------------------------------------------------------------
# Chroma
# ---------------------------------------------------------------------------

# Chroma metadata values must be scalars (str/int/float/bool). Chunk text is
# stored in Chroma's `documents` field instead, and re-merged into `payload`
# on read so callers see the same shape Qdrant returns.
_CONTENT_KEY = "content"


def _scalar_metadata(payload: dict) -> dict:
    """Coerce a Qdrant-style payload into Chroma-legal metadata.

    Drops the content field (stored as the Chroma document) and any None
    values (Chroma rejects them), and JSON-ish-stringifies anything that is
    not already a scalar.
    """
    meta: dict = {}
    for key, value in (payload or {}).items():
        if key == _CONTENT_KEY or value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            meta[key] = value
        else:
            meta[key] = str(value)
    return meta


def _to_chroma_where(filter: dict | None) -> dict | None:
    """Translate the Qdrant-style filter dialect used across the codebase into
    a Chroma `where` clause. Returns None when there is nothing to filter on."""
    if not filter:
        return None

    clauses: list[dict] = []
    for condition in filter.get("must", []) or []:
        key = condition.get("key")
        match = condition.get("match") or {}
        if not key:
            continue
        if "any" in match:
            values = list(match["any"] or [])
            if values:
                clauses.append({key: {"$in": values}})
        elif "value" in match:
            clauses.append({key: {"$eq": match["value"]}})

    if not clauses:
        return None
    # Chroma rejects a single-element $and, so unwrap it.
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


class ChromaVectorStore(VectorStore):
    """Embedded, persistent ChromaDB backend — fully local, no server or API key.

    Uses `chromadb.PersistentClient(path=CHROMA_PATH)`. The chromadb client is
    synchronous and not async-safe, so every call is dispatched to a worker
    thread and guarded by a lock.
    """

    _client = None
    _client_lock = threading.Lock()

    @classmethod
    def _get_client(cls):
        if cls._client is None:
            with cls._client_lock:
                if cls._client is None:
                    import chromadb
                    from chromadb.config import Settings

                    os.makedirs(CHROMA_PATH, exist_ok=True)
                    cls._client = chromadb.PersistentClient(
                        path=CHROMA_PATH,
                        settings=Settings(anonymized_telemetry=False, allow_reset=False),
                    )
                    logger.info("chroma.client_ready", {"path": CHROMA_PATH})
        return cls._client

    @classmethod
    def reset_client(cls):
        """Drop the cached client (used by tests that repoint CHROMA_PATH)."""
        with cls._client_lock:
            cls._client = None

    def _collection(self, name: str, vector_size: int | None = None):
        """get-or-create, so every entry point is idempotent like Qdrant's."""
        client = self._get_client()
        metadata = {"hnsw:space": "cosine"}
        if vector_size:
            metadata["nova:vector_size"] = vector_size
        return client.get_or_create_collection(name=name, metadata=metadata)

    @staticmethod
    async def _run(fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    async def ensure_collection(self, collection: dict):
        def _do():
            col = self._collection(collection["name"], collection.get("vectorSize"))
            return {"status": "ok", "name": col.name}

        return await self._run(_do)

    async def upsert(self, collection_name: str, points: list[dict]):
        if not points:
            return {"status": "ok", "upserted": 0}

        def _do():
            col = self._collection(collection_name)
            ids, embeddings, metadatas, documents = [], [], [], []
            for p in points:
                payload = p.get("payload") or {}
                # Chroma requires string ids; DB ids may be ints/UUID objects.
                ids.append(str(p["id"]))
                embeddings.append(list(p["vector"]))
                metadatas.append(_scalar_metadata(payload))
                documents.append(payload.get(_CONTENT_KEY) or "")
            col.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)
            return {"status": "ok", "upserted": len(ids)}

        return await self._run(_do)

    async def search(
        self,
        collection_name: str,
        vector: list[float],
        limit: int = 10,
        filter: dict | None = None,
    ) -> list[dict]:
        def _do():
            col = self._collection(collection_name)
            if col.count() == 0:
                return []
            where = _to_chroma_where(filter)
            res = col.query(
                query_embeddings=[list(vector)],
                n_results=max(1, limit),
                where=where,
                include=["metadatas", "documents", "distances"],
            )
            ids = (res.get("ids") or [[]])[0]
            metadatas = (res.get("metadatas") or [[]])[0]
            documents = (res.get("documents") or [[]])[0]
            distances = (res.get("distances") or [[]])[0]

            out = []
            for i, point_id in enumerate(ids):
                meta = dict(metadatas[i] or {}) if i < len(metadatas) else {}
                content = documents[i] if i < len(documents) else ""
                distance = distances[i] if i < len(distances) else 1.0
                # Collection uses cosine space, so distance = 1 - cosine
                # similarity. Clamp because HNSW can return tiny negatives.
                score = max(0.0, min(1.0, 1.0 - float(distance)))
                out.append({
                    "id": point_id,
                    "score": score,
                    "payload": {**meta, _CONTENT_KEY: content},
                })
            return out

        return await self._run(_do)

    async def delete(self, collection_name: str, point_ids: list[str] | None = None, filter: dict | None = None):
        if point_ids is None and filter is None:
            raise ValueError("delete() requires either point_ids or filter")

        def _do():
            col = self._collection(collection_name)
            if point_ids is not None:
                col.delete(ids=[str(p) for p in point_ids])
            else:
                where = _to_chroma_where(filter)
                if where is None:
                    raise ValueError("delete() filter did not translate to any Chroma condition")
                col.delete(where=where)
            return {"status": "ok"}

        return await self._run(_do)

    async def filter_by_metadata(self, collection_name: str, filter: dict, limit: int = 100) -> list[dict]:
        def _do():
            col = self._collection(collection_name)
            where = _to_chroma_where(filter)
            res = col.get(where=where, limit=limit, include=["metadatas", "documents"])
            ids = res.get("ids") or []
            metadatas = res.get("metadatas") or []
            documents = res.get("documents") or []
            return [
                {
                    "id": point_id,
                    "payload": {
                        **(dict(metadatas[i]) if i < len(metadatas) and metadatas[i] else {}),
                        _CONTENT_KEY: documents[i] if i < len(documents) else "",
                    },
                }
                for i, point_id in enumerate(ids)
            ]

        return await self._run(_do)


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


def vector_store_enabled(backend: str | None = None) -> bool:
    """Whether a usable vector store is configured.

    Chroma is embedded and always available once the package is installed, so
    it needs no URL. Qdrant is a remote service and is only considered enabled
    when QDRANT_URL is set — which is why call sites used to gate on
    QDRANT_URL directly. They should call this instead so the gate follows the
    configured backend.
    """
    name = (backend or VECTOR_STORE_BACKEND).lower()
    if name in ("chroma", "chromadb"):
        return True
    if name == "qdrant":
        return bool(QDRANT_URL)
    return False
