r"""Implement a record store backed by a ``persista`` key-value
store."""

from __future__ import annotations

__all__ = ["RecordStore"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify

from persista.record.record import Record
from persista.store.validation import check_is_open, normalize_on_conflict, validate_batch_size

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable, Iterator
    from typing import Self

    from persista.store import BaseStore, OnConflict


class RecordStore(MultilineDisplayMixin):
    r"""Implement a record store backed by a
    :class:`persista.store.BaseStore`.

    A record store has the method names of
    :class:`~persista.store.BaseStore`, with
    :class:`~persista.record.Record` instances (keyed by their
    ``id``) taking the place of key-value pairs. It only converts
    records and delegates to the underlying store, which decides where
    and how the records are persisted: for example,
    ``RecordStore(SQLiteStore(path))`` persists records in a SQLite
    database. The URI methods belong to the underlying store (see
    :attr:`store`).

    Records are keyed by their ``id`` in the underlying key-value
    store, and a record's ``metadata`` dict is stored directly as the
    value, so the ``id`` itself is not duplicated in the stored value.

    Every operation that touches the underlying store has a sync method
    and an async twin prefixed with ``a``. A record store can be used
    as a sync or async context manager, which opens the underlying
    store on entry and closes it on exit. Constructing a record store
    does not connect to the underlying backend.

    Args:
        store: The underlying key-value store.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.store import RecordStore
        >>> from persista.store import InMemoryStore
        >>> with RecordStore(InMemoryStore()) as store:
        ...     store.set_many([Record(id="1", metadata={"author": "Alice"})])
        ...     store.get("1")
        ...
        Record(id='1', metadata={'author': 'Alice'})

        ```
    """

    def __init__(self, store: BaseStore) -> None:
        self._store = store

    @property
    def store(self) -> BaseStore:
        r"""Return the underlying key-value store."""
        return self._store

    def set(self, record: Record, *, on_conflict: OnConflict = "overwrite") -> None:
        r"""Add a single record to the store.

        Args:
            record: The record to add.
            on_conflict: The strategy to use if a record with the same
                ``id`` already exists in the store:

                - ``"raise"``: raise a :class:`KeyError` and leave
                  the existing record unchanged.
                - ``"skip"``: leave the existing record unchanged.
                - ``"overwrite"``: replace the existing record with
                  ``record``.
                - ``"merge"``: shallow-merge the metadata of
                  ``record`` into the existing metadata, with fields
                  from ``record`` taking precedence on overlapping
                  keys.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and the
                ``id`` already exists.

        Example:
            ```pycon
            >>> from persista.record import Record
            >>> from persista.record.store import RecordStore
            >>> from persista.store import InMemoryStore
            >>> with RecordStore(InMemoryStore()) as store:
            ...     store.set(Record(id="1", metadata={"author": "Alice"}))
            ...     store.set(Record(id="1", metadata={"year": 2024}), on_conflict="merge")
            ...     store.get("1")
            ...
            Record(id='1', metadata={'author': 'Alice', 'year': 2024})

            ```
        """
        self._store.set(record.id, self._to_value(record), on_conflict=on_conflict)

    async def aset(self, record: Record, *, on_conflict: OnConflict = "overwrite") -> None:
        r"""Async equivalent of :meth:`set`."""
        await self._store.aset(record.id, self._to_value(record), on_conflict=on_conflict)

    def set_many(self, records: list[Record], *, on_conflict: OnConflict = "overwrite") -> None:
        r"""Add multiple records to the store.

        Records of ``records`` that share an ``id`` are resolved with
        ``on_conflict`` too, in the order of the list: ``"overwrite"``
        keeps the last one, ``"skip"`` the first one, ``"merge"``
        merges them, and ``"raise"`` raises.

        Args:
            records: The records to add.
            on_conflict: The strategy to use for the ``id``s that
                already exist in the store. See :meth:`set` for the
                meaning of each option.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and an
                ``id`` already exists in the store or appears more than
                once in ``records``. Nothing is written.
            ValueError: If ``on_conflict`` is not a valid strategy.
        """
        on_conflict = normalize_on_conflict(on_conflict)
        self._store.set_many(self._to_items(records, on_conflict), on_conflict=on_conflict)

    async def aset_many(
        self, records: list[Record], *, on_conflict: OnConflict = "overwrite"
    ) -> None:
        r"""Async equivalent of :meth:`set_many`."""
        on_conflict = normalize_on_conflict(on_conflict)
        await self._store.aset_many(self._to_items(records, on_conflict), on_conflict=on_conflict)

    def set_batches(
        self,
        records: Iterable[Record],
        batch_size: int = 32,
        *,
        on_conflict: OnConflict = "overwrite",
    ) -> None:
        r"""Add records from an iterable, writing them to the store in
        mini-batches.

        This is the streaming equivalent of :meth:`set_many`: it
        consumes ``records`` lazily and writes at most ``batch_size``
        records at a time.

        Args:
            records: The records to add.
            batch_size: The maximum number of records to write per
                underlying :meth:`set_many` call. Must be a positive
                integer.
            on_conflict: The strategy to use for the ``id``s that
                already exist in the store. See :meth:`set` for the
                meaning of each option. Applied independently per batch,
                so with ``"raise"`` a conflict is only detected once the
                offending batch is written, not upfront.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and an
                ``id`` already exists.
            ValueError: If ``batch_size`` or ``on_conflict`` is
                invalid.

        Example:
            ```pycon
            >>> from persista.record import Record
            >>> from persista.record.store import RecordStore
            >>> from persista.store import InMemoryStore
            >>> with RecordStore(InMemoryStore()) as store:
            ...     store.set_batches((Record(id=str(i)) for i in range(5)), batch_size=2)
            ...     store.count()
            ...
            5

            ```
        """
        validate_batch_size(batch_size)
        for batch in batchify(records, size=batch_size):
            self.set_many(list(batch), on_conflict=on_conflict)

    async def aset_batches(
        self,
        records: Iterable[Record],
        batch_size: int = 32,
        *,
        on_conflict: OnConflict = "overwrite",
    ) -> None:
        r"""Async equivalent of :meth:`set_batches`."""
        validate_batch_size(batch_size)
        for batch in batchify(records, size=batch_size):
            await self.aset_many(list(batch), on_conflict=on_conflict)

    def get(self, record_id: str) -> Record | None:
        r"""Retrieve a single record by its ID.

        Args:
            record_id: The record ID to look up.

        Returns:
            The :class:`~persista.record.Record`, or ``None`` if not
            found.
        """
        value = self._store.get(record_id)
        return self._from_value(record_id, value) if value is not None else None

    async def aget(self, record_id: str) -> Record | None:
        r"""Async equivalent of :meth:`get`."""
        value = await self._store.aget(record_id)
        return self._from_value(record_id, value) if value is not None else None

    def get_many(self, record_ids: list[str]) -> list[Record | None]:
        r"""Retrieve multiple records by their IDs.

        Args:
            record_ids: The record IDs to look up.

        Returns:
            A list the same length as ``record_ids``, with the
            corresponding :class:`~persista.record.Record` for each
            ID that exists, or ``None`` for IDs not found.
        """
        return [
            self._from_value(record_id, value) if value is not None else None
            for record_id, value in zip(record_ids, self._store.get_many(record_ids), strict=True)
        ]

    async def aget_many(self, record_ids: list[str]) -> list[Record | None]:
        r"""Async equivalent of :meth:`get_many`."""
        return [
            self._from_value(record_id, value) if value is not None else None
            for record_id, value in zip(
                record_ids, await self._store.aget_many(record_ids), strict=True
            )
        ]

    def filter(self, /, **metadata_filters: Any) -> list[Record]:
        r"""Retrieve the records whose metadata fields match all the
        provided filters.

        The records are selected by the ``filter`` method of the underlying
        store, so the filters have its semantics, with every backend (see
        :meth:`persista.store.BaseStore.filter`): all filters are combined
        with ``AND``, the values are compared with the types of JSON, and
        ``None`` matches a field that is ``None`` or absent.

        Args:
            **metadata_filters: Key-value pairs where each key is a
                metadata field name and the value is the value to
                match. Calling with no arguments returns all records.

        Returns:
            A list of matching :class:`~persista.record.Record`
            instances, in no guaranteed order.

        Raises:
            RuntimeError: If the store is closed.
        """
        return [
            self._from_value(record_id, value)
            for record_id, value in self._store.filter(**metadata_filters).items()
        ]

    async def afilter(self, /, **metadata_filters: Any) -> list[Record]:
        r"""Async equivalent of :meth:`filter`."""
        matches = await self._store.afilter(**metadata_filters)
        return [self._from_value(record_id, value) for record_id, value in matches.items()]

    def delete(self, record_id: str) -> None:
        r"""Delete a record by its ID.

        IDs that do not exist are silently ignored.

        Args:
            record_id: The ID of the record to delete.
        """
        self._store.delete(record_id)

    async def adelete(self, record_id: str) -> None:
        r"""Async equivalent of :meth:`delete`."""
        await self._store.adelete(record_id)

    def delete_many(self, record_ids: list[str]) -> None:
        r"""Delete multiple records by their IDs.

        IDs that do not exist are silently ignored.

        Args:
            record_ids: The IDs of the records to delete.
        """
        self._store.delete_many(record_ids)

    async def adelete_many(self, record_ids: list[str]) -> None:
        r"""Async equivalent of :meth:`delete_many`."""
        await self._store.adelete_many(record_ids)

    def clear(self) -> None:
        r"""Remove every record from the store, without closing it."""
        self._store.clear()

    async def aclear(self) -> None:
        r"""Async equivalent of :meth:`clear`."""
        await self._store.aclear()

    def contains(self, record_id: str) -> bool:
        r"""Check if a record ID exists in the store.

        Args:
            record_id: The record ID to check.

        Returns:
            ``True`` if the record exists in the store, ``False``
            otherwise.
        """
        return self._store.contains(record_id)

    async def acontains(self, record_id: str) -> bool:
        r"""Async equivalent of :meth:`contains`."""
        return await self._store.acontains(record_id)

    def contains_many(self, record_ids: list[str]) -> list[bool]:
        r"""Check which record IDs exist in the store.

        Args:
            record_ids: The record IDs to check.

        Returns:
            A list of booleans, in the same order as ``record_ids``,
            where each entry is ``True`` if the corresponding record
            ID exists in the store and ``False`` otherwise.
        """
        return self._store.contains_many(record_ids)

    async def acontains_many(self, record_ids: list[str]) -> list[bool]:
        r"""Async equivalent of :meth:`contains_many`."""
        return await self._store.acontains_many(record_ids)

    def keys(self) -> Iterator[str]:
        r"""Iterate over the IDs of all records in the store.

        Returns:
            An iterator over every record ID currently in the store.
        """
        return self._store.keys()

    async def akeys(self) -> AsyncIterator[str]:
        r"""Async equivalent of :meth:`keys`."""
        keys = self._store.akeys()
        async for key in keys:
            yield key

    def values(self, batch_size: int = 32) -> Iterator[Record]:
        r"""Iterate over all records without loading them all into memory
        at once.

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
        r"""Async equivalent of :meth:`values`."""
        batches = self.aiter_batches(batch_size=batch_size)
        async for batch in batches:
            for record in batch:
                yield record

    def iter_batches(self, batch_size: int = 32) -> Iterator[list[Record]]:
        r"""Yield records in batches, avoiding loading the whole store
        into memory at once.

        Args:
            batch_size: The maximum number of records to yield per
                batch. Must be a positive integer.

        Yields:
            Lists of records, each with at most ``batch_size``
            elements, in the same order as :meth:`values`. The last
            batch may contain fewer than ``batch_size`` records.
        """
        for batch in self._store.iter_batches(batch_size=batch_size):
            yield [self._from_value(record_id, value) for record_id, value in batch.items()]

    async def aiter_batches(self, batch_size: int = 32) -> AsyncIterator[list[Record]]:
        r"""Async equivalent of :meth:`iter_batches`."""
        batches = self._store.aiter_batches(batch_size=batch_size)
        async for batch in batches:
            yield [self._from_value(record_id, value) for record_id, value in batch.items()]

    def count(self) -> int:
        r"""Return the total number of records in the store.

        Returns:
            The number of records currently stored.
        """
        return self._store.count()

    async def acount(self) -> int:
        r"""Async equivalent of :meth:`count`."""
        return await self._store.acount()

    def open(self) -> None:
        r"""Open the underlying store."""
        self._store.open()

    async def aopen(self) -> None:
        r"""Async equivalent of :meth:`open`."""
        await self._store.aopen()

    def close(self) -> None:
        r"""Close the underlying store."""
        self._store.close()

    async def aclose(self) -> None:
        r"""Async equivalent of :meth:`close`."""
        await self._store.aclose()

    @property
    def closed(self) -> bool:
        r"""Indicate whether the underlying store is closed.

        Returns:
            ``True`` if the store is closed, ``False`` if it is
            open and ready to use.
        """
        return self._store.closed

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

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"store": self._store}

    def _to_items(
        self, records: list[Record], on_conflict: OnConflict
    ) -> dict[str, dict[str, Any]]:
        r"""Convert records to the items written to the underlying store.

        Args:
            records: The records to convert.
            on_conflict: The normalized strategy used to resolve the
                records that share an ``id``.

        Returns:
            The values keyed by record ``id``, in the order in which
            each ``id`` first appears.

        Raises:
            KeyError: If ``on_conflict`` is ``"raise"`` and an
                ``id`` appears more than once.
            RuntimeError: If an ``id`` appears more than once with
                ``"raise"`` and the underlying store is closed.
        """
        items: dict[str, dict[str, Any]] = {}
        duplicates: set[str] = set()
        for record in records:
            value = self._to_value(record)
            if record.id not in items or on_conflict == "overwrite":
                items[record.id] = value
            elif on_conflict == "merge":
                items[record.id] = {**items[record.id], **value}
            elif on_conflict == "raise":
                duplicates.add(record.id)
        if duplicates:
            # A closed store raises the same error as for any other write.
            check_is_open(self._store)
            msg = f"Record id(s) appear more than once: {sorted(duplicates)}"
            raise KeyError(msg)
        return items

    @staticmethod
    def _to_value(record: Record) -> dict[str, Any]:
        r"""Convert a record to the value stored under its ``id``.

        Args:
            record: The record to convert.

        Returns:
            A shallow copy of the metadata of the record.
        """
        return dict(record.metadata)

    @staticmethod
    def _from_value(record_id: str, value: dict[str, Any]) -> Record:
        r"""Convert a stored value back to a record.

        Args:
            record_id: The key of the value.
            value: The stored value.

        Returns:
            The record, with a shallow copy of ``value`` as metadata.
        """
        return Record(id=record_id, metadata=dict(value))
