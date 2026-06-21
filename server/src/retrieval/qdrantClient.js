// Thin REST wrapper around Qdrant. Not wired to a running instance yet —
// current retrieval still goes through rag.js's in-JS cosine search.
// Once a Qdrant container is up, point QDRANT_URL at it and swap
// retrievalService.js's semanticSearch() to use this client.
const QDRANT_URL = process.env.QDRANT_URL || 'http://127.0.0.1:6333';

export const COLLECTIONS = {
  documents: { name: 'nova_documents', vectorSize: 384, distance: 'Cosine' },
  code: { name: 'nova_code', vectorSize: 384, distance: 'Cosine' },
  web: { name: 'nova_web', vectorSize: 384, distance: 'Cosine' },
  media: { name: 'nova_media', vectorSize: 384, distance: 'Cosine' }
};

async function request(path, options = {}) {
  const res = await fetch(`${QDRANT_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`Qdrant ${options.method || 'GET'} ${path} failed: ${res.status} ${body}`);
  }
  return res.json();
}

export async function ensureCollection(collection) {
  return request(`/collections/${collection.name}`, {
    method: 'PUT',
    body: JSON.stringify({
      vectors: { size: collection.vectorSize, distance: collection.distance }
    })
  });
}

export async function ensureAllCollections() {
  return Promise.all(Object.values(COLLECTIONS).map(ensureCollection));
}

export async function upsertPoints(collectionName, points) {
  // points: [{ id, vector, payload }]
  return request(`/collections/${collectionName}/points?wait=true`, {
    method: 'PUT',
    body: JSON.stringify({ points })
  });
}

export async function search(collectionName, vector, { limit = 10, filter } = {}) {
  const data = await request(`/collections/${collectionName}/points/search`, {
    method: 'POST',
    body: JSON.stringify({ vector, limit, filter, with_payload: true })
  });
  return data.result; // [{ id, score, payload }]
}
