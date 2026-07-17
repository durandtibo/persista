from __future__ import annotations

import asyncio
import copy
from typing import TYPE_CHECKING, Any

import pytest

from persista.store.base import AsyncBaseStore
from persista.store.validation import normalize_on_conflict, validate_batch_size

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Mapping

    from persista.store.types import OnConflict


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class InMemoryAsyncStore(AsyncBaseStore):
    r"""Minimal concrete implementation of ``AsyncBaseStore`` used to
    exercise the concrete methods it provides (``values``,
    ``set_batches``, ``__aenter__``/``__aexit__``)."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    async def get(self, key: str) -> dict[str, Any] | None:
        value = self._data.get(key)
        return copy.deepcopy(value) if value is not None else None

    async def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [await self.get(key) for key in keys]

    async def set(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
    ) -> None:
        await self.set_many({key: value}, on_conflict=on_conflict)

    async def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        on_conflict = normalize_on_conflict(on_conflict)
        conflicts = [key for key in items if key in self._data]
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {conflicts}"
            raise KeyError(msg)
        for key, value in items.items():
            if key in self._data and on_conflict == "skip":
                continue
            if key in self._data and on_conflict == "merge":
                self._data[key] = {**self._data[key], **copy.deepcopy(value)}
                continue
            self._data[key] = copy.deepcopy(value)

    async def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not field_filters:
            return [copy.deepcopy(value) for value in self._data.values()]
        return [
            copy.deepcopy(value)
            for value in self._data.values()
            if all(value.get(key) == val for key, val in field_filters.items())
        ]

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def delete_many(self, keys: list[str]) -> None:
        for key in keys:
            await self.delete(key)

    async def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        found = [key for key in keys if key in self._data]
        missing = [key for key in keys if key not in self._data]
        return found, missing

    async def keys(self) -> AsyncIterator[str]:
        for key in list(self._data.keys()):
            yield key

    async def iter_batches(
        self, batch_size: int = 32
    ) -> AsyncGenerator[dict[str, dict[str, Any]], None]:
        validate_batch_size(batch_size)
        items = list(self._data.items())
        for i in range(0, len(items), batch_size):
            yield dict(items[i : i + batch_size])

    async def count(self) -> int:
        return len(self._data)


@pytest.fixture
def store() -> InMemoryAsyncStore:
    return InMemoryAsyncStore()


def test_async_base_store_is_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        AsyncBaseStore()  # type: ignore[abstract]


def test_async_base_store_values(store: InMemoryAsyncStore) -> None:
    async def run_test() -> list[dict[str, Any]]:
        await store.set_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
        return [value async for value in store.values(batch_size=2)]

    values = run(run_test())
    assert sorted(values, key=lambda v: v["a"]) == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_async_base_store_set_batches(store: InMemoryAsyncStore) -> None:
    async def run_test() -> int:
        await store.set_batches([("1", {"a": 1}), ("2", {"a": 2}), ("3", {"a": 3})], batch_size=2)
        return await store.count()

    assert run(run_test()) == 3


def test_async_base_store_set_batches_default_batch_size(store: InMemoryAsyncStore) -> None:
    async def run_test() -> int:
        await store.set_batches([(str(i), {"a": i}) for i in range(5)])
        return await store.count()

    assert run(run_test()) == 5


def test_async_base_store_context_manager() -> None:
    async def run_test() -> bool:
        async with InMemoryAsyncStore() as store:
            assert not store.closed
        return store.closed

    assert run(run_test())
