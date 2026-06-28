// Minimal in-memory TTL cache for retrieval results, keyed by query+chatId.
// Real implementation (not a stub) since it's a pure perf optimization with
// no external dependency — swap for Redis later by changing only this file.
const store = new Map();
const DEFAULT_TTL_MS = parseInt(process.env.RETRIEVAL_CACHE_TTL_MS || '60000', 10);

export function cacheKey(query, chatId) {
  return `${chatId}::${query.trim().toLowerCase()}`;
}

export function getCached(key) {
  const entry = store.get(key);
  if (!entry) return null;
  if (Date.now() > entry.expiresAt) {
    store.delete(key);
    return null;
  }
  return entry.value;
}

export function setCached(key, value, ttlMs = DEFAULT_TTL_MS) {
  store.set(key, { value, expiresAt: Date.now() + ttlMs });
}

// Embedding cache: same text always produces the same vector (deterministic
// model), so this can use a much longer TTL than query-result caching —
// repeated chunk text (re-upload, re-chunk on edit) skips the Ollama round-trip.
const embeddingStore = new Map();
const EMBEDDING_CACHE_TTL_MS = parseInt(process.env.EMBEDDING_CACHE_TTL_MS || '86400000', 10); // 24h

export function embeddingCacheKey(text) {
  return text.trim().toLowerCase();
}

export function getCachedEmbedding(text) {
  const entry = embeddingStore.get(embeddingCacheKey(text));
  if (!entry) return null;
  if (Date.now() > entry.expiresAt) {
    embeddingStore.delete(embeddingCacheKey(text));
    return null;
  }
  return entry.value;
}

export function setCachedEmbedding(text, vector) {
  embeddingStore.set(embeddingCacheKey(text), { value: vector, expiresAt: Date.now() + EMBEDDING_CACHE_TTL_MS });
}
