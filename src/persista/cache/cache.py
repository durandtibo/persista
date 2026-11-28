r"""Provide a TTL cache backed by any ``BaseStore``."""

from __future__ import annotations

__all__ = ["MISSING", "Cache"]

import inspect
import logging
import math
import time
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

from coola.display import MultilineDisplayMixin

from persista.cache.memoize import memoize_with
from persista.cache.ttl import DEFAULT, validate_ttl
from persista.store.codec import PickleCodec
from persista.store.in_memory import InMemoryStore
from persista.store.validation import validate_keys

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Collection, Mapping
    from typing import Self

    from persista.store.base import BaseStore

P = ParamSpec("P")
R = TypeVar("R")
T = TypeVar("T")

logger: logging.Logger = logging.getLogger(__name__)

MISSING: Any = object()
"""Sentinel usable as the ``default`` argument to :meth:`Cache.get` /
:meth:`Cache.aget` to distinguish a cache miss from a cached
``None``."""


class Cache(MultilineDisplayMixin):
    """Cache with per-entry expiry, backed by any
    :class:`~persista.store.BaseStore`.

    Every method that accesses the store has a sync form (``get``,
    ``get_many``, ``contains``, ``set``, ``set_many``, ``delete``,
    ``delete_many``, ``clear``, ``get_or_compute``) and an async counterpart
    prefixed with ``a`` (``aget``, ``aget_many``, ...), so the same cache
    instance can be used from sync and async code, provided the backing
    store supports the interface being used. :meth:`memoize` decorates
    both kinds of functions.

    Each entry is wrapped as ``{"value": value, "expires_at":
    expires_at}`` before being written to the store, since
    :class:`~persista.store.BaseStore` only accepts ``dict``
    values. The codec of the backing store decides which values can be
    cached, and a hit returns what the codec reads back:

    - the default store uses :class:`~persista.store.PickleCodec`: any
      value that can be pickled is cached, with its type;
    - a store with the :class:`~persista.store.JsonCodec` (for example
      ``InMemoryStore()``) only accepts values that JSON can represent,
      and returns a tuple as a list;
    - the other stores serialize values as described in their
      documentation (for example, a SQLite-backed store needs
      JSON-serializable values by default).

    A time-to-live (``ttl``, or ``default_ttl`` when it is not given) is
    ``None`` (the entry never expires), ``0`` (the entry is deleted instead
    of written) or a positive number of seconds. A negative or ``NaN``
    value raises ``ValueError``.

    ``expires_at`` is a Unix timestamp (``time.time()``), not a
    monotonic clock reading, because entries may be read back by a
    different process or after a restart of this one. Expiry is checked
    when an entry is read: an expired entry is a miss, and it **stays in
    the store until its key is read again** (or deleted, overwritten, or
    the cache cleared). There is no background eviction and no size
    limit, so a cache that writes many keys that are never read again
    grows until :meth:`clear`. The read that deletes an expired entry can
    remove a value that another writer stores between the read and the
    deletion.

    Concurrent misses on the same key can compute the value several
    times.

    The cache owns its store: :meth:`clear` clears the whole store, so do
    not give a cache a store that holds other data.

    Like :class:`~persista.store.BaseStore`, constructing a
    :class:`Cache` does not connect to the underlying backing store:
    this is deferred to :meth:`open`/:meth:`aopen`, so every method that
    accesses the store raises until the cache has been opened, either
    explicitly or via use as a sync context manager (``with Cache(...) as
    cache: ...``, calling :meth:`open` on entry and :meth:`close` on
    exit) or an async context manager (``async with Cache(...) as
    cache: ...``, calling :meth:`aopen` on entry and :meth:`aclose`
    on exit).

    Args:
        store: The backing store. Defaults to a new
            :class:`~persista.store.in_memory.InMemoryStore` with the
            :class:`~persista.store.PickleCodec`.
        default_ttl: The time-to-live, in seconds, of the entries written
            without an explicit ``ttl``. ``None`` (the default) means that
            they never expire.

    Raises:
        ValueError: If ``default_ttl`` is negative or ``NaN``.

    Example:
        ```pycon
        >>> from persista.cache import Cache
        >>> with Cache(default_ttl=60) as cache:
        ...     cache.set("greeting", "hello")
        ...     cache.get("greeting")
        ...
        'hello'

        ```
    """

    def __init__(
        self,
        store: BaseStore | None = None,
        *,
        default_ttl: float | None = None,
    ) -> None:
        validate_ttl(default_ttl, name="default_ttl")
        self._store: BaseStore = store if store is not None else InMemoryStore(codec=PickleCodec())
        self._default_ttl = default_ttl

    @property
    def default_ttl(self) -> float | None:
        """The time-to-live, in seconds, of the entries written without
        an explicit ``ttl``."""
        return self._default_ttl

    @property
    def closed(self) -> bool:
        r"""Indicate whether the cache's backing store is closed.

        Returns:
            ``True`` if the backing store has been closed (or never
            opened), ``False`` if it is open and ready to use.
        """
        return self._store.closed

    def open(self) -> None:
        r"""Connect the backing store and prepare the cache for use.

        Repeated calls are safe (idempotent), since the underlying
        :meth:`BaseStore.open` is idempotent.
        """
        self._store.open()

    async def aopen(self) -> None:
        """Async equivalent of :meth:`open`."""
        await self._store.aopen()

    def close(self) -> None:
        r"""Close the cache's backing store and release any underlying
        resources.

        Repeated calls are safe (idempotent), since the underlying
        :meth:`BaseStore.close` is idempotent.

        Raises:
            RuntimeError: If the store cannot be closed from sync code,
                such as a :class:`~persista.store.RedisStore` whose async
                client is open: use :meth:`aclose`.
        """
        self._store.close()

    async def aclose(self) -> None:
        """Async equivalent of :meth:`close`."""
        await self._store.aclose()

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    async def __aenter__(self) -> Self:
        await self.aopen()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by its key.

        If the entry has expired, it is deleted from the backing store
        before ``default`` is returned.

        Args:
            key: The key to look up.
            default: The value to return if the key is missing or its
                entry has expired. Pass the
                :data:`~persista.cache.cache.MISSING` sentinel here
                to distinguish a cache miss from a cached ``None``.

        Returns:
            The cached value, or ``default`` on a miss.

        Raises:
            RuntimeError: If the cache is closed.
            TypeError: If ``key`` is not a ``str``.

        Example:
            ```pycon
            >>> from persista.cache import MISSING, Cache
            >>> with Cache() as cache:
            ...     cache.set("greeting", "hello")
            ...     cache.get("greeting")
            ...     cache.get("missing") is None
            ...     cache.set("empty", None)
            ...     cache.get("empty", MISSING) is MISSING
            ...     cache.get("missing", MISSING) is MISSING
            ...
            'hello'
            True
            False
            True

            ```
        """
        entry = self._store.get(key)
        if entry is None:
            return default
        if self._is_expired(entry, time.time()):
            self._store.delete(key)
            return default
        logger.debug("Cache hit: %s", key)
        return entry["value"]

    async def aget(self, key: str, default: Any = None) -> Any:
        """Async equivalent of :meth:`get`."""
        entry = await self._store.aget(key)
        if entry is None:
            return default
        if self._is_expired(entry, time.time()):
            await self._store.adelete(key)
            return default
        logger.debug("Cache hit: %s", key)
        return entry["value"]

    def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Retrieve the values of several keys with one read of the
        store.

        Args:
            keys: The keys to look up.

        Returns:
            The cached value of each key that is a hit, keyed by the key.
            A missing or expired key is not in the result, so a cached
            ``None`` is distinguished from a miss with ``in``. The expired
            entries are deleted from the backing store.

        Raises:
            RuntimeError: If the cache is closed.
            TypeError: If a key is not a ``str``.

        Example:
            ```pycon
            >>> from persista.cache import Cache
            >>> with Cache() as cache:
            ...     cache.set_many({"a": "hello", "b": None})
            ...     cache.get_many(["a", "b", "missing"])
            ...
            {'a': 'hello', 'b': None}

            ```
        """
        keys = validate_keys(keys)
        hits, expired = self._split_entries(keys, self._store.get_many(keys))
        if expired:
            self._store.delete_many(expired)
        return hits

    async def aget_many(self, keys: list[str]) -> dict[str, Any]:
        """Async equivalent of :meth:`get_many`."""
        keys = validate_keys(keys)
        hits, expired = self._split_entries(keys, await self._store.aget_many(keys))
        if expired:
            await self._store.adelete_many(expired)
        return hits

    def contains(self, key: str) -> bool:
        """Indicate whether a key is present and unexpired.

        Args:
            key: The key to check.

        Returns:
            ``True`` if ``key`` has an entry that has not expired,
            otherwise ``False``. An expired entry is deleted from the
            backing store.

        Raises:
            RuntimeError: If the cache is closed.
            TypeError: If ``key`` is not a ``str``.

        Example:
            ```pycon
            >>> from persista.cache import Cache
            >>> with Cache() as cache:
            ...     cache.set("greeting", "hello")
            ...     cache.contains("greeting")
            ...     cache.contains("missing")
            ...
            True
            False

            ```
        """
        return self.get(key, MISSING) is not MISSING

    async def acontains(self, key: str) -> bool:
        """Async equivalent of :meth:`contains`."""
        return await self.aget(key, MISSING) is not MISSING

    def set(self, key: str, value: Any, *, ttl: float | None = DEFAULT) -> None:
        """Add a value to the cache.

        Calling this again with an existing key overwrites the
        previous value and resets its expiry.

        Args:
            key: The key to set.
            value: The value to cache. The codec of the backing
                store must accept it (see the class docstring).
            ttl: The time-to-live, in seconds, before the entry
                expires. Defaults to ``default_ttl`` when not given.
                ``None`` means that the entry never expires. ``0`` means
                that the value is not written, and that an existing entry
                of ``key`` is deleted.

        Raises:
            RuntimeError: If the cache is closed.
            TypeError: If ``key`` is not a ``str``, or if the codec of the
                store cannot encode ``value``.
            ValueError: If ``ttl`` is negative or ``NaN``, or if ``value``
                cannot be encoded without losing data.

        Example:
            ```pycon
            >>> from persista.cache import Cache
            >>> with Cache() as cache:
            ...     cache.set("greeting", "hello")
            ...     cache.get("greeting")
            ...     cache.set("greeting", "bonjour", ttl=30)
            ...     cache.get("greeting")
            ...     cache.set("greeting", "salut", ttl=0)
            ...     cache.contains("greeting")
            ...
            'hello'
            'bonjour'
            False

            ```
        """
        self.set_many({key: value}, ttl=ttl)

    async def aset(self, key: str, value: Any, *, ttl: float | None = DEFAULT) -> None:
        """Async equivalent of :meth:`set`."""
        await self.aset_many({key: value}, ttl=ttl)

    def set_many(self, items: Mapping[str, Any], *, ttl: float | None = DEFAULT) -> None:
        """Add several values to the cache with one write to the store.

        Args:
            items: The values to cache, keyed by their keys. The codec of
                the backing store must accept them (see the class
                docstring).
            ttl: The time-to-live, in seconds, of every entry. See
                :meth:`set`.

        Raises:
            RuntimeError: If the cache is closed.
            TypeError: If a key is not a ``str``, or if the codec of the
                store cannot encode a value.
            ValueError: If ``ttl`` is negative or ``NaN``, or if a value
                cannot be encoded without losing data.

        Example:
            ```pycon
            >>> from persista.cache import Cache
            >>> with Cache() as cache:
            ...     cache.set_many({"a": "hello", "b": "world"}, ttl=60)
            ...     cache.get_many(["a", "b"])
            ...
            {'a': 'hello', 'b': 'world'}

            ```
        """
        ttl = self._resolve_ttl(ttl)
        if ttl == 0:
            self._store.delete_many(list(items))
            return
        self._store.set_many(self._make_entries(items, ttl))

    async def aset_many(self, items: Mapping[str, Any], *, ttl: float | None = DEFAULT) -> None:
        """Async equivalent of :meth:`set_many`."""
        ttl = self._resolve_ttl(ttl)
        if ttl == 0:
            await self._store.adelete_many(list(items))
            return
        await self._store.aset_many(self._make_entries(items, ttl))

    def delete(self, key: str) -> None:
        """Remove a single entry from the cache, if present.

        Args:
            key: The key to remove.

        Raises:
            RuntimeError: If the cache is closed.
            TypeError: If ``key`` is not a ``str``.

        Example:
            ```pycon
            >>> from persista.cache import Cache
            >>> with Cache() as cache:
            ...     cache.set("greeting", "hello")
            ...     cache.delete("greeting")
            ...     cache.contains("greeting")
            ...
            False

            ```
        """
        self._store.delete(key)

    async def adelete(self, key: str) -> None:
        """Async equivalent of :meth:`delete`."""
        await self._store.adelete(key)

    def delete_many(self, keys: list[str]) -> None:
        """Remove several entries from the cache with one write to the
        store, if present.

        Args:
            keys: The keys to remove.

        Raises:
            RuntimeError: If the cache is closed.
            TypeError: If a key is not a ``str``.

        Example:
            ```pycon
            >>> from persista.cache import Cache
            >>> with Cache() as cache:
            ...     cache.set_many({"a": "hello", "b": "world"})
            ...     cache.delete_many(["a", "b"])
            ...     cache.get_many(["a", "b"])
            ...
            {}

            ```
        """
        self._store.delete_many(keys)

    async def adelete_many(self, keys: list[str]) -> None:
        """Async equivalent of :meth:`delete_many`."""
        await self._store.adelete_many(keys)

    def clear(self) -> None:
        """Remove every entry from the cache, expired or not.

        This clears the whole backing store.

        Raises:
            RuntimeError: If the cache is closed.

        Example:
            ```pycon
            >>> from persista.cache import Cache
            >>> with Cache() as cache:
            ...     cache.set("greeting", "hello")
            ...     cache.clear()
            ...     cache.get("greeting") is None
            ...
            True

            ```
        """
        self._store.clear()

    async def aclear(self) -> None:
        """Async equivalent of :meth:`clear`."""
        await self._store.aclear()

    def get_or_compute(self, key: str, fn: Callable[[], T], *, ttl: float | None = DEFAULT) -> T:
        """Return the cached value for ``key``, computing and storing it
        on a cache miss.

        Concurrent misses on the same key can call ``fn`` several times.

        Args:
            key: The key to look up and, on a miss, store the result
                under.
            fn: The function without arguments that computes the value
                on a miss, such as a ``lambda`` or a
                ``functools.partial``.
            ttl: The time-to-live, in seconds, of a freshly computed
                value. See :meth:`set`. It does not change an entry that
                is a hit.

        Returns:
            The cached value on a hit, as the codec of the store reads it
            back, otherwise the value returned by ``fn()``.

        Raises:
            RuntimeError: If the cache is closed.
            TypeError: If ``key`` is not a ``str``, or if the codec of the
                store cannot encode the computed value.
            ValueError: If ``ttl`` is negative or ``NaN`` (``fn`` is not
                called), or if the computed value cannot be encoded
                without losing data.

        Example:
            ```pycon
            >>> from persista.cache import Cache
            >>> calls = []
            >>> def compute():
            ...     calls.append(1)
            ...     return 8
            ...
            >>> with Cache() as cache:
            ...     cache.get_or_compute("key", compute)
            ...     cache.get_or_compute("key", compute)  # served from the cache
            ...
            8
            8
            >>> calls
            [1]

            ```
        """
        # Checked here too, so that an invalid ttl raises on a hit, and
        # before fn is called.
        self._resolve_ttl(ttl)
        value = self.get(key, MISSING)
        if value is MISSING:
            value = fn()
            self.set(key, value, ttl=ttl)
        return value

    async def aget_or_compute(
        self,
        key: str,
        fn: Callable[[], T] | Callable[[], Awaitable[T]],
        *,
        ttl: float | None = DEFAULT,
    ) -> T:
        """Async equivalent of :meth:`get_or_compute`.

        ``fn`` may be a regular function or an ``async def`` function: what
        it returns is awaited if it is awaitable. A regular function is
        called in the event loop, which it blocks. The store is accessed
        with its async methods.

        Example:
            ```pycon
            >>> import asyncio
            >>> from persista.cache import Cache
            >>> async def compute():
            ...     return 8
            ...
            >>> async def main():
            ...     async with Cache() as cache:
            ...         print(await cache.aget_or_compute("key", compute))
            ...
            >>> asyncio.run(main())
            8

            ```
        """
        self._resolve_ttl(ttl)
        value = await self.aget(key, MISSING)
        if value is MISSING:
            # Whether the result is awaitable is only known at runtime.
            result: Any = fn()
            value = await result if inspect.isawaitable(result) else result
            await self.aset(key, value, ttl=ttl)
        return value

    def memoize(
        self,
        *,
        ttl: float | None = DEFAULT,
        ignore: Collection[str] = (),
        key: Callable[..., str] | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorate a function so its return values are cached.

        Works on both sync and ``async def`` functions: the decorated
        function is of the same kind. The store of an ``async def``
        function is accessed with its async methods.

        The key of a call is the hash of the canonical encoding (see
        :func:`~persista.utils.canonical.encode_canonical`) of the module
        of the function, its qualified name (``__module__`` and
        ``__qualname__``), and its arguments bound to its parameters, with
        the default values:

        - ``f(1)`` and ``f(a=1)`` are the same call, and so is
          ``f(1, b=2)`` if ``2`` is the default of ``b``. The order of keyword
          arguments, also those collected by ``**kwargs``, and the order
          of the items of a ``dict`` do not matter;
        - arguments of different types are different calls: ``1``, ``1.0``,
          ``True`` and ``"1"``, or a list and a tuple, do not share a result;
        - the arguments, including the default values, must be built from
          ``None``, ``bool``, ``int``, ``float``, ``str``, ``bytes``, ``list``,
          ``tuple``, ``dict``, ``set`` and ``frozenset``. Any other argument,
          including an instance of a subclass of these types, raises
          ``TypeError``, unless its parameter is named in ``ignore`` or
          ``key`` is given.

        A method needs ``ignore`` or ``key``, because its first argument
        (``self`` or ``cls``) cannot be encoded. With ``ignore=("self",)``, all
        the instances share the results, so use it only if the result does
        not depend on the instance.

        Functions are told apart by their names only: two functions with
        the same module and qualified name, such as two closures returned
        by the same function, two lambdas defined in the same scope, or a
        function and a wrapper of it made with ``functools.wraps``,
        share their results. Give them a ``key`` if they differ.

        A hit returns the result as the codec of the store reads it back
        (see the class docstring). Concurrent misses on the same call can
        run the function several times.

        Args:
            ttl: The time-to-live, in seconds, of the cached results. See
                :meth:`set`.
            ignore: The names of the parameters whose arguments are left
                out of the key, such as a client or a logger: calls that
                only differ in these arguments share a result.
            key: A function that is called with the arguments of each call
                and returns its key. The key is used as is, so it must
                differ between functions that share the cache. It cannot be
                used together with ``ignore``.

        Returns:
            A decorator that wraps a function with caching.

        Raises:
            TypeError: If ``ignore`` is a ``str``. The decorator raises it for
                a callable without a ``__qualname__`` or a built-in method
                bound to an object, unless ``key`` is given. A call raises
                it if its arguments do not match the signature, or cannot
                be encoded.
            ValueError: If ``ttl`` is negative or ``NaN``, or if ``ignore`` and
                ``key`` are both given. The decorator raises it if ``ignore``
                names a parameter that the function does not have. A call
                raises it if an argument contains itself.
            RuntimeError: A call raises it if the cache is closed.

        Example:
            ```pycon
            >>> from persista.cache import Cache
            >>> calls = []
            >>> with Cache() as cache:
            ...     @cache.memoize(ignore=("verbose",))
            ...     def square(x, verbose=False):
            ...         calls.append(x)
            ...         return x * x
            ...     square(4)
            ...     square(x=4, verbose=True)  # served from the cache
            ...
            16
            16
            >>> calls
            [4]

            ```
        """
        return memoize_with(lambda: self, ttl=ttl, ignore=ignore, key=key)

    def _resolve_ttl(self, ttl: float | None) -> float | None:
        """Resolve a ``ttl`` argument against ``self._default_ttl``.

        Args:
            ttl: The ``ttl`` of a call, or
                :data:`~persista.cache.ttl.DEFAULT` to use
                ``self._default_ttl``.

        Returns:
            The resolved ttl.

        Raises:
            ValueError: If ``ttl`` is negative or ``NaN``.
        """
        if ttl is DEFAULT:
            # Checked by the constructor.
            return self._default_ttl
        validate_ttl(ttl)
        return ttl

    @staticmethod
    def _make_entries(items: Mapping[str, Any], ttl: float | None) -> dict[str, dict[str, Any]]:
        """Wrap values in the entries that are written to the store.

        Args:
            items: The values, keyed by their keys. It is not modified.
            ttl: The resolved time-to-live of the entries: ``None`` or a
                positive number.

        Returns:
            The entry of each key. An infinite ``ttl`` gives entries that
            never expire.
        """
        expires_at = None
        # JSON cannot represent infinity.
        if ttl is not None and ttl != math.inf:
            expires_at = time.time() + ttl
        return {key: {"value": value, "expires_at": expires_at} for key, value in items.items()}

    @staticmethod
    def _is_expired(entry: dict[str, Any], now: float) -> bool:
        """Indicate whether an entry of the store has expired.

        Args:
            entry: The entry.
            now: The current Unix timestamp.

        Returns:
            ``True`` if the expiry of the entry is before ``now``.
        """
        expires_at = entry["expires_at"]
        return expires_at is not None and now > expires_at

    def _split_entries(
        self, keys: list[str], entries: list[dict[str, Any] | None]
    ) -> tuple[dict[str, Any], list[str]]:
        """Split a batch of entries of the store into hits and expired
        keys.

        Args:
            keys: The keys that were looked up.
            entries: The entries of ``keys``, in the same order, with
                ``None`` for the missing keys.

        Returns:
            A ``(hits, expired_keys)`` tuple. ``hits`` maps each key that is
            a hit to its cached value. ``expired_keys`` lists the keys whose
            entry has expired and should be deleted.
        """
        now = time.time()
        hits: dict[str, Any] = {}
        expired_keys: list[str] = []
        for key, entry in zip(keys, entries, strict=True):
            if entry is None:
                continue
            if self._is_expired(entry, now):
                expired_keys.append(key)
            else:
                hits[key] = entry["value"]
        return hits, expired_keys

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {
            "store": self._store,
            "default_ttl": self._default_ttl,
        }
