"""
Caching, per spec: "Cache embeddings, repeated retrievals and/or final
responses where appropriate."

A minimal in-process TTL+LRU cache — no Redis dependency for the demo.
This is explicitly NOT shared across multiple backend replicas; the
`CacheBackend` interface exists so swapping in a Redis-backed
implementation later (for horizontal scaling) doesn't touch call sites.

Two named caches are exposed:
- `embedding_cache` — keyed by (provider, text), avoids re-embedding the
  same query text repeatedly (common in a demo/eval loop).
- `query_cache` — keyed by (pipeline, question, filters), skips the whole
  retrieve->rerank->generate pipeline for a repeated identical question.
  Deliberately NOT used for conversation-aware queries (session_id set) —
  those must always re-run because history changes the resolved query.
"""

import hashlib
import json
import time
from collections import OrderedDict
from typing import Any, Callable


class TTLCache:
    def __init__(self, max_size: int = 512, ttl_seconds: int = 3600):
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        self._store.move_to_end(key)  # LRU touch
        return value

    def set(self, key: str, value: Any) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (time.time() + self._ttl, value)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()


def make_key(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


embedding_cache = TTLCache(max_size=2048, ttl_seconds=6 * 3600)
query_cache = TTLCache(max_size=256, ttl_seconds=15 * 60)


def cached_embed_query(provider_name: str, text: str, compute: Callable[[], list[float]]) -> list[float]:
    key = make_key("embedding", provider_name, text)
    cached = embedding_cache.get(key)
    if cached is not None:
        return cached
    value = compute()
    embedding_cache.set(key, value)
    return value
