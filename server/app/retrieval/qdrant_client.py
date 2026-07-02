import httpx

from ..core.config import QDRANT_URL

COLLECTIONS = {
    "documents": {"name": "nova_documents", "vectorSize": 384, "distance": "Cosine"},
    "code": {"name": "nova_code", "vectorSize": 384, "distance": "Cosine"},
    "web": {"name": "nova_web", "vectorSize": 384, "distance": "Cosine"},
    "media": {"name": "nova_media", "vectorSize": 384, "distance": "Cosine"},
}


async def _request(path: str, method: str = "GET", json: dict | None = None) -> dict:
    url = f"{QDRANT_URL}{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.request(method, url, json=json, headers={"Content-Type": "application/json"})
        if res.status_code >= 400:
            raise RuntimeError(f"Qdrant {method} {path} failed: {res.status_code} {res.text}")
        return res.json()


async def ensure_collection(collection: dict):
    # Qdrant's create-collection PUT is not idempotent — it 409s if the
    # collection already exists (e.g. from a prior run). Treat that as success
    # instead of tearing down/recreating (would drop existing vectors).
    url = f"{QDRANT_URL}/collections/{collection['name']}"
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.put(
            url,
            json={"vectors": {"size": collection["vectorSize"], "distance": collection["distance"]}},
            headers={"Content-Type": "application/json"},
        )
        if res.status_code >= 400 and "already exists" not in res.text:
            raise RuntimeError(f"Qdrant PUT /collections/{collection['name']} failed: {res.status_code} {res.text}")
        return res.json() if res.status_code < 400 else {"status": "already_exists"}


async def ensure_all_collections():
    for collection in COLLECTIONS.values():
        await ensure_collection(collection)


async def upsert_points(collection_name: str, points: list[dict]):
    return await _request(
        f"/collections/{collection_name}/points?wait=true",
        method="PUT",
        json={"points": points},
    )


async def search(collection_name: str, vector: list[float], limit: int = 10, filter: dict | None = None):
    data = await _request(
        f"/collections/{collection_name}/points/search",
        method="POST",
        json={"vector": vector, "limit": limit, "filter": filter, "with_payload": True},
    )
    return data["result"]
