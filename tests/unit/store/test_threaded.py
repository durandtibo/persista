from __future__ import annotations

import asyncio
import contextlib
import copy
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest

from persista.store._threaded import ThreadedAsyncStoreMixin
from persista.store.base import BaseStore
from persista.store.validation import normalize_on_conflict, validate_batch_size

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from typing import Self

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

    def contains_many(self, keys: list[str]) -> list[bool]:
        return [key in self._data for key in keys]

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


# --- aget/aset ---


async def test_threaded_mixin_aget_aset_round_trip() -> None:
    store = _ThreadedTestStore()
    await store.aset("1", {"a": 1})
    assert await store.aget("1") == {"a": 1}
    assert await store.aget("missing") is None


async def test_threaded_mixin_aset_many_and_acontains_many() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert await store.acontains_many(["1", "3"]) == [True, False]


# --- akeys ---


async def test_threaded_mixin_akeys_yields_all_keys() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    keys = sorted([key async for key in store.akeys()])
    assert keys == ["1", "2"]


# --- aiter_batches ---


async def test_threaded_mixin_aiter_batches_respects_batch_size() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert sum(len(b) for b in batches) == 3
    assert all(len(b) <= 2 for b in batches)


# --- aget_many/adelete_many/aclear ---


async def test_threaded_mixin_aget_many() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert await store.aget_many(["1", "3"]) == [{"a": 1}, None]


async def test_threaded_mixin_adelete_many() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    await store.adelete_many(["1", "2"])
    assert await store.acount() == 0


async def test_threaded_mixin_adelete_and_aclear() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    await store.adelete("1")
    assert await store.acontains("1") is False
    await store.aclear()
    assert await store.acount() == 0


# --- aclose ---


async def test_threaded_mixin_aclose_sets_closed() -> None:
    store = _ThreadedTestStore()
    await store.aclose()
    assert store.closed


# --- afilter ---


async def test_threaded_mixin_afilter_matches_field() -> None:
    store = _ThreadedTestStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    result = await store.afilter(a=2)
    assert result == [{"a": 2}]


class _SlowStore(_ThreadedTestStore):
    r"""Store whose ``get`` sleeps and records which thread ran it."""

    def __init__(self, delay: float = 0.05) -> None:
        super().__init__()
        self._delay = delay
        self.get_thread: threading.Thread | None = None

    def get(self, key: str) -> dict[str, Any] | None:
        self.get_thread = threading.current_thread()
        time.sleep(self._delay)
        return super().get(key)


class _BoomError(RuntimeError):
    pass


class _RaisingStore(_ThreadedTestStore):
    r"""Store whose ``get`` always raises, to test exception
    propagation."""

    def get(self, key: str) -> dict[str, Any] | None:
        msg = f"boom for {key}"
        raise _BoomError(msg)


# --- threading behavior ---


async def test_threaded_mixin_aget_runs_on_worker_thread() -> None:
    store = _SlowStore()
    await store.aset("1", {"a": 1})
    await store.aget("1")
    assert store.get_thread is not None
    assert store.get_thread is not threading.current_thread()


async def test_threaded_mixin_aget_does_not_block_event_loop() -> None:
    store = _SlowStore(delay=0.2)
    await store.aset("1", {"a": 1})

    ticks = 0

    async def tick_counter() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    ticker = asyncio.create_task(tick_counter())
    await store.aget("1")
    ticker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await ticker

    assert ticks > 3


async def test_threaded_mixin_aget_cancellation_propagates_and_store_stays_usable() -> None:
    store = _SlowStore(delay=0.2)
    await store.aset("1", {"a": 1})

    task = asyncio.create_task(store.aget("1"))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await store.aget("1") == {"a": 1}


async def test_threaded_mixin_exception_propagates_from_worker_thread() -> None:
    store = _RaisingStore()
    with pytest.raises(_BoomError, match="boom for 1"):
        await store.aget("1")


async def test_threaded_mixin_concurrent_aset_calls_all_persist() -> None:
    store = _ThreadedTestStore()
    await asyncio.gather(*(store.aset(str(i), {"a": i}) for i in range(50)))
    assert await store.acount() == 50
    for i in range(50):
        assert await store.aget(str(i)) == {"a": i}
