import time

from ..core.config import RETRIEVAL_CACHE_TTL_MS, EMBEDDING_CACHE_TTL_MS

_store: dict[str, dict] = {}
_embedding_store: dict[str, dict] = {}


def cache_key(query: str, chat_id: str) -> str:
    return f"{chat_id}::{query.strip().lower()}"


def get_cached(key: str):
    entry = _store.get(key)
    if not entry:
        return None
    if time.time() * 1000 > entry["expiresAt"]:
        _store.pop(key, None)
        return None
    return entry["value"]


def set_cached(key: str, value, ttl_ms: int = RETRIEVAL_CACHE_TTL_MS):
    _store[key] = {"value": value, "expiresAt": time.time() * 1000 + ttl_ms}


def _embedding_cache_key(text: str) -> str:
    return text.strip().lower()


def get_cached_embedding(text: str):
    key = _embedding_cache_key(text)
    entry = _embedding_store.get(key)
    if not entry:
        return None
    if time.time() * 1000 > entry["expiresAt"]:
        _embedding_store.pop(key, None)
        return None
    return entry["value"]


def set_cached_embedding(text: str, vector):
    key = _embedding_cache_key(text)
    _embedding_store[key] = {"value": vector, "expiresAt": time.time() * 1000 + EMBEDDING_CACHE_TTL_MS}
