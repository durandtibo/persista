r"""Implement a record store backed by a ``persista`` key-value
store."""

from __future__ import annotations

__all__ = ["RecordStore"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.record.record import Record
from persista.record.store.base import BaseRecordStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator, Iterator

    from persista.store import BaseStore


class RecordStore(BaseRecordStore, MultilineDisplayMixin):
    r"""Implement a record store backed by a
    :class:`persista.store.BaseStore`.

    Records are keyed by their ``id`` in the underlying key-value
    store, and a record's ``metadata`` dict is stored directly as the
    value, so the ``id`` itself is not duplicated in the stored value.

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
        return self._store

    @staticmethod
    def _to_value(record: Record) -> dict[str, Any]:
        return dict(record.metadata)

    @staticmethod
    def _from_value(record_id: str, value: dict[str, Any]) -> Record:
        return Record(id=record_id, metadata=dict(value))

    @staticmethod
    def _matches(record: Record, metadata_filters: dict[str, Any]) -> bool:
        return all(record.metadata.get(key) == val for key, val in metadata_filters.items())

    def set_many(self, records: list[Record]) -> None:
        self._store.set_many(
            {record.id: self._to_value(record) for record in records}, on_conflict="overwrite"
        )

    async def aset_many(self, records: list[Record]) -> None:
        await self._store.aset_many(
            {record.id: self._to_value(record) for record in records}, on_conflict="overwrite"
        )

    def get(self, record_id: str) -> Record | None:
        value = self._store.get(record_id)
        return self._from_value(record_id, value) if value is not None else None

    async def aget(self, record_id: str) -> Record | None:
        value = await self._store.aget(record_id)
        return self._from_value(record_id, value) if value is not None else None

    def get_many(self, record_ids: list[str]) -> list[Record | None]:
        return [
            self._from_value(record_id, value) if value is not None else None
            for record_id, value in zip(record_ids, self._store.get_many(record_ids), strict=True)
        ]

    async def aget_many(self, record_ids: list[str]) -> list[Record | None]:
        return [
            self._from_value(record_id, value) if value is not None else None
            for record_id, value in zip(
                record_ids, await self._store.aget_many(record_ids), strict=True
            )
        ]

    def filter(self, **metadata_filters: Any) -> list[Record]:
        """See :meth:`BaseRecordStore.filter`.

        Note:
            This always performs a full scan of the underlying store
            (via :meth:`~persista.store.BaseStore.iter_batches`) and
            filters records in Python, regardless of the underlying
            store's own query capabilities. In particular, for
            ``Typed*RecordStore`` variants whose metadata fields are
            stored as their own SQL columns, this does not push
            ``metadata_filters`` down to a SQL ``WHERE`` clause, so a
            filtered call is no cheaper than fetching every record.
        """
        records = []
        for batch in self._store.iter_batches():
            for record_id, value in batch.items():
                record = self._from_value(record_id, value)
                if self._matches(record, metadata_filters):
                    records.append(record)
        return records

    async def afilter(self, **metadata_filters: Any) -> list[Record]:
        """Async equivalent of :meth:`filter`.

        Note:
            Same full-scan performance characteristics as :meth:`filter`;
            see its Note.
        """
        records = []
        async for batch in self._store.aiter_batches():
            for record_id, value in batch.items():
                record = self._from_value(record_id, value)
                if self._matches(record, metadata_filters):
                    records.append(record)
        return records

    def delete(self, record_id: str) -> None:
        self._store.delete(record_id)

    async def adelete(self, record_id: str) -> None:
        await self._store.adelete(record_id)

    def delete_many(self, record_ids: list[str]) -> None:
        self._store.delete_many(record_ids)

    async def adelete_many(self, record_ids: list[str]) -> None:
        await self._store.adelete_many(record_ids)

    def clear(self) -> None:
        self._store.clear()

    async def aclear(self) -> None:
        await self._store.aclear()

    def contains(self, record_id: str) -> bool:
        return self._store.contains(record_id)

    async def acontains(self, record_id: str) -> bool:
        return await self._store.acontains(record_id)

    def contains_many(self, record_ids: list[str]) -> list[bool]:
        return self._store.contains_many(record_ids)

    async def acontains_many(self, record_ids: list[str]) -> list[bool]:
        return await self._store.acontains_many(record_ids)

    def keys(self) -> Iterator[str]:
        return self._store.keys()

    async def akeys(self) -> AsyncIterator[str]:
        async for key in self._store.akeys():
            yield key

    def iter_batches(self, batch_size: int = 32) -> Generator[list[Record], None, None]:
        for batch in self._store.iter_batches(batch_size=batch_size):
            yield [self._from_value(record_id, value) for record_id, value in batch.items()]

    async def aiter_batches(self, batch_size: int = 32) -> AsyncIterator[list[Record]]:
        async for batch in self._store.aiter_batches(batch_size=batch_size):
            yield [self._from_value(record_id, value) for record_id, value in batch.items()]

    def count(self) -> int:
        return self._store.count()

    async def acount(self) -> int:
        return await self._store.acount()

    def open(self) -> None:
        self._store.open()

    async def aopen(self) -> None:
        await self._store.aopen()

    def close(self) -> None:
        self._store.close()

    async def aclose(self) -> None:
        await self._store.aclose()

    @property
    def closed(self) -> bool:
        return self._store.closed

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"store": self._store}
