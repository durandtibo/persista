r"""Provide the abstract base classes for key-value stores."""

from __future__ import annotations

__all__ = ["AsyncBaseStore", "BaseStore"]

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from coola.utils.batching import batchify

from persista.store.validation import validate_batch_size

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        AsyncIterator,
        Generator,
        Iterable,
        Iterator,
        Mapping,
    )
    from typing import Self

    from persista.store.types import OnConflict


class BaseStore(ABC):
    """Abstract base class for key-value stores.

    Defines the common interface that all key-value store
    implementations must provide. Values are stored as dicts, which
    allows :meth:`filter` to match on the content of a value.

    To implement a custom store, subclass :class:`BaseStore` and
    implement all abstract methods.

    Implementations are expected to support use as a context manager
    (``with SomeStore(...) as store: ...``), which calls :meth:`close`
    automatically on exit.
    """

    @abstractmethod
    def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a single value by its key.

        Args:
            key: The key to look up.

        Returns:
            The value associated with ``key``, or ``None`` if the
            key is not found.
        """

    @abstractmethod
    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        """Retrieve multiple values by their keys.

        Args:
            keys: The keys to look up.

        Returns:
            A list the same length as ``keys``, with the
            corresponding value for each key that exists, or
            ``None`` for keys that are not found.
        """

    @abstractmethod
    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
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
        """

    @abstractmethod
    def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        """Add multiple key-value pairs to the store.

        Args:
            items: The values to add, keyed by their unique key.
            on_conflict: The strategy to use for keys in ``items``
                that already exist in the store. See :meth:`set` for
                the meaning of each option.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and any key
                in ``items`` already exists.
        """

    def set_batches(
        self,
        items: Iterable[tuple[str, dict[str, Any]]],
        batch_size: int = 32,
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
        """
        validate_batch_size(batch_size)
        for batch in batchify(items, size=batch_size):
            self.set_many(dict(batch), on_conflict=on_conflict)

    @abstractmethod
    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        """Retrieve values whose content matches all provided field
        filters.

        All filters should be combined with ``AND``. Each keyword
        argument matches the corresponding key in the stored value
        exactly.

        Args:
            **field_filters: Key-value pairs where each key is a
                field name within a stored value and the value is
                the exact value to match. Calling with no arguments
                should return every value in the store.

        Returns:
            A list of matching values.
        """

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a value by its key.

        Keys that do not exist should be silently ignored.

        Args:
            key: The key of the value to delete.
        """

    @abstractmethod
    def delete_many(self, keys: list[str]) -> None:
        """Delete multiple values by their keys.

        Keys that do not exist should be silently ignored.

        Args:
            keys: The keys of the values to delete.
        """

    @abstractmethod
    def clear(self) -> None:
        """Remove every key-value pair from the store.

        This is equivalent to resetting the store to empty, without
        closing it.
        """

    @abstractmethod
    def contains(self, key: str) -> bool:
        """Check if the key exists in the store.

        Args:
            key: The key to check.

        Returns:
            True if the key exists in the store, False otherwise.
        """

    @abstractmethod
    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        """Check which keys exist in the store.

        Args:
            keys: The keys to check.

        Returns:
            A tuple of two lists: ``(found, missing)`` where ``found``
            contains the keys that exist in the store and ``missing``
            contains the keys that do not.
        """

    @abstractmethod
    def keys(self) -> Iterator[str]:
        """Iterate over all keys in the store.

        Yields:
            Every key currently in the store.
        """

    def values(self, batch_size: int = 32) -> Iterator[dict[str, Any]]:
        """Iterate over all values without loading them all into memory
        at once.

        Args:
            batch_size: The batch size used internally when pulling
                values from the underlying store. Does not affect
                the granularity of what is yielded — values are
                always yielded one at a time.

        Yields:
            One value at a time, in the same order as
            :meth:`iter_batches`.
        """
        for batch in self.iter_batches(batch_size=batch_size):
            yield from batch.values()

    @abstractmethod
    def iter_batches(
        self, batch_size: int = 32
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        """Yield key-value pairs in batches, avoiding loading the whole
        store into memory at once.

        This is the scalable equivalent of :meth:`values`: instead of
        materializing every value as a single mapping, it streams
        them from the underlying store in chunks of ``batch_size``.

        Args:
            batch_size: The maximum number of pairs to yield per
                batch. Must be a positive integer.

        Yields:
            Dicts mapping key to value, each with at most
            ``batch_size`` entries, in the same order as
            :meth:`values`. The last batch may contain fewer than
            ``batch_size`` entries.
        """

    @abstractmethod
    def count(self) -> int:
        """Return the total number of key-value pairs in the store.

        Returns:
            The number of key-value pairs currently stored.
        """

    @abstractmethod
    def close(self) -> None:
        r"""Close the store and release any underlying resources (e.g.
        database connections, file handles).

        Implementations should make repeated calls to ``close()`` safe
        (i.e. idempotent), since :meth:`__exit__` calls it
        unconditionally and callers may also close a store manually
        before using it as a context manager.
        """

    @property
    @abstractmethod
    def closed(self) -> bool:
        r"""Indicate whether the store is closed.

        Returns:
            ``True`` if the store has been closed, ``False`` if it is
            open and ready to use.
        """

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class AsyncBaseStore(ABC):
    """Abstract base class for asynchronous key-value stores.

    Mirrors :class:`BaseStore`, but every method that touches the
    underlying store is a coroutine (or an async generator), for
    implementations backed by an async driver (e.g. an async DB client).

    Implementations are expected to support use as an async context
    manager (``async with SomeStore(...) as store: ...``), which calls
    :meth:`close` automatically on exit.
    """

    @abstractmethod
    async def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a single value by its key.

        Args:
            key: The key to look up.

        Returns:
            The value associated with ``key``, or ``None`` if the
            key is not found.
        """

    @abstractmethod
    async def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        """Retrieve multiple values by their keys.

        Args:
            keys: The keys to look up.

        Returns:
            A list the same length as ``keys``, with the
            corresponding value for each key that exists, or
            ``None`` for keys that are not found.
        """

    @abstractmethod
    async def set(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
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
        """

    @abstractmethod
    async def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        """Add multiple key-value pairs to the store.

        Args:
            items: The values to add, keyed by their unique key.
            on_conflict: The strategy to use for keys in ``items``
                that already exist in the store. See :meth:`set` for
                the meaning of each option.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and any key
                in ``items`` already exists.
        """

    async def set_batches(
        self,
        items: Iterable[tuple[str, dict[str, Any]]],
        batch_size: int = 32,
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
        """
        validate_batch_size(batch_size)
        for batch in batchify(items, size=batch_size):
            await self.set_many(dict(batch), on_conflict=on_conflict)

    @abstractmethod
    async def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        """Retrieve values whose content matches all provided field
        filters.

        All filters should be combined with ``AND``. Each keyword
        argument matches the corresponding key in the stored value
        exactly.

        Args:
            **field_filters: Key-value pairs where each key is a
                field name within a stored value and the value is
                the exact value to match. Calling with no arguments
                should return every value in the store.

        Returns:
            A list of matching values.
        """

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a value by its key.

        Keys that do not exist should be silently ignored.

        Args:
            key: The key of the value to delete.
        """

    @abstractmethod
    async def delete_many(self, keys: list[str]) -> None:
        """Delete multiple values by their keys.

        Keys that do not exist should be silently ignored.

        Args:
            keys: The keys of the values to delete.
        """

    @abstractmethod
    async def clear(self) -> None:
        """Remove every key-value pair from the store.

        This is equivalent to resetting the store to empty, without
        closing it.
        """

    @abstractmethod
    async def contains(self, key: str) -> bool:
        """Check if the key exists in the store.

        Args:
            key: The key to check.

        Returns:
            True if the key exists in the store, False otherwise.
        """

    @abstractmethod
    async def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        """Check which keys exist in the store.

        Args:
            keys: The keys to check.

        Returns:
            A tuple of two lists: ``(found, missing)`` where ``found``
            contains the keys that exist in the store and ``missing``
            contains the keys that do not.
        """

    @abstractmethod
    def keys(self) -> AsyncIterator[str]:
        """Iterate over all keys in the store.

        Yields:
            Every key currently in the store.
        """

    async def values(self, batch_size: int = 32) -> AsyncIterator[dict[str, Any]]:
        """Iterate over all values without loading them all into memory
        at once.

        Args:
            batch_size: The batch size used internally when pulling
                values from the underlying store. Does not affect
                the granularity of what is yielded — values are
                always yielded one at a time.

        Yields:
            One value at a time, in the same order as
            :meth:`iter_batches`.
        """
        async for batch in self.iter_batches(batch_size=batch_size):
            for value in batch.values():
                yield value

    @abstractmethod
    def iter_batches(self, batch_size: int = 32) -> AsyncGenerator[dict[str, dict[str, Any]], None]:
        """Yield key-value pairs in batches, avoiding loading the whole
        store into memory at once.

        This is the scalable equivalent of :meth:`values`: instead of
        materializing every value as a single mapping, it streams
        them from the underlying store in chunks of ``batch_size``.

        Args:
            batch_size: The maximum number of pairs to yield per
                batch. Must be a positive integer.

        Yields:
            Dicts mapping key to value, each with at most
            ``batch_size`` entries, in the same order as
            :meth:`values`. The last batch may contain fewer than
            ``batch_size`` entries.
        """

    @abstractmethod
    async def count(self) -> int:
        """Return the total number of key-value pairs in the store.

        Returns:
            The number of key-value pairs currently stored.
        """

    @abstractmethod
    async def close(self) -> None:
        r"""Close the store and release any underlying resources (e.g.
        database connections, file handles).

        Implementations should make repeated calls to ``close()`` safe
        (i.e. idempotent), since :meth:`__aexit__` calls it
        unconditionally and callers may also close a store manually
        before using it as a context manager.
        """

    @property
    @abstractmethod
    def closed(self) -> bool:
        r"""Indicate whether the store is closed.

        Returns:
            ``True`` if the store has been closed, ``False`` if it is
            open and ready to use.
        """

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
