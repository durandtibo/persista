from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Self

import pytest

from persista.store._threaded import ThreadedAsyncStoreMixin
from persista.store.base import BaseStore
from persista.store.validation import normalize_on_conflict, validate_batch_size

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from persista.store.types import OnConflict


class _ThreadedTestStore(ThreadedAsyncStoreMixin, BaseStore):
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._closed = False

    def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def get(self, key: str) -> dict[str, Any] | None:
        value = self._data.get(key)
        return copy.deepcopy(value) if value is not None else None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [self.get(key) for key in keys]

    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
        self.set_many({key: value}, on_conflict=on_conflict)

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

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not field_filters:
            return [copy.deepcopy(v) for v in self._data.values()]
        return [
            copy.deepcopy(v)
            for v in self._data.values()
            if all(v.get(k) == val for k, val in field_filters.items())
        ]

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def delete_many(self, keys: list[str]) -> None:
        for key in keys:
            self.delete(key)

    def clear(self) -> None:
        self._data.clear()

    def contains(self, key: str) -> bool:
        return key in self._data

    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        found = [key for key in keys if key in self._data]
        missing = [key for key in keys if key not in self._data]
        return found, missing

    def keys(self) -> Iterator[str]:
        yield from list(self._data.keys())

    def iter_batches(self, batch_size: int = 32) -> Iterator[dict[str, dict[str, Any]]]:
        validate_batch_size(batch_size)
        items = list(self._data.items())
        for i in range(0, len(items), batch_size):
            yield dict(items[i : i + batch_size])

    def count(self) -> int:
        return len(self._data)

    def to_uri(self) -> str:
        return "threaded-test://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:  # noqa: ARG003
        return cls()


@pytest.mark.asyncio
async def test_threaded_mixin_aget_aset_round_trip() -> None:
    store = _ThreadedTestStore()
    await store.aset("1", {"a": 1})
    assert await store.aget("1") == {"a": 1}
    assert await store.aget("missing") is None


@pytest.mark.asyncio
async def test_threaded_mixin_aset_many_and_acontains_many() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    found, missing = await store.acontains_many(["1", "3"])
    assert found == ["1"]
    assert missing == ["3"]


@pytest.mark.asyncio
async def test_threaded_mixin_akeys_yields_all_keys() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    keys = sorted([key async for key in store.akeys()])
    assert keys == ["1", "2"]


@pytest.mark.asyncio
async def test_threaded_mixin_aiter_batches_respects_batch_size() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert sum(len(b) for b in batches) == 3
    assert all(len(b) <= 2 for b in batches)


@pytest.mark.asyncio
async def test_threaded_mixin_adelete_and_aclear() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    await store.adelete("1")
    assert await store.acontains("1") is False
    await store.aclear()
    assert await store.acount() == 0


@pytest.mark.asyncio
async def test_threaded_mixin_aclose_sets_closed() -> None:
    store = _ThreadedTestStore()
    await store.aclose()
    assert store.closed


@pytest.mark.asyncio
async def test_threaded_mixin_afilter_matches_field() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    result = await store.afilter(a=2)
    assert result == [{"a": 2}]
