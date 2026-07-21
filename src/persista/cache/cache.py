r"""Provide a TTL cache backed by any ``BaseStore``."""

from __future__ import annotations

__all__ = ["Cache"]

import functools
import logging
import time
from typing import TYPE_CHECKING, Any, TypeVar

from persista.cache.utils import make_key
from persista.store.in_memory import InMemoryStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from persista.store.base import BaseStore

T = TypeVar("T")

logger: logging.Logger = logging.getLogger(__name__)

_UNSET: Any = object()


class Cache:
    """Cache with per-entry expiry, backed by any
    :class:`~persista.store.base.BaseStore`.

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
        self.default_ttl = default_ttl
        self._ignore_none = ignore_none

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
                expires. Defaults to ``self.default_ttl`` when not
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
        resolved_ttl = self.default_ttl if ttl is _UNSET else ttl
        if resolved_ttl is not None and resolved_ttl < 0:
            msg = f"ttl must be non-negative, got {resolved_ttl}"
            raise ValueError(msg)
        if resolved_ttl == 0:
            self._store.delete(key)
            return
        expires_at = None if resolved_ttl is None else time.time() + resolved_ttl
        self._store.set(key, {"value": value, "expires_at": expires_at})

    def get_or_compute(
        self,
        key: str,
        fn: Callable[..., T],
        *args: Any,
        ttl: float | None = _UNSET,
        **kwargs: Any,
    ) -> T:
        """Return the cached value for ``key``, computing and storing it
        on a cache miss.

        Args:
            key: The key to look up and, on a miss, store the result
                under.
            fn: The function to call to compute the value when
                ``key`` is not in the cache.
            *args: Positional arguments passed to ``fn`` on a miss.
            ttl: The time-to-live, in seconds, applied when storing a
                freshly computed value. See :meth:`set`.
            **kwargs: Keyword arguments passed to ``fn`` on a miss.

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
            >>> cache.get_or_compute("key", compute, 4)
            8
            >>> cache.get_or_compute("key", compute, 4)  # served from the cache
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

    def memoize(
        self,
        ttl: float | None = _UNSET,
        strategy: str = "json",
        ignore_non_serializable: bool = False,
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorate a function so its return values are cached.

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
            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> T:
                key = make_key(
                    func.__qualname__,
                    args,
                    kwargs,
                    strategy=strategy,
                    ignore_non_serializable=ignore_non_serializable,
                )
                return self.get_or_compute(key, func, *args, ttl=ttl, **kwargs)

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
