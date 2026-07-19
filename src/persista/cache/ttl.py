r"""Provide a TTL cache backed by any ``BaseStore``."""

from __future__ import annotations

__all__ = ["TTLCache"]

import json
import time
from typing import TYPE_CHECKING, Any

from coola.hashing import hash_bytes

from persista.store.in_memory import InMemoryStore

if TYPE_CHECKING:
    from persista.store.base import BaseStore


class TTLCache:
    """Cache with per-entry expiry, backed by any
    :class:`~persista.store.base.BaseStore`.

    Values are wrapped as ``{"value": value, "expires_at": expires_at}``
    before being written to the store, since :class:`BaseStore` only
    accepts ``dict`` values. If the backing store is one that
    serializes values (e.g. a SQLite- or Redis-backed store), cached
    values must be JSON-serializable.
    """

    def __init__(self, store: BaseStore | None = None, default_ttl: int = 300) -> None:
        self._store: BaseStore = store if store is not None else InMemoryStore()
        self.default_ttl = default_ttl

    def _make_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        raw = json.dumps(
            {"func": func_name, "args": args, "kwargs": kwargs},
            sort_keys=True,
            default=str,
        )
        return hash_bytes(raw.encode())

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() > entry["expires_at"]:
            self._store.delete(key)  # expired, evict
            return None
        return entry["value"]

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl if ttl is not None else self.default_ttl
        self._store.set(key, {"value": value, "expires_at": time.time() + ttl})

    def clear(self) -> None:
        self._store.delete_many(list(self._store.keys()))
