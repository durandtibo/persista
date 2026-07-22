r"""Provide an async TTL cache backed by any ``AsyncBaseStore``."""

from __future__ import annotations

__all__ = ["AsyncCache"]

import functools
import logging
import time
from typing import TYPE_CHECKING, Any, TypeVar

from persista.cache.cache import _UNSET
from persista.cache.utils import make_key
from persista.store.async_in_memory import AsyncInMemoryStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from persista.store.base import AsyncBaseStore

T = TypeVar("T")

logger: logging.Logger = logging.getLogger(__name__)


class AsyncCache:
    """Async cache with per-entry expiry, backed by any
    :class:`~persista.store.base.AsyncBaseStore`.

    This is the async counterpart of :class:`~persista.cache.cache.Cache`,
    for use with an async backing store (e.g. a Redis- or
    Postgres-backed store accessed via an async driver). It mirrors
    ``Cache``'s API, but every method that touches the backing store
    is a coroutine.

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
            entries whose ``ttl`` is not explicitly set on
            :meth:`set` / :meth:`get_or_compute` / :meth:`memoize`.
            ``None`` (the default) means entries never expire unless
            an explicit ``ttl`` is given. Must be non-negative.
        ignore_none: If ``True``, a cached value of ``None`` is
            treated as a cache miss rather than a hit, so it gets
            recomputed instead of being served back forever.

    Raises:
        ValueError: If ``default_ttl`` is negative.

    Example:
        ```pycon
        >>> import asyncio
        >>> from persista.cache import AsyncCache
        >>> async def main():
        ...     cache = AsyncCache(default_ttl=60)
        ...     await cache.set("greeting", "hello")
        ...     print(await cache.get("greeting"))
        ...
        >>> asyncio.run(main())
        hello

        ```
    """

    def __init__(
        self,
        store: AsyncBaseStore | None = None,
        default_ttl: float | None = None,
        ignore_none: bool = False,
    ) -> None:
        if default_ttl is not None and default_ttl < 0:
            msg = f"default_ttl must be non-negative, got {default_ttl}"
            raise ValueError(msg)
        self._store: AsyncBaseStore = store if store is not None else AsyncInMemoryStore()
        self.default_ttl = default_ttl
        self._ignore_none = ignore_none

    async def get(self, key: str) -> Any | None:
        """Retrieve a value by its key.

        If the entry has expired, it is evicted from the backing
        store as a side effect of this call, before ``None`` is
        returned.

        Args:
            key: The key to look up.

        Returns:
            The cached value, or ``None`` if the key is missing, its
            entry has expired, or (when ``ignore_none`` is ``True``)
            the cached value is itself ``None``. This means a cached
            value of ``None`` is indistinguishable from a cache miss.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache import AsyncCache
            >>> async def main():
            ...     cache = AsyncCache()
            ...     await cache.set("greeting", "hello")
            ...     print(await cache.get("greeting"))
            ...     print(await cache.get("missing"))
            ...
            >>> asyncio.run(main())
            hello
            None

            ```
        """
        _, value = await self._get(key)
        return value

    async def _get(self, key: str) -> tuple[bool, Any]:
        """Look up a key, returning both hit/miss and the value.

        Args:
            key: The key to look up.

        Returns:
            A ``(hit, value)`` tuple. ``hit`` is ``True`` only when
            ``key`` exists in the store, has not expired, and (when
            ``ignore_none`` is ``True``) its value is not ``None``.
        """
        entry = await self._store.get(key)
        if entry is None:
            return False, None
        expires_at = entry["expires_at"]
        if expires_at is not None and time.time() > expires_at:
            await self._store.delete(key)  # expired, evict
            return False, None
        value = entry["value"]
        if self._ignore_none and value is None:
            logger.debug("Ignoring cached None: %s", key)
            return False, None
        logger.debug("Cache hit: %s", key)
        return True, value

    async def set(self, key: str, value: Any, ttl: float | None = _UNSET) -> None:
        """Add a value to the cache.

        Calling this again with an existing key overwrites the
        previous value and resets its expiry.

        Args:
            key: The key to set.
            value: The value to cache. Must be JSON-serializable if
                the backing store serializes values (see the class
                docstring).
            ttl: The time-to-live, in seconds, before the entry
                expires. Defaults to ``self.default_ttl`` when not
                given. ``None`` means the entry never expires. ``0``
                means the value is not written to the store at all,
                evicting any existing entry for ``key`` instead. Must
                be non-negative.

        Raises:
            ValueError: If ``ttl`` is negative.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache import AsyncCache
            >>> async def main():
            ...     cache = AsyncCache()
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
        resolved_ttl = self.default_ttl if ttl is _UNSET else ttl
        if resolved_ttl is not None and resolved_ttl < 0:
            msg = f"ttl must be non-negative, got {resolved_ttl}"
            raise ValueError(msg)
        if resolved_ttl == 0:
            await self._store.delete(key)
            return
        expires_at = None if resolved_ttl is None else time.time() + resolved_ttl
        await self._store.set(key, {"value": value, "expires_at": expires_at})

    async def contains(self, key: str) -> bool:
        """Indicate whether a key is present and unexpired.

        Args:
            key: The key to check.

        Returns:
            ``True`` if ``key`` has an entry in the cache that has not
            expired, otherwise ``False``. If the entry has expired,
            it is evicted from the backing store as a side effect of
            this call, as in :meth:`get`.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache import AsyncCache
            >>> async def main():
            ...     cache = AsyncCache()
            ...     await cache.set("greeting", "hello")
            ...     print(await cache.contains("greeting"))
            ...     print(await cache.contains("missing"))
            ...
            >>> asyncio.run(main())
            True
            False

            ```
        """
        hit, _ = await self._get(key)
        return hit

    async def delete(self, key: str) -> None:
        """Remove a single entry from the cache, if present.

        Unlike :meth:`set` with ``ttl=0``, this does not require a
        value to be given.

        Args:
            key: The key to remove.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache import AsyncCache
            >>> async def main():
            ...     cache = AsyncCache()
            ...     await cache.set("greeting", "hello")
            ...     await cache.delete("greeting")
            ...     print(await cache.get("greeting"))
            ...
            >>> asyncio.run(main())
            None

            ```
        """
        await self._store.delete(key)

    async def get_or_compute(
        self,
        key: str,
        fn: Callable[..., Awaitable[T]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        ttl: float | None = _UNSET,
    ) -> T:
        """Return the cached value for ``key``, computing and storing it
        on a cache miss.

        ``args``/``kwargs`` are passed as a tuple/dict rather than
        ``*args``/``**kwargs`` so that ``fn``'s own arguments can never
        collide with this method's parameters (e.g. a ``fn`` that
        itself takes a ``key`` or ``ttl`` argument).

        Args:
            key: The key to look up and, on a miss, store the result
                under.
            fn: The async function to call to compute the value when
                ``key`` is not in the cache.
            args: Positional arguments passed to ``fn`` on a miss.
            kwargs: Keyword arguments passed to ``fn`` on a miss.
            ttl: The time-to-live, in seconds, applied when storing a
                freshly computed value. See :meth:`set`.

        Returns:
            The cached value on a hit, otherwise the value returned by
            ``await fn(*args, **kwargs)``.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache import AsyncCache
            >>> cache = AsyncCache()
            >>> calls = []
            >>> async def compute(x):
            ...     calls.append(x)
            ...     return x * 2
            ...
            >>> async def main():
            ...     print(await cache.get_or_compute("key", compute, (4,), {}))
            ...     print(await cache.get_or_compute("key", compute, (4,), {}))  # cached
            ...
            >>> asyncio.run(main())
            8
            8
            >>> calls
            [4]

            ```
        """
        hit, value = await self._get(key)
        if hit:
            return value
        value = await fn(*args, **kwargs)
        await self.set(key, value, ttl=ttl)
        return value

    def memoize(
        self,
        ttl: float | None = _UNSET,
        strategy: str = "json",
        ignore_non_serializable: bool = False,
    ) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
        """Decorate an async function so its return values are cached.

        The cache key is derived from the decorated function's
        qualified name (``__qualname__``) and call arguments, via
        :func:`~persista.cache.utils.make_key`, so calls with equal
        arguments share a cached result. Call arguments must be
        serializable with ``strategy``, unless
        ``ignore_non_serializable`` is set; the return value must
        additionally be JSON-serializable if the backing store
        serializes values (see the class docstring). Because the key
        is based on ``__qualname__`` rather than object identity, two
        distinct functions defined with the same qualified name (e.g.
        two calls to the same factory returning a closure) share
        their cache entries.

        Args:
            ttl: The time-to-live, in seconds, applied to cached
                results. See :meth:`set`.
            strategy: The serialization strategy used to compute the
                cache key. Either ``"json"`` or ``"pickle"``. See
                :func:`~persista.cache.utils.make_key`.
            ignore_non_serializable: If ``True``, positional arguments
                and keyword argument values that are not serializable
                with ``strategy`` are dropped before computing the
                key, instead of raising an error.

        Returns:
            A decorator that wraps an async function with caching.

        Raises:
            ValueError: If ``ttl`` is negative.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache import AsyncCache
            >>> cache = AsyncCache()
            >>> calls = []
            >>> @cache.memoize()
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
                key = make_key(
                    func.__qualname__,
                    args,
                    kwargs,
                    strategy=strategy,
                    ignore_non_serializable=ignore_non_serializable,
                )
                return await self.get_or_compute(key, func, args, kwargs, ttl=ttl)

            return wrapper

        return decorator

    async def clear(self) -> None:
        """Remove every entry from the cache, expired or not.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache import AsyncCache
            >>> async def main():
            ...     cache = AsyncCache()
            ...     await cache.set("greeting", "hello")
            ...     await cache.clear()
            ...     print(await cache.get("greeting"))
            ...
            >>> asyncio.run(main())
            None

            ```
        """
        await self._store.clear()
