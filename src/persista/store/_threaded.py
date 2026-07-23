r"""Provide a mixin that derives async methods from a store's sync
methods via a background thread, for backends with no native async
driver."""

from __future__ import annotations

__all__ = ["ThreadedAsyncStoreMixin"]

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from persista.store.types import OnConflict


class ThreadedAsyncStoreMixin:
    r"""Provide every ``a``-prefixed async method as an
    ``asyncio.to_thread`` wrapper around the corresponding sync
    method.

    Mix this into a :class:`~persista.store.base.BaseStore` subclass
    whose backend has no native async driver (in-memory, file, LMDB,
    DuckDB): the subclass only needs to implement the sync side, and
    this mixin supplies a fully-conformant async side for free by
    running each sync call in a worker thread. ``akeys``/
    ``aiter_batches`` additionally bridge the sync generators returned
    by ``keys``/``iter_batches`` across the thread boundary, pulling
    one key/batch at a time via ``asyncio.to_thread`` rather than
    materializing the whole store in memory.

    Must be listed before ``BaseStore`` in the MRO (e.g.
    ``class Foo(ThreadedAsyncStoreMixin, BaseStore)``) so its concrete
    methods satisfy ``BaseStore``'s abstract async methods.
    """

    async def aget(self, key: str) -> dict[str, Any] | None:
        return await asyncio.to_thread(self.get, key)

    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return await asyncio.to_thread(self.get_many, keys)

    async def aset(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
    ) -> None:
        await asyncio.to_thread(self.set, key, value, on_conflict)

    async def aset_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        await asyncio.to_thread(self.set_many, items, on_conflict)

    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(lambda: self.filter(**field_filters))

    async def adelete(self, key: str) -> None:
        await asyncio.to_thread(self.delete, key)

    async def adelete_many(self, keys: list[str]) -> None:
        await asyncio.to_thread(self.delete_many, keys)

    async def aclear(self) -> None:
        await asyncio.to_thread(self.clear)

    async def acontains(self, key: str) -> bool:
        return await asyncio.to_thread(self.contains, key)

    async def acontains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        return await asyncio.to_thread(self.contains_many, keys)

    async def akeys(self) -> AsyncIterator[str]:
        sentinel = object()
        iterator = await asyncio.to_thread(lambda: iter(self.keys()))
        while True:
            key = await asyncio.to_thread(next, iterator, sentinel)
            if key is sentinel:
                return
            yield key

    async def aiter_batches(
        self, batch_size: int = 32
    ) -> AsyncIterator[dict[str, dict[str, Any]]]:
        sentinel = object()
        iterator = await asyncio.to_thread(lambda: iter(self.iter_batches(batch_size=batch_size)))
        while True:
            batch = await asyncio.to_thread(next, iterator, sentinel)
            if batch is sentinel:
                return
            yield batch

    async def acount(self) -> int:
        return await asyncio.to_thread(self.count)

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)
