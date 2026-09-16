r"""Provide a mixin that derives async methods from a store's sync
methods via a background thread, for backends with no native async
driver."""

from __future__ import annotations

__all__ = ["ThreadedAsyncStoreMixin", "athread_iter"]

import asyncio
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator, Mapping

    from persista.store.types import OnConflict

_T = TypeVar("_T")


_SENTINEL: Any = object()


async def athread_iter(sync_iter_factory: Callable[[], Iterator[_T]]) -> AsyncIterator[_T]:
    r"""Bridge a sync iterator/generator to an async one via a background
    thread.

    Calls ``sync_iter_factory`` and then pulls one item at a time from
    the resulting iterator with ``asyncio.to_thread``, so neither
    creating the iterator nor advancing it blocks the event loop. This
    is the building block behind :meth:`ThreadedAsyncStoreMixin.akeys`
    and :meth:`ThreadedAsyncStoreMixin.aiter_batches`, but it is generic
    enough to bridge any sync iterator/generator, not just store ones.

    Unlike wrapping the whole sync iterable in a single
    ``asyncio.to_thread`` call, this never materializes more than one
    item in memory at a time, which matters for iterators that stream
    over a large or unbounded source (e.g. every row/batch in a table).

    Args:
        sync_iter_factory: A zero-argument callable that returns the
            sync iterator/generator to bridge, e.g. ``store.keys`` or
            ``lambda: store.iter_batches(batch_size=32)``. It is called
            in a worker thread, so it is safe to use even when creating
            the iterator itself does blocking I/O (e.g. opening a
            server-side cursor).

    Yields:
        Each item produced by the sync iterator, in order.
    """
    iterator = await asyncio.to_thread(lambda: iter(sync_iter_factory()))
    while True:
        item = await asyncio.to_thread(next, iterator, _SENTINEL)
        if item is _SENTINEL:
            return
        yield item


class ThreadedAsyncStoreMixin:
    r"""Provide every ``a``-prefixed async method as an
    ``asyncio.to_thread`` wrapper around the corresponding sync method.

    Mix this into a :class:`~persista.store.BaseStore` subclass whose
    backend has no native async driver (in-memory, file, LMDB, DuckDB):
    the subclass only needs to implement the sync side, and this mixin
    supplies a fully-conformant async side for free by running each sync
    call in a worker thread. ``akeys``/``aiter_batches`` additionally
    use :func:`athread_iter` to bridge the sync generators returned by
    ``keys``/``iter_batches`` across the thread boundary, pulling one
    key/batch at a time rather than materializing the whole store in
    memory.

    Must be listed before ``BaseStore`` in the MRO (e.g. ``class
    Foo(ThreadedAsyncStoreMixin, BaseStore)``) so its concrete methods
    satisfy ``BaseStore``'s abstract async methods.
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

    async def acontains_many(self, keys: list[str]) -> list[bool]:
        return await asyncio.to_thread(self.contains_many, keys)

    async def akeys(self) -> AsyncIterator[str]:
        async for key in athread_iter(self.keys):
            yield key

    async def aiter_batches(self, batch_size: int = 32) -> AsyncIterator[dict[str, dict[str, Any]]]:
        async for batch in athread_iter(lambda: self.iter_batches(batch_size=batch_size)):
            yield batch

    async def acount(self) -> int:
        return await asyncio.to_thread(self.count)

    async def aopen(self) -> None:
        await asyncio.to_thread(self.open)

    async def aclose(self) -> None:
        await asyncio.to_thread(self.close)
