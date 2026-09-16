from __future__ import annotations

import asyncio
import contextlib
import copy
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest

from persista.store.base import BaseStore
from persista.store.threaded import ThreadedAsyncStoreMixin, athread_iter
from persista.store.validation import normalize_on_conflict, validate_batch_size

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from typing import Self

    from persista.store.types import OnConflict


class _ThreadedTestStore(ThreadedAsyncStoreMixin, BaseStore):
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._closed = False

    def open(self) -> None:
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


# --- athread_iter ---


async def test_athread_iter_yields_all_items_in_order() -> None:
    items = [1, 2, 3, 4, 5]
    result = [item async for item in athread_iter(lambda: iter(items))]
    assert result == items


async def test_athread_iter_empty_iterator_yields_nothing() -> None:
    result = [item async for item in athread_iter(lambda: iter([]))]
    assert result == []


async def test_athread_iter_calls_factory_lazily_on_first_iteration() -> None:
    called = False

    def factory() -> Iterator[int]:
        nonlocal called
        called = True
        return iter([1, 2, 3])

    gen = athread_iter(factory)
    assert called is False
    result = [item async for item in gen]
    assert called is True
    assert result == [1, 2, 3]


async def test_athread_iter_calls_factory_once_per_call() -> None:
    calls = 0

    def factory() -> Iterator[int]:
        nonlocal calls
        calls += 1
        return iter([1, 2, 3])

    assert [item async for item in athread_iter(factory)] == [1, 2, 3]
    assert calls == 1


async def test_athread_iter_bridges_a_generator_not_just_a_list_iterator() -> None:
    def gen_factory() -> Iterator[int]:
        yield from range(3)

    result = [item async for item in athread_iter(gen_factory)]
    assert result == [0, 1, 2]


async def test_athread_iter_advances_items_on_a_worker_thread() -> None:
    main_thread = threading.current_thread()
    threads_seen: list[threading.Thread] = []

    class _ThreadRecordingIterator:
        def __iter__(self) -> _ThreadRecordingIterator:
            return self

        def __next__(self) -> int:
            threads_seen.append(threading.current_thread())
            if len(threads_seen) > 3:
                raise StopIteration
            return len(threads_seen)

    result = [item async for item in athread_iter(_ThreadRecordingIterator)]

    assert result == [1, 2, 3]
    assert threads_seen
    assert all(thread is not main_thread for thread in threads_seen)


async def test_athread_iter_propagates_exception_raised_while_advancing() -> None:
    def factory() -> Iterator[int]:
        def gen() -> Iterator[int]:
            yield 1
            msg = "boom"
            raise _BoomError(msg)

        return gen()

    with pytest.raises(_BoomError, match="boom"):
        [item async for item in athread_iter(factory)]


async def test_athread_iter_does_not_block_the_event_loop() -> None:
    def factory() -> Iterator[int]:
        def gen() -> Iterator[int]:
            for i in range(20):
                time.sleep(0.005)
                yield i

        return gen()

    ticks = 0

    async def tick_counter() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    ticker = asyncio.create_task(tick_counter())
    result = [item async for item in athread_iter(factory)]
    ticker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await ticker

    assert result == list(range(20))
    assert ticks > 3
