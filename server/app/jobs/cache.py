import threading
import time
from collections import OrderedDict
from typing import Any

from ..core.config import RETRIEVAL_CACHE_TTL_MS, EMBEDDING_CACHE_TTL_MS


class BoundedTTLCache:
    """Thread-safe bounded in-memory LRU cache with time-to-live (TTL) expiry.
    Prevents unbounded memory consumption on constrained hardware."""

    def __init__(self, max_size: int = 1000, default_ttl_ms: int = 60000):
        self.max_size = max_size
        self.default_ttl_ms = default_ttl_ms
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.time() * 1000 > expires_at:
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl_ms: int | None = None) -> None:
        ttl = self.default_ttl_ms if ttl_ms is None else ttl_ms
        expires_at = time.time() * 1000 + ttl
        with self._lock:
            if key in self._cache:
                self._cache.pop(key)
            elif len(self._cache) >= self.max_size:
                # Evict oldest item (LRU)
                self._cache.popitem(last=False)
            self._cache[key] = (expires_at, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


_retrieval_cache = BoundedTTLCache(max_size=500, default_ttl_ms=RETRIEVAL_CACHE_TTL_MS)
_embedding_cache = BoundedTTLCache(max_size=2500, default_ttl_ms=EMBEDDING_CACHE_TTL_MS)
_http_fetch_cache = BoundedTTLCache(max_size=300, default_ttl_ms=300000)  # 5 min TTL


def cache_key(query: str, chat_id: str) -> str:
    return f"{chat_id}::{query.strip().lower()}"


def get_cached(key: str):
    return _retrieval_cache.get(key)


def set_cached(key: str, value, ttl_ms: int = RETRIEVAL_CACHE_TTL_MS):
    _retrieval_cache.set(key, value, ttl_ms=ttl_ms)


def _embedding_cache_key(text: str) -> str:
    return text.strip().lower()


def get_cached_embedding(text: str):
    key = _embedding_cache_key(text)
    return _embedding_cache.get(key)


def set_cached_embedding(text: str, vector, ttl_ms: int = EMBEDDING_CACHE_TTL_MS):
    key = _embedding_cache_key(text)
    _embedding_cache.set(key, vector, ttl_ms=ttl_ms)


def get_cached_fetch(url: str):
    return _http_fetch_cache.get(url.strip())


def set_cached_fetch(url: str, payload: dict, ttl_ms: int = 300000):
    _http_fetch_cache.set(url.strip(), payload, ttl_ms=ttl_ms)
