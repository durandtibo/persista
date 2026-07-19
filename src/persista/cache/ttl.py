r"""Provide a TTL cache backed by any ``BaseStore``."""

from __future__ import annotations

__all__ = ["TTLCache"]

import functools
import time
from typing import TYPE_CHECKING, Any, TypeVar

from persista.cache.utils import make_key
from persista.store.in_memory import InMemoryStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from persista.store.base import BaseStore

T = TypeVar("T")


class TTLCache:
    """Cache with per-entry expiry, backed by any
    :class:`~persista.store.base.BaseStore`.

    Values are wrapped as ``{"value": value, "expires_at": expires_at}``
    before being written to the store, since :class:`BaseStore` only
    accepts ``dict`` values. If the backing store is one that
    serializes values (e.g. a SQLite- or Redis-backed store), cached
    values must be JSON-serializable.

    ``expires_at`` is a Unix timestamp (``time.time()``), not a
    monotonic clock reading, because entries may be read back by a
    different process or after a restart of this one.

    Args:
        store: The backing store. Defaults to a new
            :class:`~persista.store.in_memory.InMemoryStore`.
        default_ttl: The default time-to-live, in seconds, applied to
            entries whose ``ttl`` is not explicitly set. Must be
            positive.

    Raises:
        ValueError: If ``default_ttl`` is not positive.
    """

    def __init__(self, store: BaseStore | None = None, default_ttl: float = 300) -> None:
        if default_ttl <= 0:
            msg = f"default_ttl must be a positive number, got {default_ttl}"
            raise ValueError(msg)
        self._store: BaseStore = store if store is not None else InMemoryStore()
        self.default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        """Retrieve a value by its key.

        Args:
            key: The key to look up.

        Returns:
            The cached value, or ``None`` if the key is missing or
            its entry has expired.
        """
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() > entry["expires_at"]:
            self._store.delete(key)  # expired, evict
            return None
        return entry["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Add a value to the cache.

        Args:
            key: The key to set.
            value: The value to cache.
            ttl: The time-to-live, in seconds, before the entry
                expires. Defaults to ``self.default_ttl``. Must be
                positive.

        Raises:
            ValueError: If ``ttl`` is not positive.
        """
        ttl = ttl if ttl is not None else self.default_ttl
        if ttl <= 0:
            msg = f"ttl must be a positive number, got {ttl}"
            raise ValueError(msg)
        self._store.set(key, {"value": value, "expires_at": time.time() + ttl})

    def clear(self) -> None:
        """Remove every entry from the cache."""
        self._store.clear()

    def memoize(self, ttl: float | None = None) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorate a function so its return values are cached.

        The cache key is derived from the function's qualified name
        and call arguments, so calls with equal arguments share a
        cached result. Arguments must be JSON-serializable.

        Args:
            ttl: The time-to-live, in seconds, applied to cached
                results. Defaults to ``self.default_ttl``.

        Returns:
            A decorator that wraps a function with caching.
        """

        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> T:
                key = make_key(func.__qualname__, args, kwargs)
                cached = self.get(key)
                if cached is not None:
                    return cached
                result = func(*args, **kwargs)
                self.set(key, result, ttl=ttl)
                return result

            return wrapper

        return decorator
