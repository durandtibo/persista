r"""Provide the base class for key-value stores, supporting both sync
and async access from the same instance."""

from __future__ import annotations

__all__ = ["BaseStore"]

import asyncio
import contextlib
import contextvars
import logging
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from coola.utils.batching import batchify

from persista.store.codec import JsonCodec
from persista.store.plan import build_plan
from persista.store.validation import (
    check_is_open,
    normalize_on_conflict,
    validate_batch_size,
    validate_key,
    validate_keys,
)

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Callable,
        Iterable,
        Iterator,
        Mapping,
        Set as AbstractSet,
    )
    from typing import Self

    from persista.store.codec import Codec
    from persista.store.types import OnConflict, Payload, Plan

T = TypeVar("T")

logger: logging.Logger = logging.getLogger(__name__)

# Number of values that keys() and filter() read from the backend at a time.
_SCAN_BATCH_SIZE = 256


class BaseStore(ABC):
    """Base class for key-value stores.

    Defines the common interface of all key-value stores. Values are
    stored as dicts, which allows :meth:`filter` to match on the content
    of a value.

    Every operation that touches the underlying store has a sync
    method (e.g. :meth:`get`) and an async twin prefixed with ``a``
    (e.g. :meth:`aget`), both callable on the same instance -- there
    is no separate async class.

    The public methods are written once, in this class. For each of
    them, this class:

    - checks that the store is open (``RuntimeError`` otherwise, also
      with an empty input);
    - validates the keys (a key is a ``str``, ``TypeError`` otherwise),
      ``on_conflict`` and ``batch_size``;
    - turns each value into a payload with the codec of the store, and
      each payload back into a value;
    - returns early on an empty input;
    - resolves the write conflicts.

    A value is a ``dict`` that the codec can encode. The store keeps the
    payloads only, so mutating a value that was passed to the store or
    returned by it never changes the stored value, and a read returns
    ``codec.decode(codec.encode(value))``. With the default
    :class:`~persista.store.JsonCodec`, a tuple is therefore read back as
    a list, and a value that would lose data raises.

    .. note::
        ``SQLiteStore``, ``DuckDBStore``, ``LmdbStore``, ``RedisStore``,
        ``PostgresStore``, the file stores and their pickle variants do
        not use the primitives below yet: they implement the public
        methods themselves (see
        :class:`~persista.store.unmigrated.UnmigratedStore`), and they
        do not take a codec.

    To implement a custom store, subclass :class:`BaseStore`, call
    ``super().__init__``, and implement :meth:`to_uri`,
    :meth:`from_uri` and the primitives:

    - ``_open()`` and ``_close()``: connect to the backend and release it.
      ``_close`` is also called if ``_open`` raises, so it must accept a
      store that is only partly open.
    - ``_get_many(keys)``: return the payloads of the keys that exist.
    - ``_put_many(items)``: add or replace payloads.
    - ``_update(keys, plan)``: atomically read the existing keys, call
      ``plan``, and write its result.
    - ``_delete_many(keys)``: delete keys, ignoring the missing ones.
    - ``_clear()``: delete every key.
    - ``_count()``: return the number of keys.
    - ``_iter_batches(batch_size)``: yield the payloads in batches.

    Two primitives have a default that a backend can replace by a faster
    one: ``_contains_many(keys)`` and ``_filter_candidates(fields)``.
    The primitives are called with the store open, with validated keys,
    and with encoded payloads. A list of keys or a mapping of items is
    never empty, and a list of keys can contain duplicates.

    Each data primitive has an async twin (``_aget_many``, ...), which by
    default runs the sync one in a thread. A backend with a native async
    driver replaces the async twins, and releases the resources that only
    they use in ``_aclose()``.

    A backend is assumed not to be thread-safe: the primitives run with
    one lock per instance, and the async calls run in a worker thread of
    the store, so calls that wait for the store do not fill the default
    executor of the event loop. An iteration takes the lock for one batch
    at a time, not while the caller handles a batch. A thread-safe
    backend sets the class attribute ``_thread_safe`` to ``True``: its
    primitives run without the lock, and in the default executor.

    Implementations support use as a sync context manager
    (``with SomeStore(...) as store: ...``, calling
    :meth:`open` on entry and :meth:`close` on exit) and as an async
    context manager (``async with SomeStore(...) as store: ...``,
    calling :meth:`aopen` on entry and :meth:`aclose` on exit).

    Constructing a store does not connect to the underlying backend:
    this is deferred to :meth:`open`/:meth:`aopen`, so every operation
    on the data raises until the store has been opened, either
    explicitly or via the context manager.

    No implementation supports a per-key time-to-live (TTL): a value
    written with :meth:`set`/:meth:`set_many` persists until it is
    explicitly deleted or the store is cleared, even on a backend that
    natively supports expiry (e.g. Redis's ``EX``/``PX``). This is
    intentional -- persista is meant for durable storage, not caching
    -- so build TTL/expiry on top of a store (e.g. an ``expires_at``
    value field checked by the caller) rather than assuming the store
    enforces it.

    Args:
        codec: The codec that turns the values into payloads.
            Defaults to a :class:`~persista.store.JsonCodec`.

    Example:
        ```pycon
        >>> from persista.store import InMemoryStore
        >>> with InMemoryStore() as store:  # calls open()/close() automatically
        ...     store.set("user:1", {"name": "Ann"})
        ...     store.get("user:1")
        ...
        {'name': 'Ann'}

        ```
    """

    #: Whether the primitives can be called by several threads at once.
    _thread_safe: ClassVar[bool] = False

    def __init__(self, *, codec: Codec | None = None) -> None:
        self._codec: Codec = codec if codec is not None else JsonCodec()
        self._closed = True
        # Always guards open() and close(), and also the primitives of a
        # backend that is not thread-safe.
        self._lock = threading.RLock()
        self._guard: contextlib.AbstractContextManager[Any] = (
            contextlib.nullcontext() if self._thread_safe else self._lock
        )
        # The worker thread of the async calls, created when first needed.
        self._executor: ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()

    ##########################
    #     Public methods     #
    ##########################

    def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a single value by its key.

        Args:
            key: The key to look up.

        Returns:
            The value associated with ``key``, or ``None`` if the
            key is not found.

        Raises:
            RuntimeError: If the store is closed.
            TypeError: If ``key`` is not a ``str``.
        """
        # Same steps as _call, without its second check of the state:
        # this is the shortest path to a value.
        with self._guard:
            check_is_open(self)
            key = validate_key(key)
            payload = self._get_many([key]).get(key)
        return None if payload is None else self._codec.decode(payload)

    async def aget(self, key: str) -> dict[str, Any] | None:
        """Async equivalent of :meth:`get`."""
        check_is_open(self)
        key = validate_key(key)
        payload = (await self._aget_many([key])).get(key)
        return None if payload is None else self._codec.decode(payload)

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        """Retrieve multiple values by their keys.

        Args:
            keys: The keys to look up.

        Returns:
            A list the same length as ``keys``, with the
            corresponding value for each key that exists, or
            ``None`` for keys that are not found.

        Raises:
            RuntimeError: If the store is closed.
            TypeError: If a key is not a ``str``.
        """
        check_is_open(self)
        keys = validate_keys(keys)
        if not keys:
            return []
        return self._decode_many(keys, self._call(self._get_many, keys))

    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        """Async equivalent of :meth:`get_many`."""
        check_is_open(self)
        keys = validate_keys(keys)
        if not keys:
            return []
        return self._decode_many(keys, await self._aget_many(keys))

    def set(
        self, key: str, value: dict[str, Any], *, on_conflict: OnConflict = "overwrite"
    ) -> None:
        """Add a single key-value pair to the store.

        Args:
            key: The key to set.
            value: The value to associate with ``key``.
            on_conflict: The strategy to use if ``key`` already
                exists in the store:

                - ``"raise"``: raise a :class:`KeyError` and leave
                  the existing value unchanged.
                - ``"skip"``: leave the existing value unchanged.
                - ``"overwrite"``: replace the existing value with
                  ``value``.
                - ``"merge"``: shallow-merge ``value`` into the
                  existing value, with fields from ``value`` taking
                  precedence on overlapping keys.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and ``key``
                already exists.
            RuntimeError: If the store is closed.
            TypeError: If ``key`` is not a ``str``, or if the codec of
                the store cannot encode ``value``.
            ValueError: If ``on_conflict`` is not a valid strategy, or if
                ``value`` cannot be encoded without losing data.
        """
        self.set_many({key: value}, on_conflict=on_conflict)

    async def aset(
        self, key: str, value: dict[str, Any], *, on_conflict: OnConflict = "overwrite"
    ) -> None:
        """Async equivalent of :meth:`set`."""
        await self.aset_many({key: value}, on_conflict=on_conflict)

    def set_many(
        self,
        items: Mapping[str, dict[str, Any]],
        *,
        on_conflict: OnConflict = "overwrite",
    ) -> None:
        """Add multiple key-value pairs to the store.

        Every key and value is checked and encoded before the first one
        is written.

        Args:
            items: The values to add, keyed by their unique key.
            on_conflict: The strategy to use for keys in ``items``
                that already exist in the store. See :meth:`set` for
                the meaning of each option.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and any key
                in ``items`` already exists. Nothing is written.
            RuntimeError: If the store is closed.
            TypeError: If a key is not a ``str``, or if the codec of the
                store cannot encode a value.
            ValueError: If ``on_conflict`` is not a valid strategy, or if
                a value cannot be encoded without losing data.
        """
        check_is_open(self)
        strategy = normalize_on_conflict(on_conflict)
        if not items:
            return
        payloads = self._encode_items(items)
        if strategy == "overwrite":
            self._call(self._put_many, payloads)
        else:
            plan = build_plan(payloads, strategy, self._codec)
            self._call(self._update, list(payloads), plan)

    async def aset_many(
        self,
        items: Mapping[str, dict[str, Any]],
        *,
        on_conflict: OnConflict = "overwrite",
    ) -> None:
        """Async equivalent of :meth:`set_many`."""
        check_is_open(self)
        strategy = normalize_on_conflict(on_conflict)
        if not items:
            return
        payloads = self._encode_items(items)
        if strategy == "overwrite":
            await self._aput_many(payloads)
        else:
            plan = build_plan(payloads, strategy, self._codec)
            await self._aupdate(list(payloads), plan)

    def set_batches(
        self,
        items: Iterable[tuple[str, dict[str, Any]]],
        batch_size: int = 32,
        *,
        on_conflict: OnConflict = "overwrite",
    ) -> None:
        """Add key-value pairs from an iterable, writing them to the
        store in mini-batches.

        This is the streaming equivalent of :meth:`set_many`: instead
        of requiring every key-value pair to be materialized into a
        single mapping upfront, it consumes ``items`` lazily and
        writes at most ``batch_size`` pairs at a time. This keeps
        memory usage bounded when ``items`` comes from a generator
        over a large or unbounded source.

        Args:
            items: An iterable of ``(key, value)`` pairs to add.
            batch_size: The maximum number of pairs to write to the
                store per underlying :meth:`set_many` call. Must be a
                positive integer.
            on_conflict: The strategy to use for keys that already
                exist in the store. See :meth:`set` for the meaning
                of each option. Applied independently per batch, so
                with ``"raise"`` a conflict is only detected once the
                offending batch is written, not upfront.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and any key
                already exists.
            RuntimeError: If the store is closed.
            ValueError: If ``batch_size`` or ``on_conflict`` is
                invalid.
        """
        check_is_open(self)
        validate_batch_size(batch_size)
        strategy = normalize_on_conflict(on_conflict)
        for batch in batchify(items, size=batch_size):
            self.set_many(dict(batch), on_conflict=strategy)

    async def aset_batches(
        self,
        items: Iterable[tuple[str, dict[str, Any]]],
        batch_size: int = 32,
        *,
        on_conflict: OnConflict = "overwrite",
    ) -> None:
        """Async equivalent of :meth:`set_batches`."""
        check_is_open(self)
        validate_batch_size(batch_size)
        strategy = normalize_on_conflict(on_conflict)
        for batch in batchify(items, size=batch_size):
            await self.aset_many(dict(batch), on_conflict=strategy)

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        """Retrieve values whose content matches all provided field
        filters.

        All filters are combined with ``AND``. Each keyword argument
        matches the corresponding key in the stored value.

        Args:
            **field_filters: Key-value pairs where each key is a
                field name within a stored value and the value is
                the value to match. Calling with no arguments
                returns every value in the store.

        Returns:
            A list of matching values.

        Raises:
            RuntimeError: If the store is closed.
        """
        check_is_open(self)
        matches: list[dict[str, Any]] = []
        for batch in self._batches(self._filter_candidates, field_filters):
            matches.extend(self._matching_values(batch, field_filters))
        return matches

    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
        """Async equivalent of :meth:`filter`."""
        check_is_open(self)
        matches: list[dict[str, Any]] = []
        async with contextlib.aclosing(self._afilter_candidates(field_filters)) as batches:
            async for batch in batches:
                matches.extend(self._matching_values(batch, field_filters))
        return matches

    def delete(self, key: str) -> None:
        """Delete a value by its key.

        Keys that do not exist are silently ignored.

        Args:
            key: The key of the value to delete.

        Raises:
            RuntimeError: If the store is closed.
            TypeError: If ``key`` is not a ``str``.
        """
        check_is_open(self)
        self._call(self._delete_many, [validate_key(key)])

    async def adelete(self, key: str) -> None:
        """Async equivalent of :meth:`delete`."""
        check_is_open(self)
        await self._adelete_many([validate_key(key)])

    def delete_many(self, keys: list[str]) -> None:
        """Delete multiple values by their keys.

        Keys that do not exist are silently ignored.

        Args:
            keys: The keys of the values to delete.

        Raises:
            RuntimeError: If the store is closed.
            TypeError: If a key is not a ``str``. Nothing is deleted.
        """
        check_is_open(self)
        keys = validate_keys(keys)
        if keys:
            self._call(self._delete_many, keys)

    async def adelete_many(self, keys: list[str]) -> None:
        """Async equivalent of :meth:`delete_many`."""
        check_is_open(self)
        keys = validate_keys(keys)
        if keys:
            await self._adelete_many(keys)

    def clear(self) -> None:
        """Remove every key-value pair from the store.

        This is equivalent to resetting the store to empty, without
        closing it.

        Raises:
            RuntimeError: If the store is closed.
        """
        check_is_open(self)
        self._call(self._clear)

    async def aclear(self) -> None:
        """Async equivalent of :meth:`clear`."""
        check_is_open(self)
        await self._aclear()

    def contains(self, key: str) -> bool:
        """Check if the key exists in the store.

        Args:
            key: The key to check.

        Returns:
            True if the key exists in the store, False otherwise.

        Raises:
            RuntimeError: If the store is closed.
            TypeError: If ``key`` is not a ``str``.
        """
        check_is_open(self)
        key = validate_key(key)
        return key in self._call(self._contains_many, [key])

    async def acontains(self, key: str) -> bool:
        """Async equivalent of :meth:`contains`."""
        check_is_open(self)
        key = validate_key(key)
        return key in await self._acontains_many([key])

    def contains_many(self, keys: list[str]) -> list[bool]:
        """Check which keys exist in the store.

        Args:
            keys: The keys to check.

        Returns:
            A list of booleans, in the same order as ``keys``, where
            each entry is ``True`` if the corresponding key exists in
            the store and ``False`` otherwise.

        Raises:
            RuntimeError: If the store is closed.
            TypeError: If a key is not a ``str``.
        """
        check_is_open(self)
        keys = validate_keys(keys)
        if not keys:
            return []
        found = self._call(self._contains_many, keys)
        return [key in found for key in keys]

    async def acontains_many(self, keys: list[str]) -> list[bool]:
        """Async equivalent of :meth:`contains_many`."""
        check_is_open(self)
        keys = validate_keys(keys)
        if not keys:
            return []
        found = await self._acontains_many(keys)
        return [key in found for key in keys]

    def keys(self) -> Iterator[str]:
        """Iterate over all keys in the store.

        The errors are raised when the iteration starts.

        Yields:
            Every key currently in the store.

        Raises:
            RuntimeError: If the store is closed.
        """
        check_is_open(self)
        for batch in self._batches(self._iter_batches, _SCAN_BATCH_SIZE):
            yield from batch

    async def akeys(self) -> AsyncIterator[str]:
        """Async equivalent of :meth:`keys`."""
        check_is_open(self)
        async with contextlib.aclosing(self._aiter_batches(_SCAN_BATCH_SIZE)) as batches:
            async for batch in batches:
                for key in batch:
                    yield key

    def values(self, batch_size: int = 32) -> Iterator[dict[str, Any]]:
        """Iterate over all values without loading them all into memory
        at once.

        Args:
            batch_size: The batch size used internally when pulling
                values from the underlying store. Does not affect
                the granularity of what is yielded -- values are
                always yielded one at a time.

        Yields:
            One value at a time, in the same order as
            :meth:`iter_batches`.

        Raises:
            RuntimeError: If the store is closed.
            ValueError: If ``batch_size`` is invalid.
        """
        for batch in self.iter_batches(batch_size=batch_size):
            yield from batch.values()

    async def avalues(self, batch_size: int = 32) -> AsyncIterator[dict[str, Any]]:
        """Async equivalent of :meth:`values`."""
        batches = self.aiter_batches(batch_size=batch_size)
        async for batch in batches:
            for value in batch.values():
                yield value

    def iter_batches(self, batch_size: int = 32) -> Iterator[dict[str, dict[str, Any]]]:
        """Yield key-value pairs in batches, avoiding loading the whole
        store into memory at once.

        This is the scalable equivalent of :meth:`values`: instead of
        materializing every value as a single mapping, it streams
        them from the underlying store in chunks of ``batch_size``.

        The errors are raised when the iteration starts, and a
        ``RuntimeError`` is raised if the store is closed during the
        iteration.

        Args:
            batch_size: The maximum number of pairs to yield per
                batch. Must be a positive integer.

        Yields:
            Dicts mapping key to value, each with at most
            ``batch_size`` entries, in the same order as
            :meth:`values`. A batch may contain fewer than
            ``batch_size`` entries.

        Raises:
            RuntimeError: If the store is closed.
            ValueError: If ``batch_size`` is invalid.
        """
        check_is_open(self)
        validate_batch_size(batch_size)
        for batch in self._batches(self._iter_batches, batch_size):
            yield {key: self._codec.decode(payload) for key, payload in batch.items()}

    async def aiter_batches(self, batch_size: int = 32) -> AsyncIterator[dict[str, dict[str, Any]]]:
        """Async equivalent of :meth:`iter_batches`."""
        check_is_open(self)
        validate_batch_size(batch_size)
        async with contextlib.aclosing(self._aiter_batches(batch_size)) as batches:
            async for batch in batches:
                yield {key: self._codec.decode(payload) for key, payload in batch.items()}

    def count(self) -> int:
        """Return the total number of key-value pairs in the store.

        Returns:
            The number of key-value pairs currently stored.

        Raises:
            RuntimeError: If the store is closed.
        """
        check_is_open(self)
        return self._call(self._count)

    async def acount(self) -> int:
        """Async equivalent of :meth:`count`."""
        check_is_open(self)
        return await self._acount()

    def open(self) -> None:
        r"""Connect to the underlying backend and prepare the store for
        use (e.g. open a database connection, create a directory).

        The constructor does not do this: a store connects only once
        ``open()`` (or :meth:`__enter__`) is called. Calling ``open()`` on
        an open store does nothing, and a store may be reopened after
        :meth:`close`. If the backend cannot be opened, the error is
        raised, the resources already acquired are released, and the
        store stays closed.
        """
        with self._lock:
            if not self._closed:
                return
            try:
                self._open()
            except BaseException:
                try:
                    self._close()
                except Exception:
                    # Keep the error of _open, which explains the failure.
                    logger.warning(
                        "Could not close %s after it failed to open",
                        type(self).__name__,
                        exc_info=True,
                    )
                raise
            self._closed = False

    async def aopen(self) -> None:
        """Async equivalent of :meth:`open`."""
        if not self.closed:
            return
        try:
            await self._run_in_thread(self.open)
        except Exception:
            self._shutdown_executor()
            raise

    def close(self) -> None:
        r"""Close the store and release any underlying resources (e.g.
        database connections, file handles).

        Calling ``close()`` on a closed store does nothing, since
        :meth:`__exit__` calls it unconditionally and callers may also
        close a store manually before using it as a context manager.
        """
        with self._lock:
            if not self._closed:
                self._close()
                self._closed = True
        self._shutdown_executor()

    async def aclose(self) -> None:
        """Async equivalent of :meth:`close`."""
        if self.closed:
            self._shutdown_executor()
            return
        await self._aclose()
        await self._run_in_thread(self.close)

    @property
    def closed(self) -> bool:
        r"""Indicate whether the store is closed.

        Returns:
            ``True`` if the store has not been opened or has been
            closed, ``False`` if it is open and ready to use.
        """
        return self._closed

    @abstractmethod
    def to_uri(self) -> str:
        """Return a URI that identifies where this store's data lives.

        Returns:
            A URI. For a store backed by a file/database, passing
            this URI to :meth:`from_uri` reconnects to the same
            data. For a process-local store, the URI carries no
            reconnection information and :meth:`from_uri` returns a
            fresh, empty store.
        """

    @classmethod
    @abstractmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:
        """Reconstruct a store from a URI produced by :meth:`to_uri`.

        Args:
            uri: A URI produced by :meth:`to_uri` (of a store of this
                same class).
            read_only: If ``True`` and this store type supports a
                read-only connection mode, open it read-only.
                Ignored by store types with no such mode.

        Returns:
            A new store instance.
        """

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

    ######################
    #     Primitives     #
    ######################

    # They are called with the store open, with validated and non-empty
    # arguments, and with encoded payloads.

    @abstractmethod
    def _open(self) -> None:
        r"""Connect to the backend."""

    @abstractmethod
    def _close(self) -> None:
        r"""Release the resources of the backend.

        It is also called if :meth:`_open` raises, so it must accept a
        store that is only partly open.
        """

    @abstractmethod
    def _get_many(self, keys: list[str]) -> dict[str, Payload]:
        r"""Read the payloads of some keys.

        Args:
            keys: The keys to read. It can contain duplicates.

        Returns:
            The payload of each key that exists. The missing keys are
            not in the dict.
        """

    @abstractmethod
    def _put_many(self, items: dict[str, Payload]) -> None:
        r"""Add or replace payloads.

        Args:
            items: The payloads to write, keyed by their unique key.
        """

    @abstractmethod
    def _update(self, keys: list[str], plan: Plan) -> None:
        r"""Atomically read the existing keys, call the plan, and write
        its result.

        Nothing else must write or delete these keys between the read
        and the write. If ``plan`` raises, nothing is written. A backend
        that detects a concurrent write may read again and call
        ``plan`` again.

        Args:
            keys: The unique keys that the plan may write.
            plan: A function that takes the payloads of the keys of
                ``keys`` that exist, and returns the payloads to write,
                possibly none.

        Raises:
            KeyError: If ``plan`` rejects an existing key.
        """

    @abstractmethod
    def _delete_many(self, keys: list[str]) -> None:
        r"""Delete keys, ignoring the missing ones.

        Args:
            keys: The keys to delete. It can contain duplicates.
        """

    @abstractmethod
    def _clear(self) -> None:
        r"""Delete every key."""

    @abstractmethod
    def _count(self) -> int:
        r"""Count the keys.

        Returns:
            The number of keys.
        """

    @abstractmethod
    def _iter_batches(self, batch_size: int) -> Iterator[dict[str, Payload]]:
        r"""Yield every key and payload in batches.

        A key that is present during the whole iteration is yielded
        exactly once, even if other keys are written or deleted during
        the iteration, and at most ``batch_size`` payloads are held in
        memory. Each batch is read while the instance lock is held (for a
        backend that is not thread-safe), but the lock is released
        between two batches. The iterator is closed when the iteration
        stops early.

        Args:
            batch_size: The maximum number of pairs per batch.

        Yields:
            Non-empty dicts mapping key to payload.
        """

    def _contains_many(self, keys: list[str]) -> AbstractSet[str]:
        r"""Find which keys exist.

        The default reads the payloads with :meth:`_get_many`.

        Args:
            keys: The keys to check. It can contain duplicates.

        Returns:
            The keys of ``keys`` that exist.
        """
        return set(self._get_many(keys))

    def _filter_candidates(self, fields: Mapping[str, Any]) -> Iterator[dict[str, Payload]]:
        r"""Yield, in batches, a superset of the pairs that match a
        filter.

        :meth:`filter` applies the filter to the decoded values, so this
        method can only make ``filter`` faster: it must not change its
        result. The default yields every pair.

        Args:
            fields: The value that each field must be equal to. Empty if
                every value matches. It must not be modified.

        Returns:
            An iterator of dicts mapping key to payload.
        """
        del fields
        return self._iter_batches(_SCAN_BATCH_SIZE)

    ############################
    #     Async primitives     #
    ############################

    async def _aget_many(self, keys: list[str]) -> dict[str, Payload]:
        r"""Async equivalent of :meth:`_get_many`.

        Args:
            keys: The keys to read.

        Returns:
            The payload of each key that exists.
        """
        return await self._run_in_thread(self._call, self._get_many, keys)

    async def _aput_many(self, items: dict[str, Payload]) -> None:
        r"""Async equivalent of :meth:`_put_many`.

        Args:
            items: The payloads to write, keyed by their unique key.
        """
        await self._run_in_thread(self._call, self._put_many, items)

    async def _aupdate(self, keys: list[str], plan: Plan) -> None:
        r"""Async equivalent of :meth:`_update`.

        Args:
            keys: The unique keys that the plan may write.
            plan: A function that takes the existing payloads and
                returns the payloads to write.

        Raises:
            KeyError: If ``plan`` rejects an existing key.
        """
        await self._run_in_thread(self._call, self._update, keys, plan)

    async def _adelete_many(self, keys: list[str]) -> None:
        r"""Async equivalent of :meth:`_delete_many`.

        Args:
            keys: The keys to delete.
        """
        await self._run_in_thread(self._call, self._delete_many, keys)

    async def _aclear(self) -> None:
        r"""Async equivalent of :meth:`_clear`."""
        await self._run_in_thread(self._call, self._clear)

    async def _acount(self) -> int:
        r"""Async equivalent of :meth:`_count`.

        Returns:
            The number of keys.
        """
        return await self._run_in_thread(self._call, self._count)

    async def _acontains_many(self, keys: list[str]) -> AbstractSet[str]:
        r"""Async equivalent of :meth:`_contains_many`.

        Args:
            keys: The keys to check.

        Returns:
            The keys of ``keys`` that exist.
        """
        return await self._run_in_thread(self._call, self._contains_many, keys)

    def _aiter_batches(self, batch_size: int) -> AsyncGenerator[dict[str, Payload]]:
        r"""Async equivalent of :meth:`_iter_batches`.

        Args:
            batch_size: The maximum number of pairs per batch.

        Returns:
            An async generator of dicts mapping key to payload.
        """
        return self._abatches(self._iter_batches, batch_size)

    def _afilter_candidates(self, fields: Mapping[str, Any]) -> AsyncGenerator[dict[str, Payload]]:
        r"""Async equivalent of :meth:`_filter_candidates`.

        Args:
            fields: The value that each field must be equal to.

        Returns:
            An async generator of dicts mapping key to payload.
        """
        return self._abatches(self._filter_candidates, fields)

    async def _aclose(self) -> None:
        r"""Release the resources that only the async primitives use.

        :meth:`aclose` calls it on an open store, before it closes the
        store with :meth:`close` in a thread. The default does nothing.
        """
        return

    ###########################
    #     Template helpers    #
    ###########################

    def _call(self, func: Callable[..., T], *args: Any) -> T:
        r"""Call a function that uses the backend of an open store.

        The lock of the instance is held during the call if the backend
        is not thread-safe.

        Args:
            func: The function to call, such as a primitive.
            *args: The arguments of the function.

        Returns:
            What the function returns.

        Raises:
            RuntimeError: If the store is closed.
        """
        with self._guard:
            # Checked again here: the store may have been closed while
            # the call was waiting.
            check_is_open(self)
            return func(*args)

    async def _run_in_thread(self, func: Callable[..., T], *args: Any) -> T:
        r"""Run a function in a thread, without blocking the event loop.

        A backend that is not thread-safe has one worker thread of its
        own, which runs the functions one at a time in the order of the
        calls. A thread-safe backend uses the default executor of the
        event loop. The function sees the context variables of the
        caller.

        Args:
            func: The function to run.
            *args: The arguments of the function.

        Returns:
            What the function returns.
        """
        if self._thread_safe:
            return await asyncio.to_thread(func, *args)
        loop = asyncio.get_running_loop()
        call: Callable[[], T] = partial(func, *args)
        context = contextvars.copy_context()
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix=f"persista-{type(self).__name__}"
                )
            future = loop.run_in_executor(self._executor, context.run, call)
        return await future

    def _shutdown_executor(self) -> None:
        r"""Stop the worker thread of the store, if there is one.

        This does not wait for the thread: the calls that are already
        queued still run.
        """
        with self._executor_lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False)

    def _batches(
        self, func: Callable[..., Iterator[dict[str, Payload]]], *args: Any
    ) -> Iterator[dict[str, Payload]]:
        r"""Iterate over the batches of a primitive, holding the lock of
        the instance for one batch at a time.

        Args:
            func: A function that returns an iterator of batches, such as
                :meth:`_iter_batches`.
            *args: The arguments of the function.

        Yields:
            Each batch of the iterator.

        Raises:
            RuntimeError: If the store is closed.
        """
        iterator = self._call(func, *args)
        try:
            while (batch := self._call(self._next_batch, iterator)) is not None:
                yield batch
        finally:
            self._close_iterator(iterator)

    async def _abatches(
        self, func: Callable[..., Iterator[dict[str, Payload]]], *args: Any
    ) -> AsyncGenerator[dict[str, Payload]]:
        r"""Async equivalent of :meth:`_batches`, reading each batch in a
        thread.

        Args:
            func: A function that returns an iterator of batches.
            *args: The arguments of the function.

        Yields:
            Each batch of the iterator.

        Raises:
            RuntimeError: If the store is closed.
        """
        # A cancelled call keeps running in its thread, so the iterator
        # must not be closed while it is still reading a batch.
        iterator_lock = threading.Lock()
        iterator = await self._run_in_thread(self._call, func, *args)
        try:
            while (
                batch := await self._run_in_thread(
                    self._call, self._next_batch, iterator, iterator_lock
                )
            ) is not None:
                yield batch
        finally:
            if self.closed:
                # Do not start a worker thread for a closed store.
                self._close_iterator(iterator, iterator_lock)
            else:
                await self._run_in_thread(self._close_iterator, iterator, iterator_lock)

    @staticmethod
    def _next_batch(
        iterator: Iterator[dict[str, Payload]], iterator_lock: threading.Lock | None = None
    ) -> dict[str, Payload] | None:
        r"""Read the next batch of an iterator.

        Args:
            iterator: The iterator to read.
            iterator_lock: The lock held while the iterator is used, if
                several threads use it.

        Returns:
            The next batch, or ``None`` if the iterator is exhausted.
        """
        with iterator_lock or contextlib.nullcontext():
            return next(iterator, None)

    def _close_iterator(
        self,
        iterator: Iterator[dict[str, Payload]],
        iterator_lock: threading.Lock | None = None,
    ) -> None:
        r"""Close an iterator of batches, if it can be closed.

        Args:
            iterator: The iterator to close.
            iterator_lock: The lock held while the iterator is used, if
                several threads use it.
        """
        close = getattr(iterator, "close", None)
        if close is None:
            return
        with self._guard, iterator_lock or contextlib.nullcontext():
            close()

    def _encode_items(self, items: Mapping[str, dict[str, Any]]) -> dict[str, Payload]:
        r"""Validate the keys of items and encode their values.

        Args:
            items: The values to write, keyed by their unique key.

        Returns:
            The payload of each key.

        Raises:
            TypeError: If a key is not a ``str``, or if the codec cannot
                encode a value.
            ValueError: If a value cannot be encoded without losing data,
                or if two keys are the same string.
        """
        encode = self._codec.encode
        payloads = {validate_key(key): encode(value) for key, value in items.items()}
        # A subclass of str can define its own equality, so two keys of
        # the mapping can be the same string.
        if len(payloads) != len(items):
            msg = f"Keys must be different strings: {list(items)!r}"
            raise ValueError(msg)
        return payloads

    def _decode_many(
        self, keys: list[str], payloads: Mapping[str, Payload]
    ) -> list[dict[str, Any] | None]:
        r"""Decode the payloads of some keys, in the order of the keys.

        Args:
            keys: The keys that were read.
            payloads: The payload of each key that exists.

        Returns:
            One new value per key (also for a repeated key), or ``None``
            for a missing key.
        """
        decode = self._codec.decode
        return [None if (payload := payloads.get(key)) is None else decode(payload) for key in keys]

    def _matching_values(
        self, batch: Mapping[str, Payload], fields: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        r"""Decode a batch and keep the values that match a filter.

        Args:
            batch: The payloads to decode, keyed by their unique key.
            fields: The value that each field must be equal to.

        Returns:
            The values whose fields are all equal to the expected ones.
            A missing field is equal to ``None``.
        """
        decode = self._codec.decode
        values = (decode(payload) for payload in batch.values())
        return [
            value
            for value in values
            if all(value.get(name) == expected for name, expected in fields.items())
        ]
