r"""Provide an async TTL cache backed by any ``AsyncBaseStore``."""

from __future__ import annotations

__all__ = ["AsyncTTLCache"]

import functools
import time
from typing import TYPE_CHECKING, Any, TypeVar

from persista.cache.utils import make_key
from persista.store.async_in_memory import AsyncInMemoryStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from persista.store.base import AsyncBaseStore

T = TypeVar("T")


class AsyncTTLCache:
    """Async cache with per-entry expiry, backed by any
    :class:`~persista.store.base.AsyncBaseStore`.

    Each entry is wrapped as ``{"value": value, "expires_at":
    expires_at}`` before being written to the store, since
    :class:`~persista.store.base.AsyncBaseStore` only accepts ``dict``
    values. If the backing store is one that serializes values (e.g.
    a SQLite- or Redis-backed store), cached values must be
    JSON-serializable.

    ``expires_at`` is a Unix timestamp (``time.time()``), not a
    monotonic clock reading, because entries may be read back by a
    different process or after a restart of this one. Expiry is
    checked lazily on :meth:`get`: an expired entry is only evicted
    the next time it is looked up, not proactively at its expiry
    time.

    Args:
        store: The backing store. Defaults to a new
            :class:`~persista.store.async_in_memory.AsyncInMemoryStore`.
        default_ttl: The default time-to-live, in seconds, applied to
            entries whose ``ttl`` is not explicitly set. Must be
            positive.

    Raises:
        ValueError: If ``default_ttl`` is not positive.

    Example:
        ```pycon
        >>> import asyncio
        >>> from persista.cache import AsyncTTLCache
        >>> async def main():
        ...     cache = AsyncTTLCache(default_ttl=60)
        ...     await cache.set("greeting", "hello")
        ...     print(await cache.get("greeting"))
        ...
        >>> asyncio.run(main())
        hello

        ```
    """

    def __init__(self, store: AsyncBaseStore | None = None, default_ttl: float = 300) -> None:
        if default_ttl <= 0:
            msg = f"default_ttl must be a positive number, got {default_ttl}"
            raise ValueError(msg)
        self._store: AsyncBaseStore = store if store is not None else AsyncInMemoryStore()
        self.default_ttl = default_ttl

    async def get(self, key: str) -> Any | None:
        """Retrieve a value by its key.

        If the entry has expired, it is evicted from the backing
        store as a side effect of this call, before ``None`` is
        returned.

        Args:
            key: The key to look up.

        Returns:
            The cached value, or ``None`` if the key is missing or
            its entry has expired. This means a cached value of
            ``None`` is indistinguishable from a cache miss.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache import AsyncTTLCache
            >>> async def main():
            ...     cache = AsyncTTLCache()
            ...     await cache.set("greeting", "hello")
            ...     print(await cache.get("greeting"))
            ...     print(await cache.get("missing"))
            ...
            >>> asyncio.run(main())
            hello
            None

            ```
        """
        entry = await self._store.get(key)
        if entry is None:
            return None
        if time.time() > entry["expires_at"]:
            await self._store.delete(key)  # expired, evict
            return None
        return entry["value"]

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Add a value to the cache.

        Calling this again with an existing key overwrites the
        previous value and resets its expiry.

        Args:
            key: The key to set.
            value: The value to cache. Must be JSON-serializable if
                the backing store serializes values (see the class
                docstring).
            ttl: The time-to-live, in seconds, before the entry
                expires. Defaults to ``self.default_ttl``. Must be
                positive.

        Raises:
            ValueError: If ``ttl`` is not positive.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache import AsyncTTLCache
            >>> async def main():
            ...     cache = AsyncTTLCache()
            ...     await cache.set("greeting", "hello")
            ...     print(await cache.get("greeting"))
            ...     await cache.set("greeting", "bonjour")
            ...     print(await cache.get("greeting"))
            ...
            >>> asyncio.run(main())
            hello
            bonjour

            ```
        """
        ttl = ttl if ttl is not None else self.default_ttl
        if ttl <= 0:
            msg = f"ttl must be a positive number, got {ttl}"
            raise ValueError(msg)
        await self._store.set(key, {"value": value, "expires_at": time.time() + ttl})

    async def clear(self) -> None:
        """Remove every entry from the cache, expired or not.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache import AsyncTTLCache
            >>> async def main():
            ...     cache = AsyncTTLCache()
            ...     await cache.set("greeting", "hello")
            ...     await cache.clear()
            ...     print(await cache.get("greeting"))
            ...
            >>> asyncio.run(main())
            None

            ```
        """
        await self._store.clear()

    def memoize(
        self, ttl: float | None = None
    ) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
        """Decorate an async function so its return values are cached.

        The cache key is derived from the decorated function's
        qualified name (``__qualname__``) and call arguments, via
        :func:`~persista.cache.utils.make_key`, so calls with equal
        arguments share a cached result. Call arguments must always
        be JSON-serializable, regardless of the backing store; the
        return value must additionally be JSON-serializable if the
        backing store serializes values (see the class docstring).
        Because the key is based on ``__qualname__`` rather than
        object identity, two distinct functions defined with the same
        qualified name (e.g. two calls to the same factory returning
        a closure) share their cache entries.

        Args:
            ttl: The time-to-live, in seconds, applied to cached
                results. Defaults to ``self.default_ttl``. Must be
                positive.

        Returns:
            A decorator that wraps an async function with caching.

        Raises:
            ValueError: If ``ttl`` is not positive.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache import AsyncTTLCache
            >>> cache = AsyncTTLCache()
            >>> calls = []
            >>> @cache.memoize(ttl=60)
            ... async def square(x):
            ...     calls.append(x)
            ...     return x * x
            ...
            >>> async def main():
            ...     print(await square(4))
            ...     print(await square(4))  # served from the cache, not re-computed
            ...
            >>> asyncio.run(main())
            16
            16
            >>> calls
            [4]

            ```
        """

        def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                key = make_key(func.__qualname__, args, kwargs)
                cached = await self.get(key)
                if cached is not None:
                    return cached
                result = await func(*args, **kwargs)
                await self.set(key, result, ttl=ttl)
                return result

            return wrapper

        return decorator
