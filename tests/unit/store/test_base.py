from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import BaseStore, normalize_on_conflict, validate_batch_size

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator, Iterator, Mapping

    from persista.store import OnConflict


class InMemoryTestStore(BaseStore):
    r"""Minimal concrete implementation of ``BaseStore`` used to
    exercise the concrete methods it provides (``values``/``avalues``,
    ``set_batches``/``aset_batches``, the sync and async context manager
    protocols)."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._closed = False

    def close(self) -> None:
        self._closed = True

    async def aclose(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def get(self, key: str) -> dict[str, Any] | None:
        value = self._data.get(key)
        return copy.deepcopy(value) if value is not None else None

    async def aget(self, key: str) -> dict[str, Any] | None:
        return self.get(key)

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [self.get(key) for key in keys]

    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [await self.aget(key) for key in keys]

    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
        self.set_many({key: value}, on_conflict=on_conflict)

    async def aset(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
    ) -> None:
        self.set(key, value, on_conflict=on_conflict)

    def set_many(
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

    async def aset_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        self.set_many(items, on_conflict=on_conflict)

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not field_filters:
            return [copy.deepcopy(value) for value in self._data.values()]
        return [
            copy.deepcopy(value)
            for value in self._data.values()
            if all(value.get(k) == v for k, v in field_filters.items())
        ]

    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
        return self.filter(**field_filters)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def adelete(self, key: str) -> None:
        self.delete(key)

    def delete_many(self, keys: list[str]) -> None:
        for key in keys:
            self.delete(key)

    async def adelete_many(self, keys: list[str]) -> None:
        self.delete_many(keys)

    def clear(self) -> None:
        self._data.clear()

    async def aclear(self) -> None:
        self.clear()

    def contains(self, key: str) -> bool:
        return key in self._data

    async def acontains(self, key: str) -> bool:
        return self.contains(key)

    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        found = [key for key in keys if key in self._data]
        missing = [key for key in keys if key not in self._data]
        return found, missing

    async def acontains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        return self.contains_many(keys)

    def keys(self) -> Iterator[str]:
        yield from list(self._data.keys())

    async def akeys(self) -> AsyncIterator[str]:
        for key in list(self._data.keys()):
            yield key

    def iter_batches(self, batch_size: int = 32) -> Iterator[dict[str, dict[str, Any]]]:
        validate_batch_size(batch_size)
        items = list(self._data.items())
        for i in range(0, len(items), batch_size):
            yield dict(items[i : i + batch_size])

    async def aiter_batches(self, batch_size: int = 32) -> AsyncIterator[dict[str, dict[str, Any]]]:
        for batch in self.iter_batches(batch_size=batch_size):
            yield batch

    def count(self) -> int:
        return len(self._data)

    async def acount(self) -> int:
        return self.count()

    def to_uri(self) -> str:
        return "test://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> InMemoryTestStore:  # noqa: ARG003
        return cls()


def test_base_store_values_iterates_all() -> None:
    store = InMemoryTestStore()
    store.set_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    assert sorted(v["a"] for v in store.values(batch_size=2)) == [1, 2, 3]


async def test_base_store_avalues_iterates_all() -> None:
    store = InMemoryTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    values = [v async for v in store.avalues(batch_size=2)]
    assert sorted(v["a"] for v in values) == [1, 2, 3]


def test_base_store_set_batches() -> None:
    store = InMemoryTestStore()
    store.set_batches([("1", {"a": 1}), ("2", {"a": 2})], batch_size=1)
    assert store.count() == 2


async def test_base_store_aset_batches() -> None:
    store = InMemoryTestStore()
    await store.aset_batches([("1", {"a": 1}), ("2", {"a": 2})], batch_size=1)
    assert await store.acount() == 2


def test_base_store_set_batches_default_batch_size() -> None:
    store = InMemoryTestStore()
    store.set_batches([("1", {"a": 1}), ("2", {"a": 2})])
    assert store.count() == 2


async def test_base_store_aset_batches_default_batch_size() -> None:
    store = InMemoryTestStore()
    await store.aset_batches([("1", {"a": 1}), ("2", {"a": 2})])
    assert await store.acount() == 2


def test_base_store_sync_context_manager_calls_close() -> None:
    with InMemoryTestStore() as store:
        assert not store.closed
    assert store.closed


async def test_base_store_async_context_manager_calls_aclose() -> None:
    async with InMemoryTestStore() as store:
        assert not store.closed
    assert store.closed


def test_base_store_is_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        BaseStore()  # type: ignore[abstract]


def test_base_store_is_abstract_missing_to_uri_from_uri() -> None:
    class IncompleteStore(BaseStore):
        def close(self) -> None:
            pass

        async def aclose(self) -> None:
            pass

        @property
        def closed(self) -> bool:
            return False

        def get(self, key: str) -> dict[str, Any] | None:  # noqa: ARG002
            return None

        async def aget(self, key: str) -> dict[str, Any] | None:
            return self.get(key)

        def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:  # noqa: ARG002
            return []

        async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
            return self.get_many(keys)

        def set(
            self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
        ) -> None:
            pass

        async def aset(
            self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
        ) -> None:
            self.set(key, value, on_conflict=on_conflict)

        def set_many(
            self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
        ) -> None:
            pass

        async def aset_many(
            self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
        ) -> None:
            self.set_many(items, on_conflict=on_conflict)

        def filter(self, **field_filters: Any) -> list[dict[str, Any]]:  # noqa: ARG002
            return []

        async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
            return self.filter(**field_filters)

        def delete(self, key: str) -> None:
            pass

        async def adelete(self, key: str) -> None:
            self.delete(key)

        def delete_many(self, keys: list[str]) -> None:
            pass

        async def adelete_many(self, keys: list[str]) -> None:
            self.delete_many(keys)

        def clear(self) -> None:
            pass

        async def aclear(self) -> None:
            self.clear()

        def contains(self, key: str) -> bool:  # noqa: ARG002
            return False

        async def acontains(self, key: str) -> bool:
            return self.contains(key)

        def contains_many(
            self,
            keys: list[str],  # noqa: ARG002
        ) -> tuple[list[str], list[str]]:
            return [], []

        async def acontains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
            return self.contains_many(keys)

        def keys(self) -> Iterator[str]:
            return iter(())

        async def akeys(self) -> AsyncIterator[str]:
            for key in ():
                yield key

        def iter_batches(
            self,
            batch_size: int = 32,  # noqa: ARG002
        ) -> Generator[dict[str, dict[str, Any]], None, None]:
            yield from ()

        async def aiter_batches(
            self,
            batch_size: int = 32,
        ) -> AsyncIterator[dict[str, dict[str, Any]]]:
            for batch in self.iter_batches(batch_size=batch_size):
                yield batch

        def count(self) -> int:
            return 0

        async def acount(self) -> int:
            return self.count()

        # Intentionally omit ``to_uri``/``from_uri`` to keep this class abstract.

    with pytest.raises(TypeError, match="abstract"):
        IncompleteStore()  # type: ignore[abstract]
