r"""Provide a TTL cache backed by any ``BaseStore``."""

from __future__ import annotations

__all__ = ["Cache"]

import functools
import inspect
import logging
import time
from typing import TYPE_CHECKING, Any, TypeVar

from persista.cache.utils import make_key
from persista.store.in_memory import InMemoryStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from persista.store.base import BaseStore

T = TypeVar("T")

logger: logging.Logger = logging.getLogger(__name__)

_UNSET: Any = object()


class Cache:
    """Cache with per-entry expiry, backed by any
    :class:`~persista.store.base.BaseStore`.

    Most methods have both a sync form (``get``, ``set``, ``contains``,
    ``get_many``, ``set_many``, ``contains_many``, ``delete``,
    ``delete_many``, ``get_or_compute``, ``memoize``, ``clear``) and
    an async counterpart prefixed with ``a`` (``aget``, ``aset``,
    ``acontains``, ``aget_many``, ``aset_many``, ``acontains_many``,
    ``adelete``, ``adelete_many``, ``aget_or_compute``, ``amemoize``,
    ``aclear``), so the same cache instance can be used from sync and
    async code, provided the backing store supports the interface
    being used.

    Each entry is wrapped as ``{"value": value, "expires_at":
    expires_at}`` before being written to the store, since
    :class:`~persista.store.base.BaseStore` only accepts ``dict``
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
            :class:`~persista.store.in_memory.InMemoryStore`.
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
        >>> from persista.cache import Cache
        >>> cache = Cache(default_ttl=60)
        >>> cache.set("greeting", "hello")
        >>> cache.get("greeting")
        'hello'

        ```
    """

    def __init__(
        self,
        store: BaseStore | None = None,
        default_ttl: float | None = None,
        ignore_none: bool = False,
    ) -> None:
        if default_ttl is not None and default_ttl < 0:
            msg = f"default_ttl must be non-negative, got {default_ttl}"
            raise ValueError(msg)
        self._store: BaseStore = store if store is not None else InMemoryStore()
        self._default_ttl = default_ttl
        self._ignore_none = ignore_none

    @property
    def default_ttl(self) -> float | None:
        """The default time-to-live, in seconds, applied to entries
        whose ``ttl`` is not explicitly set on :meth:`set` /
        :meth:`get_or_compute` / :meth:`memoize`."""
        return self._default_ttl

    def get(self, key: str) -> Any | None:
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
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> cache.set("greeting", "hello")
            >>> cache.get("greeting")
            'hello'
            >>> cache.get("missing") is None
            True

            ```
        """
        _, value = self._get(key)
        return value

    def _get(self, key: str) -> tuple[bool, Any]:
        """Look up a key, returning both hit/miss and the value.

        Args:
            key: The key to look up.

        Returns:
            A ``(hit, value)`` tuple. ``hit`` is ``True`` only when
            ``key`` exists in the store, has not expired, and (when
            ``ignore_none`` is ``True``) its value is not ``None``.
        """
        entry = self._store.get(key)
        if entry is None:
            return False, None
        expires_at = entry["expires_at"]
        if expires_at is not None and time.time() > expires_at:
            self._store.delete(key)  # expired, evict
            return False, None
        value = entry["value"]
        if self._ignore_none and value is None:
            logger.debug("Ignoring cached None: %s", key)
            return False, None
        logger.debug("Cache hit: %s", key)
        return True, value

    def _resolve_ttl(self, ttl: float | None) -> float | None:
        """Resolve a ``ttl`` argument against ``self._default_ttl``.

        Args:
            ttl: The ``ttl`` passed to :meth:`set` / :meth:`aset`, or
                ``_UNSET`` to fall back to ``self._default_ttl``.

        Returns:
            The resolved ttl.

        Raises:
            ValueError: If the resolved ttl is negative.
        """
        resolved_ttl = self._default_ttl if ttl is _UNSET else ttl
        if resolved_ttl is not None and resolved_ttl < 0:
            msg = f"ttl must be non-negative, got {resolved_ttl}"
            raise ValueError(msg)
        return resolved_ttl

    def set(self, key: str, value: Any, ttl: float | None = _UNSET) -> None:
        """Add a value to the cache.

        Calling this again with an existing key overwrites the
        previous value and resets its expiry.

        Args:
            key: The key to set.
            value: The value to cache. Must be JSON-serializable if
                the backing store serializes values (see the class
                docstring).
            ttl: The time-to-live, in seconds, before the entry
                expires. Defaults to ``self._default_ttl`` when not
                given. ``None`` means the entry never expires. ``0``
                means the value is not written to the store at all,
                evicting any existing entry for ``key`` instead. Must
                be non-negative.

        Raises:
            ValueError: If ``ttl`` is negative.

        Example:
            ```pycon
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> cache.set("greeting", "hello")
            >>> cache.get("greeting")
            'hello'
            >>> cache.set("greeting", "bonjour")
            >>> cache.get("greeting")
            'bonjour'
            >>> cache.set("short-lived", "value", ttl=30)

            ```
        """
        resolved_ttl = self._resolve_ttl(ttl)
        if resolved_ttl == 0:
            self._store.delete(key)
            return
        expires_at = None if resolved_ttl is None else time.time() + resolved_ttl
        self._store.set(key, {"value": value, "expires_at": expires_at})

    async def aget(self, key: str) -> Any | None:
        """Retrieve a value by its key.

        This is the async counterpart of :meth:`get`, for use with an
        async backing store.

        Args:
            key: The key to look up.

        Returns:
            The cached value, or ``None`` if the key is missing, its
            entry has expired, or (when ``ignore_none`` is ``True``)
            the cached value is itself ``None``.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> async def main():
            ...     await cache.aset("greeting", "hello")
            ...     print(await cache.aget("greeting"))
            ...
            >>> asyncio.run(main())
            hello

            ```
        """
        _, value = await self._aget(key)
        return value

    async def _aget(self, key: str) -> tuple[bool, Any]:
        """Look up a key, returning both hit/miss and the value.

        This is the async counterpart of :meth:`_get`.

        Args:
            key: The key to look up.

        Returns:
            A ``(hit, value)`` tuple. ``hit`` is ``True`` only when
            ``key`` exists in the store, has not expired, and (when
            ``ignore_none`` is ``True``) its value is not ``None``.
        """
        entry = await self._store.aget(key)
        if entry is None:
            return False, None
        expires_at = entry["expires_at"]
        if expires_at is not None and time.time() > expires_at:
            await self._store.adelete(key)  # expired, evict
            return False, None
        value = entry["value"]
        if self._ignore_none and value is None:
            logger.debug("Ignoring cached None: %s", key)
            return False, None
        logger.debug("Cache hit: %s", key)
        return True, value

    async def aset(self, key: str, value: Any, ttl: float | None = _UNSET) -> None:
        """Add a value to the cache.

        This is the async counterpart of :meth:`set`, for use with an
        async backing store.

        Args:
            key: The key to set.
            value: The value to cache. Must be JSON-serializable if
                the backing store serializes values (see the class
                docstring).
            ttl: The time-to-live, in seconds, before the entry
                expires. Defaults to ``self._default_ttl`` when not
                given. ``None`` means the entry never expires. ``0``
                means the value is not written to the store at all,
                evicting any existing entry for ``key`` instead. Must
                be non-negative.

        Raises:
            ValueError: If ``ttl`` is negative.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> async def main():
            ...     await cache.aset("greeting", "hello")
            ...     print(await cache.aget("greeting"))
            ...
            >>> asyncio.run(main())
            hello

            ```
        """
        resolved_ttl = self._resolve_ttl(ttl)
        if resolved_ttl == 0:
            await self._store.adelete(key)
            return
        expires_at = None if resolved_ttl is None else time.time() + resolved_ttl
        await self._store.aset(key, {"value": value, "expires_at": expires_at})

    def contains(self, key: str) -> bool:
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
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> cache.set("greeting", "hello")
            >>> cache.contains("greeting")
            True
            >>> cache.contains("missing")
            False

            ```
        """
        hit, _ = self._get(key)
        return hit

    async def acontains(self, key: str) -> bool:
        """Indicate whether a key is present and unexpired.

        This is the async counterpart of :meth:`contains`, for use
        with an async backing store.

        Args:
            key: The key to check.

        Returns:
            ``True`` if ``key`` has an entry in the cache that has not
            expired, otherwise ``False``. If the entry has expired,
            it is evicted from the backing store as a side effect of
            this call, as in :meth:`aget`.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> async def main():
            ...     await cache.aset("greeting", "hello")
            ...     print(await cache.acontains("greeting"))
            ...     print(await cache.acontains("missing"))
            ...
            >>> asyncio.run(main())
            True
            False

            ```
        """
        hit, _ = await self._aget(key)
        return hit

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Retrieve multiple values in a single batched store lookup.

        Unlike calling :meth:`get` (or :meth:`contains` followed by
        :meth:`get`) once per key, this issues one
        ``self._store.get_many`` call for the whole batch, which
        matters for stores where each lookup is a network round trip
        (e.g. Redis, Postgres).

        Args:
            keys: The keys to look up.

        Returns:
            A dict mapping each key that is a hit -- present,
            unexpired, and (when ``ignore_none`` is ``True``) not a
            cached ``None`` -- to its cached value. Keys that are
            missing, expired, or an ignored ``None`` are omitted
            entirely rather than mapped to ``None``, so a hit can
            always be distinguished from a miss with ``in``. Expired
            entries are evicted from the backing store as a side
            effect of this call, as in :meth:`get`.

        Example:
            ```pycon
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> cache.set("a", "hello")
            >>> cache.set("b", "world")
            >>> sorted(cache.get_many(["a", "b", "missing"]).items())
            [('a', 'hello'), ('b', 'world')]

            ```
        """
        if not keys:
            return {}
        entries = self._store.get_many(keys)
        results, expired_keys = self._split_many(keys, entries)
        if expired_keys:
            self._store.delete_many(expired_keys)
        return results

    async def aget_many(self, keys: list[str]) -> dict[str, Any]:
        """Retrieve multiple values in a single batched store lookup.

        This is the async counterpart of :meth:`get_many`, for use
        with an async backing store.

        Args:
            keys: The keys to look up.

        Returns:
            A dict mapping each key that is a hit to its cached value.
            See :meth:`get_many` for the exact hit/miss semantics.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> async def main():
            ...     await cache.aset("a", "hello")
            ...     await cache.aset("b", "world")
            ...     print(sorted((await cache.aget_many(["a", "b", "missing"])).items()))
            ...
            >>> asyncio.run(main())
            [('a', 'hello'), ('b', 'world')]

            ```
        """
        if not keys:
            return {}
        entries = await self._store.aget_many(keys)
        results, expired_keys = self._split_many(keys, entries)
        if expired_keys:
            await self._store.adelete_many(expired_keys)
        return results

    def _split_many(
        self, keys: list[str], entries: list[dict[str, Any] | None]
    ) -> tuple[dict[str, Any], list[str]]:
        """Split a batch of raw store entries into hits and expired
        keys.

        Args:
            keys: The keys that were looked up.
            entries: The raw store entries for ``keys``, in the same
                order, with ``None`` for keys that were missing.

        Returns:
            A ``(hits, expired_keys)`` tuple. ``hits`` maps each key
            that is a hit to its cached value. ``expired_keys`` lists
            the keys whose entry has expired and should be evicted.
        """
        now = time.time()
        hits: dict[str, Any] = {}
        expired_keys: list[str] = []
        for key, entry in zip(keys, entries, strict=True):
            if entry is None:
                continue
            expires_at = entry["expires_at"]
            if expires_at is not None and now > expires_at:
                expired_keys.append(key)
                continue
            value = entry["value"]
            if self._ignore_none and value is None:
                logger.debug("Ignoring cached None: %s", key)
                continue
            hits[key] = value
        return hits, expired_keys

    def set_many(self, items: dict[str, Any], ttl: float | None = _UNSET) -> None:
        """Add multiple values in a single batched store write.

        Unlike calling :meth:`set` once per item, this issues one
        ``self._store.set_many`` call for the whole batch, which
        matters for stores where each write is a network round trip
        (e.g. Redis, Postgres). A single ``ttl`` applies to every
        item in the batch.

        Args:
            items: A dict mapping each key to the value to cache
                under it. Values must be JSON-serializable if the
                backing store serializes values (see the class
                docstring).
            ttl: The time-to-live, in seconds, before the entries
                expire. See :meth:`set`.

        Raises:
            ValueError: If ``ttl`` is negative.

        Example:
            ```pycon
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> cache.set_many({"a": "hello", "b": "world"})
            >>> sorted(cache.get_many(["a", "b"]).items())
            [('a', 'hello'), ('b', 'world')]

            ```
        """
        if not items:
            return
        resolved_ttl = self._resolve_ttl(ttl)
        if resolved_ttl == 0:
            self._store.delete_many(list(items.keys()))
            return
        expires_at = None if resolved_ttl is None else time.time() + resolved_ttl
        self._store.set_many(
            {key: {"value": value, "expires_at": expires_at} for key, value in items.items()}
        )

    async def aset_many(self, items: dict[str, Any], ttl: float | None = _UNSET) -> None:
        """Add multiple values in a single batched store write.

        This is the async counterpart of :meth:`set_many`, for use
        with an async backing store.

        Args:
            items: A dict mapping each key to the value to cache
                under it. Values must be JSON-serializable if the
                backing store serializes values (see the class
                docstring).
            ttl: The time-to-live, in seconds, before the entries
                expire. See :meth:`aset`.

        Raises:
            ValueError: If ``ttl`` is negative.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> async def main():
            ...     await cache.aset_many({"a": "hello", "b": "world"})
            ...     print(sorted((await cache.aget_many(["a", "b"])).items()))
            ...
            >>> asyncio.run(main())
            [('a', 'hello'), ('b', 'world')]

            ```
        """
        if not items:
            return
        resolved_ttl = self._resolve_ttl(ttl)
        if resolved_ttl == 0:
            await self._store.adelete_many(list(items.keys()))
            return
        expires_at = None if resolved_ttl is None else time.time() + resolved_ttl
        await self._store.aset_many(
            {key: {"value": value, "expires_at": expires_at} for key, value in items.items()}
        )

    def contains_many(self, keys: list[str]) -> list[bool]:
        """Check presence of multiple keys in a single batched store
        lookup.

        Unlike calling :meth:`contains` once per key, this issues one
        ``self._store.get_many`` call for the whole batch, which
        matters for stores where each lookup is a network round trip
        (e.g. Redis, Postgres).

        Args:
            keys: The keys to check.

        Returns:
            A list of booleans, in the same order as ``keys``, where
            each entry is ``True`` if the corresponding key is a hit
            -- present, unexpired, and (when ``ignore_none`` is
            ``True``) not a cached ``None`` -- and ``False``
            otherwise. Expired entries are evicted from the backing
            store as a side effect of this call, as in
            :meth:`get_many`.

        Example:
            ```pycon
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> cache.set("a", "hello")
            >>> cache.contains_many(["a", "b"])
            [True, False]

            ```
        """
        hits = self.get_many(keys)
        return [key in hits for key in keys]

    async def acontains_many(self, keys: list[str]) -> list[bool]:
        """Check presence of multiple keys in a single batched store
        lookup.

        This is the async counterpart of :meth:`contains_many`, for
        use with an async backing store.

        Args:
            keys: The keys to check.

        Returns:
            A list of booleans, in the same order as ``keys``, where
            each entry is ``True`` if the corresponding key is a hit
            -- present, unexpired, and (when ``ignore_none`` is
            ``True``) not a cached ``None`` -- and ``False``
            otherwise. Expired entries are evicted from the backing
            store as a side effect of this call, as in
            :meth:`aget_many`.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> async def main():
            ...     await cache.aset("a", "hello")
            ...     print(await cache.acontains_many(["a", "b"]))
            ...
            >>> asyncio.run(main())
            [True, False]

            ```
        """
        hits = await self.aget_many(keys)
        return [key in hits for key in keys]

    def delete(self, key: str) -> None:
        """Remove a single entry from the cache, if present.

        Unlike :meth:`set` with ``ttl=0``, this does not require a
        value to be given.

        Args:
            key: The key to remove.

        Example:
            ```pycon
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> cache.set("greeting", "hello")
            >>> cache.delete("greeting")
            >>> cache.get("greeting") is None
            True

            ```
        """
        self._store.delete(key)

    def delete_many(self, keys: list[str]) -> None:
        """Remove multiple entries from the cache in a single batched
        store write, if present.

        Args:
            keys: The keys to remove.

        Example:
            ```pycon
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> cache.set_many({"a": "hello", "b": "world"})
            >>> cache.delete_many(["a", "b"])
            >>> cache.get_many(["a", "b"])
            {}

            ```
        """
        self._store.delete_many(keys)

    async def adelete_many(self, keys: list[str]) -> None:
        """Remove multiple entries from the cache in a single batched
        store write, if present.

        This is the async counterpart of :meth:`delete_many`, for use
        with an async backing store.

        Args:
            keys: The keys to remove.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> async def main():
            ...     await cache.aset_many({"a": "hello", "b": "world"})
            ...     await cache.adelete_many(["a", "b"])
            ...     print(await cache.aget_many(["a", "b"]))
            ...
            >>> asyncio.run(main())
            {}

            ```
        """
        await self._store.adelete_many(keys)

    async def adelete(self, key: str) -> None:
        """Remove a single entry from the cache, if present.

        This is the async counterpart of :meth:`delete`, for use with
        an async backing store.

        Args:
            key: The key to remove.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> async def main():
            ...     await cache.aset("greeting", "hello")
            ...     await cache.adelete("greeting")
            ...     print(await cache.aget("greeting"))
            ...
            >>> asyncio.run(main())
            None

            ```
        """
        await self._store.adelete(key)

    def get_or_compute(
        self,
        key: str,
        fn: Callable[..., T],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        ttl: float | None = _UNSET,
    ) -> T:
        """Return the cached value for ``key``, computing and storing it
        on a cache miss.

        Args:
            key: The key to look up and, on a miss, store the result
                under.
            fn: The function to call to compute the value when
                ``key`` is not in the cache.
            args: Positional arguments passed to ``fn`` on a miss.
            kwargs: Keyword arguments passed to ``fn`` on a miss.
            ttl: The time-to-live, in seconds, applied when storing a
                freshly computed value. See :meth:`set`.

        Returns:
            The cached value on a hit, otherwise the value returned by
            ``fn(*args, **kwargs)``.

        Example:
            ```pycon
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> calls = []
            >>> def compute(x):
            ...     calls.append(x)
            ...     return x * 2
            ...
            >>> cache.get_or_compute("key", compute, (4,), {})
            8
            >>> cache.get_or_compute("key", compute, (4,), {})  # served from the cache
            8
            >>> calls
            [4]

            ```
        """
        hit, value = self._get(key)
        if hit:
            return value
        value = fn(*args, **kwargs)
        self.set(key, value, ttl=ttl)
        return value

    async def aget_or_compute(
        self,
        key: str,
        fn: Callable[..., T] | Callable[..., Awaitable[T]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        ttl: float | None = _UNSET,
    ) -> T:
        """Return the cached value for ``key``, computing and storing it
        on a cache miss.

        This is the async counterpart of :meth:`get_or_compute`, for
        use with an async backing store. ``fn`` may be a regular sync
        function or an ``async def`` function; either way, the backing
        store is always accessed through ``await``.

        Args:
            key: The key to look up and, on a miss, store the result
                under.
            fn: The sync or async function to call to compute the
                value when ``key`` is not in the cache.
            args: Positional arguments passed to ``fn`` on a miss.
            kwargs: Keyword arguments passed to ``fn`` on a miss.
            ttl: The time-to-live, in seconds, applied when storing a
                freshly computed value. See :meth:`aset`.

        Returns:
            The cached value on a hit, otherwise the value returned by
            ``fn(*args, **kwargs)`` (awaited if ``fn`` is async).

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> calls = []
            >>> async def compute(x):
            ...     calls.append(x)
            ...     return x * 2
            ...
            >>> async def main():
            ...     print(await cache.aget_or_compute("key", compute, (4,), {}))
            ...     print(await cache.aget_or_compute("key", compute, (4,), {}))  # cached
            ...
            >>> asyncio.run(main())
            8
            8
            >>> calls
            [4]

            ```
        """
        hit, value = await self._aget(key)
        if hit:
            return value
        result = fn(*args, **kwargs)
        value = await result if inspect.isawaitable(result) else result
        await self.aset(key, value, ttl=ttl)
        return value

    def memoize(
        self,
        ttl: float | None = _UNSET,
        strategy: str = "json",
        ignore_non_serializable: bool = False,
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorate a function so its return values are cached.

        Works on both sync and async functions (``async def``).

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
            A decorator that wraps a function with caching.

        Raises:
            ValueError: If ``ttl`` is negative.

        Example:
            ```pycon
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> calls = []
            >>> @cache.memoize()
            ... def square(x):
            ...     calls.append(x)
            ...     return x * x
            ...
            >>> square(4)
            16
            >>> square(4)  # served from the cache, not re-computed
            16
            >>> calls
            [4]

            ```
        """

        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            if inspect.iscoroutinefunction(func):

                @functools.wraps(func)
                async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                    key = make_key(
                        func.__qualname__,
                        args,
                        kwargs,
                        strategy=strategy,
                        ignore_non_serializable=ignore_non_serializable,
                    )
                    return await self.aget_or_compute(
                        key=key, fn=func, args=args, kwargs=kwargs, ttl=ttl
                    )

                return async_wrapper

            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> T:
                key = make_key(
                    func.__qualname__,
                    args,
                    kwargs,
                    strategy=strategy,
                    ignore_non_serializable=ignore_non_serializable,
                )
                return self.get_or_compute(key=key, fn=func, args=args, kwargs=kwargs, ttl=ttl)

            return wrapper

        return decorator

    def amemoize(
        self,
        ttl: float | None = _UNSET,
        strategy: str = "json",
        ignore_non_serializable: bool = False,
    ) -> Callable[[Callable[..., T] | Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
        """Decorate a function so its return values are cached.

        This is the async counterpart of :meth:`memoize`, for use
        with an async backing store. Works on both sync and async
        functions (``async def``); the wrapped function is always a
        coroutine function, since the backing store is only
        accessible through ``await``.

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
                results. See :meth:`aset`.
            strategy: The serialization strategy used to compute the
                cache key. Either ``"json"`` or ``"pickle"``. See
                :func:`~persista.cache.utils.make_key`.
            ignore_non_serializable: If ``True``, positional arguments
                and keyword argument values that are not serializable
                with ``strategy`` are dropped before computing the
                key, instead of raising an error.

        Returns:
            A decorator that wraps a sync or async function with
            caching, always returning a coroutine function.

        Raises:
            ValueError: If ``ttl`` is negative.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> calls = []
            >>> @cache.amemoize()
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

        def decorator(
            func: Callable[..., T] | Callable[..., Awaitable[T]],
        ) -> Callable[..., Awaitable[T]]:
            @functools.wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                key = make_key(
                    func.__qualname__,
                    args,
                    kwargs,
                    strategy=strategy,
                    ignore_non_serializable=ignore_non_serializable,
                )
                return await self.aget_or_compute(key, func, args, kwargs, ttl=ttl)

            return wrapper

        return decorator

    def clear(self) -> None:
        """Remove every entry from the cache, expired or not.

        Example:
            ```pycon
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> cache.set("greeting", "hello")
            >>> cache.clear()
            >>> cache.get("greeting") is None
            True

            ```
        """
        self._store.clear()

    async def aclear(self) -> None:
        """Remove every entry from the cache, expired or not.

        This is the async counterpart of :meth:`clear`, for use with
        an async backing store.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache.cache import Cache
            >>> cache = Cache()
            >>> async def main():
            ...     await cache.aset("greeting", "hello")
            ...     await cache.aclear()
            ...     print(await cache.aget("greeting"))
            ...
            >>> asyncio.run(main())
            None

            ```
        """
        await self._store.aclear()
