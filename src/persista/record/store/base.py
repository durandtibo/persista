r"""Provide the abstract base class for record stores."""

from __future__ import annotations

__all__ = ["BaseRecordStore"]

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator, Iterator
    from typing import Self

    from persista.record.record import Record


class BaseRecordStore(ABC):
    """Abstract base class for record stores.

    Defines the common interface that all record store implementations
    must provide. The API mirrors :class:`persista.store.BaseStore`,
    with :class:`~persista.record.Record` instances (keyed by their
    ``id``) taking the place of key-value pairs.

    To implement a custom record store, subclass
    :class:`BaseRecordStore` and implement all abstract methods.

    Implementations are expected to support use as a context manager
    (``with SomeRecordStore(...) as store: ...``), which calls
    :meth:`open` on entry and :meth:`close` on exit.

    Constructing a record store does not connect to the underlying
    backend: implementations must defer that to :meth:`open`/
    :meth:`aopen`, so every other method (including :meth:`close`)
    raises until the store has been opened, either explicitly or via
    the context manager.
    """

    @abstractmethod
    def set_many(self, records: list[Record]) -> None:
        """Add or replace records in the store.

        Records whose ``id`` already exists should be replaced (upsert
        semantics).

        Args:
            records: The list of :class:`~persista.record.Record`
                instances to add.
        """

    @abstractmethod
    async def aset_many(self, records: list[Record]) -> None:
        """Async equivalent of :meth:`set_many`."""

    @abstractmethod
    def get(self, record_id: str) -> Record | None:
        """Retrieve a single record by its ID.

        Args:
            record_id: The record ID to look up.

        Returns:
            The :class:`~persista.record.Record`, or ``None`` if not
            found.
        """

    @abstractmethod
    async def aget(self, record_id: str) -> Record | None:
        """Async equivalent of :meth:`get`."""

    @abstractmethod
    def get_many(self, record_ids: list[str]) -> list[Record | None]:
        """Retrieve multiple records by their IDs.

        Args:
            record_ids: The record IDs to look up.

        Returns:
            A list the same length as ``record_ids``, with the
            corresponding :class:`~persista.record.Record` for each
            ID that exists, or ``None`` for IDs not found.
        """

    @abstractmethod
    async def aget_many(self, record_ids: list[str]) -> list[Record | None]:
        """Async equivalent of :meth:`get_many`."""

    @abstractmethod
    def filter(self, **metadata_filters: Any) -> list[Record]:
        """Retrieve records matching all provided metadata filters.

        All filters should be combined with ``AND``. Each keyword
        argument matches the corresponding metadata key exactly.

        Args:
            **metadata_filters: Key-value pairs where each key is a
                metadata field name and the value is the exact value
                to match. Calling with no arguments should return all
                records.

        Returns:
            A list of matching :class:`~persista.record.Record`
            instances.
        """

    @abstractmethod
    async def afilter(self, **metadata_filters: Any) -> list[Record]:
        """Async equivalent of :meth:`filter`."""

    @abstractmethod
    def delete(self, record_id: str) -> None:
        """Delete a record by its ID.

        IDs that do not exist should be silently ignored.

        Args:
            record_id: The ID of the record to delete.
        """

    @abstractmethod
    async def adelete(self, record_id: str) -> None:
        """Async equivalent of :meth:`delete`."""

    @abstractmethod
    def delete_many(self, record_ids: list[str]) -> None:
        """Delete multiple records by their IDs.

        IDs that do not exist should be silently ignored.

        Args:
            record_ids: The IDs of the records to delete.
        """

    @abstractmethod
    async def adelete_many(self, record_ids: list[str]) -> None:
        """Async equivalent of :meth:`delete_many`."""

    @abstractmethod
    def clear(self) -> None:
        """Remove every record from the store.

        This is equivalent to resetting the store to empty, without
        closing it.
        """

    @abstractmethod
    async def aclear(self) -> None:
        """Async equivalent of :meth:`clear`."""

    @abstractmethod
    def contains(self, record_id: str) -> bool:
        """Check if a record ID exists in the store.

        Args:
            record_id: The record ID to check.

        Returns:
            ``True`` if the record exists in the store, ``False``
            otherwise.
        """

    @abstractmethod
    async def acontains(self, record_id: str) -> bool:
        """Async equivalent of :meth:`contains`."""

    @abstractmethod
    def contains_many(self, record_ids: list[str]) -> list[bool]:
        """Check which record IDs exist in the store.

        Args:
            record_ids: The record IDs to check.

        Returns:
            A list of booleans, in the same order as ``record_ids``,
            where each entry is ``True`` if the corresponding record
            ID exists in the store and ``False`` otherwise.
        """

    @abstractmethod
    async def acontains_many(self, record_ids: list[str]) -> list[bool]:
        """Async equivalent of :meth:`contains_many`."""

    @abstractmethod
    def keys(self) -> Iterator[str]:
        """Iterate over the IDs of all records in the store.

        Yields:
            Every record ID currently in the store.
        """

    @abstractmethod
    def akeys(self) -> AsyncIterator[str]:
        """Async equivalent of :meth:`keys`."""

    def values(self, batch_size: int = 32) -> Iterator[Record]:
        """Lazily iterate over all records without loading them all into
        memory at once.

        Args:
            batch_size: The batch size used internally when pulling
                records from the underlying store. Does not affect
                the granularity of what is yielded -- records are
                always yielded one at a time.

        Yields:
            One :class:`~persista.record.Record` at a time, in the
            same order as :meth:`iter_batches`.
        """
        for batch in self.iter_batches(batch_size=batch_size):
            yield from batch

    async def avalues(self, batch_size: int = 32) -> AsyncIterator[Record]:
        """Async equivalent of :meth:`values`."""
        async for batch in self.aiter_batches(batch_size=batch_size):
            for record in batch:
                yield record

    @abstractmethod
    def iter_batches(self, batch_size: int = 32) -> Generator[list[Record], None, None]:
        """Yield records in batches, avoiding loading the whole store
        into memory at once.

        This is the scalable equivalent of :meth:`values`: instead of
        materializing every record as a single list, it streams them
        from the database in chunks of ``batch_size``.

        Args:
            batch_size: The maximum number of records to yield per
                batch. Must be a positive integer.

        Yields:
            Lists of records, each with at most ``batch_size``
            elements, in the same order as :meth:`values`. The last
            batch may contain fewer than ``batch_size`` records.
        """

    @abstractmethod
    def aiter_batches(self, batch_size: int = 32) -> AsyncIterator[list[Record]]:
        """Async equivalent of :meth:`iter_batches`."""

    @abstractmethod
    def count(self) -> int:
        """Return the total number of records in the store.

        Returns:
            The number of records currently stored.
        """

    @abstractmethod
    async def acount(self) -> int:
        """Async equivalent of :meth:`count`."""

    @abstractmethod
    def open(self) -> None:
        r"""Connect to the underlying backend and prepare the store for
        use (e.g. open a database connection, create a directory).

        The constructor must not do this itself: implementations
        connect lazily, only once ``open()`` (or :meth:`__enter__`) is
        called. Implementations should make repeated calls to
        ``open()`` safe (i.e. idempotent), since a store may be
        reopened after :meth:`close`.
        """

    @abstractmethod
    async def aopen(self) -> None:
        """Async equivalent of :meth:`open`."""

    @abstractmethod
    def close(self) -> None:
        r"""Close the store and release any underlying resources (e.g.
        database connections, file handles).

        Implementations should make repeated calls to ``close()`` safe
        (i.e. idempotent), since :meth:`__exit__` calls it
        unconditionally and callers may also close a store manually
        before using it as a context manager.
        """

    @abstractmethod
    async def aclose(self) -> None:
        """Async equivalent of :meth:`close`."""

    @property
    @abstractmethod
    def closed(self) -> bool:
        r"""Indicate whether the store is closed.

        Returns:
            ``True`` if the store has been closed, ``False`` if it is
            open and ready to use.
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
