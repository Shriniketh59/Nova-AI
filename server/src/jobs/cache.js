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
