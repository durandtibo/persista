from __future__ import annotations

import contextvars
import threading
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import BaseStore, JsonCodec, PickleCodec

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Iterator, Mapping

    from persista.store.types import Payload, Plan

CONTEXT: contextvars.ContextVar[str] = contextvars.ContextVar("CONTEXT", default="unset")


class DictStore(BaseStore):
    r"""Minimal implementation of the primitives of ``BaseStore``, which
    records the calls it receives.

    The data survives ``close``, as in a persistent store.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.data: dict[str, Payload] = {}
        self.calls: list[tuple[Any, ...]] = []
        self.lock_held: list[bool] = []
        self.threads: list[str] = []
        self.contexts: list[str] = []
        self.closed_iterators = 0

    def to_uri(self) -> str:
        return "dict://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> DictStore:
        del uri, read_only
        return cls()

    def record(self, *call: Any) -> None:
        self.calls.append(call)
        self.lock_held.append(self._lock._is_owned())
        self.threads.append(threading.current_thread().name)
        self.contexts.append(CONTEXT.get())

    def _open(self) -> None:
        self.record("open")

    def _close(self) -> None:
        self.record("close")

    def _get_many(self, keys: list[str]) -> dict[str, Payload]:
        self.record("get_many", keys)
        return {key: self.data[key] for key in keys if key in self.data}

    def _put_many(self, items: dict[str, Payload]) -> None:
        self.record("put_many", items)
        self.data.update(items)

    def _update(self, keys: list[str], plan: Plan) -> None:
        self.record("update", keys)
        self.data.update(plan({key: self.data[key] for key in keys if key in self.data}))

    def _delete_many(self, keys: list[str]) -> None:
        self.record("delete_many", keys)
        for key in keys:
            self.data.pop(key, None)

    def _clear(self) -> None:
        self.record("clear")
        self.data.clear()

    def _count(self) -> int:
        self.record("count")
        return len(self.data)

    def _iter_batches(self, batch_size: int) -> Iterator[dict[str, Payload]]:
        try:
            keys = list(self.data)
            for start in range(0, len(keys), batch_size):
                self.record("iter_batches", batch_size)
                yield {key: self.data[key] for key in keys[start : start + batch_size]}
        finally:
            self.closed_iterators += 1


class ThreadSafeStore(DictStore):
    _thread_safe = True


class FailingOpenStore(DictStore):
    def _open(self) -> None:
        msg = "cannot connect"
        raise ConnectionError(msg)


class InterruptedOpenStore(DictStore):
    def _open(self) -> None:
        msg = "interrupted"
        raise KeyboardInterrupt(msg)


class FailingCleanupStore(FailingOpenStore):
    def _close(self) -> None:
        msg = "cannot close"
        raise ValueError(msg)


class FailingCloseStore(DictStore):
    def _close(self) -> None:
        msg = "cannot close yet"
        raise RuntimeError(msg)


class ListIteratorStore(DictStore):
    r"""Return an iterator that has no ``close`` method."""

    def _iter_batches(self, batch_size: int) -> Iterator[dict[str, Payload]]:
        del batch_size
        return iter([dict(self.data)])


class CandidatesStore(DictStore):
    r"""Record the fields given to ``_filter_candidates``."""

    def _filter_candidates(self, fields: Mapping[str, Any]) -> Iterator[dict[str, Payload]]:
        self.record("filter_candidates", dict(fields))
        yield dict(self.data)


class NativeAsyncStore(DictStore):
    r"""Replace some async primitives, as a backend with a native async
    driver does."""

    async def _aget_many(self, keys: list[str]) -> dict[str, Payload]:
        self.record("aget_many", keys)
        return {"1": '{"native": true}'}

    async def _aiter_batches(self, batch_size: int) -> AsyncGenerator[dict[str, Payload]]:
        self.record("aiter_batches", batch_size)
        yield {"1": '{"native": true}'}

    async def _aiter_key_batches(self, batch_size: int) -> AsyncGenerator[list[str]]:
        self.record("aiter_key_batches", batch_size)
        yield ["1"]

    async def _afilter_candidates(
        self, fields: Mapping[str, Any]
    ) -> AsyncGenerator[dict[str, Payload]]:
        self.record("afilter_candidates", dict(fields))
        yield {"1": '{"native": true}', "2": '{"native": false}'}

    async def _aclose(self) -> None:
        self.record("aclose")


class GuardedStore(DictStore):
    r"""Refuse to be closed while ``busy`` is set."""

    busy = True

    def _check_close(self) -> None:
        self.record("check_close")
        if self.busy:
            msg = "still busy"
            raise RuntimeError(msg)


class CloseInLoopStore(DictStore):
    r"""Close the store in the event loop."""

    _close_in_event_loop = True


class KeysOnlyStore(DictStore):
    r"""List the keys without reading the values."""

    def _iter_key_batches(self, batch_size: int) -> Iterator[list[str]]:
        self.record("iter_key_batches", batch_size)
        yield ["only", "keys"]


class NoCountStore(BaseStore):
    r"""Implement every primitive but ``_count``."""

    to_uri = DictStore.to_uri
    from_uri = DictStore.from_uri
    _open = DictStore._open
    _close = DictStore._close
    _get_many = DictStore._get_many
    _put_many = DictStore._put_many
    _update = DictStore._update
    _delete_many = DictStore._delete_many
    _clear = DictStore._clear
    _iter_batches = DictStore._iter_batches


class NoURIStore(BaseStore):
    r"""Implement the primitives but not the URI methods."""

    _open = DictStore._open
    _close = DictStore._close
    _get_many = DictStore._get_many
    _put_many = DictStore._put_many
    _update = DictStore._update
    _delete_many = DictStore._delete_many
    _clear = DictStore._clear
    _count = DictStore._count
    _iter_batches = DictStore._iter_batches


def open_store(cls: type[DictStore] = DictStore, **kwargs: Any) -> DictStore:
    r"""Create an open store with three values, and forget the calls
    made so far."""
    store = cls(**kwargs)
    store.open()
    store.set_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    store.calls.clear()
    store.lock_held.clear()
    store.threads.clear()
    store.contexts.clear()
    return store


@pytest.fixture
def store() -> Iterator[DictStore]:
    store = open_store()
    yield store
    store.close()


async def collect(iterator: Any) -> list[Any]:
    r"""Return the items of an async iterator."""
    return [item async for item in iterator]


# Every operation of a store, with an empty input where it takes one.
SYNC_OPERATIONS: list[Any] = [
    pytest.param(lambda s: s.get("1"), id="get"),
    pytest.param(lambda s: s.get_many([]), id="get_many"),
    pytest.param(lambda s: s.set("1", {}), id="set"),
    pytest.param(lambda s: s.set_many({}), id="set_many"),
    pytest.param(lambda s: s.set_batches([]), id="set_batches"),
    pytest.param(lambda s: s.delete("1"), id="delete"),
    pytest.param(lambda s: s.delete_many([]), id="delete_many"),
    pytest.param(lambda s: s.clear(), id="clear"),
    pytest.param(lambda s: s.contains("1"), id="contains"),
    pytest.param(lambda s: s.contains_many([]), id="contains_many"),
    pytest.param(lambda s: s.filter(), id="filter"),
    pytest.param(lambda s: list(s.keys()), id="keys"),
    pytest.param(lambda s: list(s.values()), id="values"),
    pytest.param(lambda s: list(s.iter_batches()), id="iter_batches"),
    pytest.param(lambda s: s.count(), id="count"),
]

ASYNC_OPERATIONS: list[Any] = [
    pytest.param(lambda s: s.aget("1"), id="aget"),
    pytest.param(lambda s: s.aget_many([]), id="aget_many"),
    pytest.param(lambda s: s.aset("1", {}), id="aset"),
    pytest.param(lambda s: s.aset_many({}), id="aset_many"),
    pytest.param(lambda s: s.aset_batches([]), id="aset_batches"),
    pytest.param(lambda s: s.adelete("1"), id="adelete"),
    pytest.param(lambda s: s.adelete_many([]), id="adelete_many"),
    pytest.param(lambda s: s.aclear(), id="aclear"),
    pytest.param(lambda s: s.acontains("1"), id="acontains"),
    pytest.param(lambda s: s.acontains_many([]), id="acontains_many"),
    pytest.param(lambda s: s.afilter(), id="afilter"),
    pytest.param(lambda s: collect(s.akeys()), id="akeys"),
    pytest.param(lambda s: collect(s.avalues()), id="avalues"),
    pytest.param(lambda s: collect(s.aiter_batches()), id="aiter_batches"),
    pytest.param(lambda s: s.acount(), id="acount"),
]

# Every operation that takes keys, called with a key that is not a str.
SYNC_INT_KEY_OPERATIONS: list[Any] = [
    pytest.param(lambda s: s.get(1), id="get"),
    pytest.param(lambda s: s.get_many(["1", 1]), id="get_many"),
    pytest.param(lambda s: s.set(1, {}), id="set"),
    pytest.param(lambda s: s.set_many({"4": {}, 1: {}}), id="set_many"),
    pytest.param(lambda s: s.set_batches([(1, {})]), id="set_batches"),
    pytest.param(lambda s: s.delete(1), id="delete"),
    pytest.param(lambda s: s.delete_many(["1", 1]), id="delete_many"),
    pytest.param(lambda s: s.contains(1), id="contains"),
    pytest.param(lambda s: s.contains_many(["1", 1]), id="contains_many"),
]

ASYNC_INT_KEY_OPERATIONS: list[Any] = [
    pytest.param(lambda s: s.aget(1), id="aget"),
    pytest.param(lambda s: s.aget_many(["1", 1]), id="aget_many"),
    pytest.param(lambda s: s.aset(1, {}), id="aset"),
    pytest.param(lambda s: s.aset_many({"4": {}, 1: {}}), id="aset_many"),
    pytest.param(lambda s: s.aset_batches([(1, {})]), id="aset_batches"),
    pytest.param(lambda s: s.adelete(1), id="adelete"),
    pytest.param(lambda s: s.adelete_many(["1", 1]), id="adelete_many"),
    pytest.param(lambda s: s.acontains(1), id="acontains"),
    pytest.param(lambda s: s.acontains_many(["1", 1]), id="acontains_many"),
]


###############################
#     Tests for BaseStore     #
###############################


def test_base_store_is_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        BaseStore()


def test_base_store_is_abstract_missing_primitive() -> None:
    with pytest.raises(TypeError, match=r"abstract.*_count"):
        NoCountStore()


def test_base_store_is_abstract_missing_to_uri_from_uri() -> None:
    with pytest.raises(TypeError, match=r"abstract.*from_uri"):
        NoURIStore()


def test_base_store_default_codec() -> None:
    assert isinstance(DictStore()._codec, JsonCodec)


def test_base_store_custom_codec() -> None:
    codec = PickleCodec()
    assert DictStore(codec=codec)._codec is codec


def test_base_store_codec_is_keyword_only() -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        BaseStore.__init__(DictStore.__new__(DictStore), PickleCodec())


def test_base_store_constructor_does_not_open() -> None:
    assert DictStore().calls == []


# --- open / close ---


def test_base_store_closed_before_open() -> None:
    assert DictStore().closed


def test_base_store_open() -> None:
    store = DictStore()
    store.open()
    assert not store.closed


def test_base_store_open_is_idempotent() -> None:
    store = DictStore()
    store.open()
    store.open()
    assert store.calls == [("open",)]


def test_base_store_close() -> None:
    store = DictStore()
    store.open()
    store.close()
    assert store.closed


def test_base_store_close_is_idempotent() -> None:
    store = DictStore()
    store.open()
    store.close()
    store.close()
    assert store.calls == [("open",), ("close",)]


def test_base_store_close_before_open_does_not_call_close_primitive() -> None:
    store = DictStore()
    store.close()
    assert store.calls == []


def test_base_store_reopen() -> None:
    store = DictStore()
    store.open()
    store.close()
    store.open()
    assert not store.closed


def test_base_store_open_and_close_hold_lock() -> None:
    store = DictStore()
    store.open()
    store.close()
    assert store.lock_held == [True, True]


def test_base_store_open_failure_stays_closed() -> None:
    store = FailingOpenStore()
    with pytest.raises(ConnectionError, match=r"cannot connect"):
        store.open()
    assert store.closed


def test_base_store_open_failure_calls_close_primitive() -> None:
    store = FailingOpenStore()
    with pytest.raises(ConnectionError, match=r"cannot connect"):
        store.open()
    assert store.calls == [("close",)]


def test_base_store_open_interrupted_calls_close_primitive() -> None:
    store = InterruptedOpenStore()
    with pytest.raises(KeyboardInterrupt, match=r"interrupted"):
        store.open()
    assert store.calls == [("close",)]


def test_base_store_open_failure_keeps_error_when_close_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = FailingCleanupStore()
    with pytest.raises(ConnectionError, match=r"cannot connect"):
        store.open()
    assert "Could not close FailingCleanupStore" in caplog.text


def test_base_store_close_failure_stays_open() -> None:
    store = FailingCloseStore()
    store.open()
    with pytest.raises(RuntimeError, match=r"cannot close yet"):
        store.close()
    assert not store.closed


async def test_base_store_aopen() -> None:
    store = DictStore()
    await store.aopen()
    assert not store.closed
    await store.aclose()


async def test_base_store_aopen_is_idempotent() -> None:
    store = DictStore()
    await store.aopen()
    await store.aopen()
    assert store.calls == [("open",)]
    await store.aclose()


async def test_base_store_aopen_open_store_starts_no_thread() -> None:
    store = DictStore()
    store.open()
    await store.aopen()
    assert store._executor is None


async def test_base_store_aopen_runs_in_worker_thread() -> None:
    store = DictStore()
    await store.aopen()
    assert store.threads[0].startswith("persista-DictStore")
    await store.aclose()


async def test_base_store_aopen_failure_calls_close_primitive() -> None:
    store = FailingOpenStore()
    with pytest.raises(ConnectionError, match=r"cannot connect"):
        await store.aopen()
    assert store.calls == [("close",)]


async def test_base_store_aopen_failure_stops_worker_thread() -> None:
    store = FailingOpenStore()
    with pytest.raises(ConnectionError, match=r"cannot connect"):
        await store.aopen()
    assert store._executor is None


async def test_base_store_aclose() -> None:
    store = DictStore()
    await store.aopen()
    await store.aclose()
    assert store.closed


async def test_base_store_aclose_stops_worker_thread() -> None:
    store = DictStore()
    await store.aopen()
    await store.aclose()
    assert store._executor is None


async def test_base_store_aclose_closed_store_calls_nothing() -> None:
    store = NativeAsyncStore()
    await store.aclose()
    assert store.calls == []


async def test_base_store_aclose_closed_store_starts_no_thread() -> None:
    store = DictStore()
    await store.aclose()
    assert store._executor is None


async def test_base_store_aclose_releases_async_resources_first() -> None:
    store = open_store(NativeAsyncStore)
    await store.aclose()
    assert store.calls == [("aclose",), ("close",)]


async def test_base_store_aclose_failure_stays_open() -> None:
    store = FailingCloseStore()
    await store.aopen()
    with pytest.raises(RuntimeError, match=r"cannot close yet"):
        await store.aclose()
    assert not store.closed


def test_base_store_close_stops_worker_thread(store: DictStore) -> None:
    store._executor = executor = FakeExecutor()
    store.close()
    assert executor.shutdowns == [False]


class FakeExecutor:
    r"""Record the calls to ``shutdown``."""

    def __init__(self) -> None:
        self.shutdowns: list[bool] = []

    def shutdown(self, wait: bool = True) -> None:
        self.shutdowns.append(wait)


# --- _check_close ---


def test_base_store_check_close_default(store: DictStore) -> None:
    store._check_close()
    assert not store.closed


def test_base_store_close_checks_before_it_closes() -> None:
    store = GuardedStore()
    store.busy = False
    with store:
        store.calls.clear()
    assert store.calls == [("check_close",), ("close",)]


def test_base_store_close_check_failure_stays_open() -> None:
    store = GuardedStore()
    store.open()
    store.calls.clear()
    with pytest.raises(RuntimeError, match=r"still busy"):
        store.close()
    assert (store.closed, store.calls) == (False, [("check_close",)])


def test_base_store_close_closed_store_does_not_check() -> None:
    store = GuardedStore()
    store.close()
    assert store.calls == []


def test_base_store_open_failure_does_not_check_close() -> None:
    class FailingGuardedStore(GuardedStore):
        def _open(self) -> None:
            msg = "cannot connect"
            raise ConnectionError(msg)

    store = FailingGuardedStore()
    with pytest.raises(ConnectionError, match=r"cannot connect"):
        store.open()
    assert store.calls == [("close",)]


async def test_base_store_aclose_runs_close_in_worker_thread() -> None:
    store = DictStore()
    await store.aopen()
    await store.aclose()
    assert store.threads[-1].startswith("persista-DictStore")


async def test_base_store_aclose_in_event_loop() -> None:
    store = CloseInLoopStore()
    await store.aopen()
    await store.aclose()
    assert (store.closed, store.threads[-1], store._executor) == (
        True,
        threading.current_thread().name,
        None,
    )


# --- context managers ---


def test_base_store_sync_context_manager_calls_open_and_close() -> None:
    with DictStore() as store:
        assert not store.closed
    assert store.closed


async def test_base_store_async_context_manager_calls_aopen_and_aclose() -> None:
    async with DictStore() as store:
        assert not store.closed
    assert store.closed


# --- closed store ---


@pytest.mark.parametrize("operation", SYNC_OPERATIONS)
def test_base_store_closed_store_raises(operation: Callable[[BaseStore], Any]) -> None:
    store = DictStore()
    with pytest.raises(RuntimeError, match=r"DictStore is not open"):
        operation(store)
    assert store.calls == []


@pytest.mark.parametrize("operation", ASYNC_OPERATIONS)
async def test_base_store_closed_store_raises_async(
    operation: Callable[[BaseStore], Any],
) -> None:
    store = DictStore()
    with pytest.raises(RuntimeError, match=r"DictStore is not open"):
        await operation(store)
    assert store.calls == []


# --- keys validation ---


@pytest.mark.parametrize("operation", SYNC_INT_KEY_OPERATIONS)
def test_base_store_non_str_key_raises(
    store: DictStore, operation: Callable[[BaseStore], Any]
) -> None:
    with pytest.raises(TypeError, match=r"A key must be a str, not int"):
        operation(store)
    assert store.calls == []


@pytest.mark.parametrize("operation", ASYNC_INT_KEY_OPERATIONS)
async def test_base_store_non_str_key_raises_async(
    store: DictStore, operation: Callable[[BaseStore], Any]
) -> None:
    with pytest.raises(TypeError, match=r"A key must be a str, not int"):
        await operation(store)
    assert store.calls == []


# --- empty inputs ---


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s: s.get_many([]), id="get_many"),
        pytest.param(lambda s: s.set_many({}), id="set_many"),
        pytest.param(lambda s: s.set_many({}, on_conflict="raise"), id="set_many_raise"),
        pytest.param(lambda s: s.set_batches([]), id="set_batches"),
        pytest.param(lambda s: s.delete_many([]), id="delete_many"),
        pytest.param(lambda s: s.contains_many([]), id="contains_many"),
    ],
)
def test_base_store_empty_input_does_not_call_backend(
    store: DictStore, operation: Callable[[BaseStore], Any]
) -> None:
    operation(store)
    assert store.calls == []


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s: s.aget_many([]), id="aget_many"),
        pytest.param(lambda s: s.aset_many({}), id="aset_many"),
        pytest.param(lambda s: s.aset_many({}, on_conflict="raise"), id="aset_many_raise"),
        pytest.param(lambda s: s.aset_batches([]), id="aset_batches"),
        pytest.param(lambda s: s.adelete_many([]), id="adelete_many"),
        pytest.param(lambda s: s.acontains_many([]), id="acontains_many"),
    ],
)
async def test_base_store_empty_input_does_not_call_backend_async(
    store: DictStore, operation: Callable[[BaseStore], Any]
) -> None:
    await operation(store)
    assert store.calls == []


def test_base_store_get_many_empty(store: DictStore) -> None:
    assert store.get_many([]) == []


def test_base_store_contains_many_empty(store: DictStore) -> None:
    assert store.contains_many([]) == []


async def test_base_store_aget_many_empty(store: DictStore) -> None:
    assert await store.aget_many([]) == []


async def test_base_store_acontains_many_empty(store: DictStore) -> None:
    assert await store.acontains_many([]) == []


# --- on_conflict validation ---


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s: s.set("1", {}, on_conflict="bogus"), id="set"),
        pytest.param(lambda s: s.set_many({}, on_conflict="bogus"), id="set_many"),
        pytest.param(lambda s: s.set_batches([], on_conflict="bogus"), id="set_batches"),
    ],
)
def test_base_store_invalid_on_conflict_raises(
    store: DictStore, operation: Callable[[BaseStore], Any]
) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        operation(store)
    assert store.calls == []


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s: s.aset("1", {}, on_conflict="bogus"), id="aset"),
        pytest.param(lambda s: s.aset_many({}, on_conflict="bogus"), id="aset_many"),
        pytest.param(lambda s: s.aset_batches([], on_conflict="bogus"), id="aset_batches"),
    ],
)
async def test_base_store_invalid_on_conflict_raises_async(
    store: DictStore, operation: Callable[[BaseStore], Any]
) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await operation(store)
    assert store.calls == []


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s: s.set("1", {}, "skip"), id="set"),
        pytest.param(lambda s: s.set_many({}, "skip"), id="set_many"),
        pytest.param(lambda s: s.set_batches([], 32, "skip"), id="set_batches"),
        pytest.param(lambda s: s.aset("1", {}, "skip"), id="aset"),
        pytest.param(lambda s: s.aset_many({}, "skip"), id="aset_many"),
        pytest.param(lambda s: s.aset_batches([], 32, "skip"), id="aset_batches"),
    ],
)
def test_base_store_on_conflict_is_keyword_only(
    store: DictStore, operation: Callable[[BaseStore], Any]
) -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        operation(store)


# --- batch_size validation ---


@pytest.mark.parametrize("batch_size", [0, -1])
@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s, n: s.set_batches([], batch_size=n), id="set_batches"),
        pytest.param(lambda s, n: list(s.values(batch_size=n)), id="values"),
        pytest.param(lambda s, n: list(s.iter_batches(batch_size=n)), id="iter_batches"),
    ],
)
def test_base_store_invalid_batch_size_raises(
    store: DictStore, operation: Callable[[BaseStore, int], Any], batch_size: int
) -> None:
    with pytest.raises(ValueError, match=r"batch_size must be a positive integer"):
        operation(store, batch_size)
    assert store.calls == []


@pytest.mark.parametrize("batch_size", [0, -1])
@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s, n: s.aset_batches([], batch_size=n), id="aset_batches"),
        pytest.param(lambda s, n: collect(s.avalues(batch_size=n)), id="avalues"),
        pytest.param(lambda s, n: collect(s.aiter_batches(batch_size=n)), id="aiter_batches"),
    ],
)
async def test_base_store_invalid_batch_size_raises_async(
    store: DictStore, operation: Callable[[BaseStore, int], Any], batch_size: int
) -> None:
    with pytest.raises(ValueError, match=r"batch_size must be a positive integer"):
        await operation(store, batch_size)
    assert store.calls == []


# --- get / get_many ---


def test_base_store_get(store: DictStore) -> None:
    assert store.get("1") == {"a": 1}


def test_base_store_get_calls_primitive(store: DictStore) -> None:
    store.get("1")
    assert store.calls == [("get_many", ["1"])]


def test_base_store_get_missing(store: DictStore) -> None:
    assert store.get("missing") is None


def test_base_store_get_returns_new_object(store: DictStore) -> None:
    store.get("1")["a"] = 10
    assert store.get("1") == {"a": 1}


async def test_base_store_aget(store: DictStore) -> None:
    assert await store.aget("1") == {"a": 1}


async def test_base_store_aget_missing(store: DictStore) -> None:
    assert await store.aget("missing") is None


def test_base_store_get_many(store: DictStore) -> None:
    assert store.get_many(["2", "missing", "1"]) == [{"a": 2}, None, {"a": 1}]


def test_base_store_get_many_duplicate_keys_are_independent(store: DictStore) -> None:
    first, second = store.get_many(["1", "1"])
    first["a"] = 10
    assert second == {"a": 1}


def test_base_store_get_many_accepts_any_iterable(store: DictStore) -> None:
    assert store.get_many(key for key in ["1", "2"]) == [{"a": 1}, {"a": 2}]


async def test_base_store_aget_many(store: DictStore) -> None:
    assert await store.aget_many(["2", "missing", "1"]) == [{"a": 2}, None, {"a": 1}]


def test_base_store_get_many_single_str_raises(store: DictStore) -> None:
    with pytest.raises(TypeError, match=r"not a single str"):
        store.get_many("12")


# --- set / set_many ---


def test_base_store_set_writes_payload(store: DictStore) -> None:
    store.set("4", {"point": (1, 2)})
    assert store.data["4"] == '{"point": [1, 2]}'


def test_base_store_set_round_trip_uses_codec(store: DictStore) -> None:
    store.set("4", {"point": (1, 2)})
    assert store.get("4") == {"point": [1, 2]}


def test_base_store_set_pickle_codec() -> None:
    store = open_store(codec=PickleCodec())
    store.set("4", {"point": (1, 2)})
    assert store.get("4") == {"point": (1, 2)}


def test_base_store_set_does_not_alias_input(store: DictStore) -> None:
    value = {"tags": ["a"]}
    store.set("4", value)
    value["tags"].append("b")
    assert store.get("4") == {"tags": ["a"]}


@pytest.mark.parametrize("value", [{1: "a"}, {"a": {1, 2}}, ["a"], None])
def test_base_store_set_unsupported_value_raises(store: DictStore, value: Any) -> None:
    with pytest.raises(TypeError, match=r"must be|not JSON serializable"):
        store.set("4", value)
    assert store.calls == []


def test_base_store_set_many_overwrite_uses_put_many(store: DictStore) -> None:
    store.set_many({"4": {"a": 4}, "5": {"a": 5}})
    assert store.calls == [("put_many", {"4": '{"a": 4}', "5": '{"a": 5}'})]


@pytest.mark.parametrize("on_conflict", ["raise", "skip", "merge", " Merge "])
def test_base_store_set_many_conflict_strategy_uses_update(
    store: DictStore, on_conflict: str
) -> None:
    store.set_many({"4": {"a": 4}, "5": {"a": 5}}, on_conflict=on_conflict)
    assert store.calls == [("update", ["4", "5"])]


def test_base_store_set_many_invalid_value_writes_nothing(store: DictStore) -> None:
    with pytest.raises(ValueError, match=r"not JSON compliant"):
        store.set_many({"4": {"a": 4}, "5": {"a": float("nan")}})
    assert store.count() == 3


def test_base_store_set_many_does_not_mutate_items(store: DictStore) -> None:
    items = {"1": {"b": 1}}
    store.set_many(items, on_conflict="merge")
    assert items == {"1": {"b": 1}}


def test_base_store_set_many_raise(store: DictStore) -> None:
    with pytest.raises(KeyError, match=r"already exist.*'1'"):
        store.set_many({"4": {"a": 4}, "1": {"a": 10}}, on_conflict="raise")
    assert store.get_many(["1", "4"]) == [{"a": 1}, None]


def test_base_store_set_many_skip(store: DictStore) -> None:
    store.set_many({"4": {"a": 4}, "1": {"a": 10}}, on_conflict="skip")
    assert store.get_many(["1", "4"]) == [{"a": 1}, {"a": 4}]


def test_base_store_set_many_merge(store: DictStore) -> None:
    store.set_many({"4": {"a": 4}, "1": {"b": 10}}, on_conflict="merge")
    assert store.get_many(["1", "4"]) == [{"a": 1, "b": 10}, {"a": 4}]


async def test_base_store_aset(store: DictStore) -> None:
    await store.aset("4", {"a": 4})
    assert store.get("4") == {"a": 4}


async def test_base_store_aset_many_overwrite_uses_put_many(store: DictStore) -> None:
    await store.aset_many({"4": {"a": 4}})
    assert store.calls == [("put_many", {"4": '{"a": 4}'})]


async def test_base_store_aset_many_raise(store: DictStore) -> None:
    with pytest.raises(KeyError, match=r"already exist"):
        await store.aset_many({"4": {"a": 4}, "1": {"a": 10}}, on_conflict="raise")
    assert store.get_many(["1", "4"]) == [{"a": 1}, None]


async def test_base_store_aset_many_merge(store: DictStore) -> None:
    await store.aset_many({"1": {"b": 10}}, on_conflict="merge")
    assert store.get("1") == {"a": 1, "b": 10}


async def test_base_store_aset_many_invalid_value_writes_nothing(store: DictStore) -> None:
    with pytest.raises(ValueError, match=r"not JSON compliant"):
        await store.aset_many({"4": {"a": 4}, "5": {"a": float("inf")}})
    assert store.count() == 3


# --- set_batches ---


def test_base_store_set_batches(store: DictStore) -> None:
    store.set_batches([("4", {"a": 4}), ("5", {"a": 5}), ("6", {"a": 6})], batch_size=2)
    assert store.calls == [
        ("put_many", {"4": '{"a": 4}', "5": '{"a": 5}'}),
        ("put_many", {"6": '{"a": 6}'}),
    ]


def test_base_store_set_batches_default_batch_size(store: DictStore) -> None:
    store.set_batches((str(i), {}) for i in range(33))
    assert [len(call[1]) for call in store.calls] == [32, 1]


def test_base_store_set_batches_on_conflict(store: DictStore) -> None:
    store.set_batches([("1", {"a": 10}), ("4", {"a": 4})], on_conflict="skip")
    assert store.get_many(["1", "4"]) == [{"a": 1}, {"a": 4}]


def test_base_store_set_batches_raise_keeps_previous_batches(store: DictStore) -> None:
    with pytest.raises(KeyError, match=r"already exist"):
        store.set_batches([("4", {"a": 4}), ("1", {"a": 10})], batch_size=1, on_conflict="raise")
    assert store.get_many(["1", "4"]) == [{"a": 1}, {"a": 4}]


async def test_base_store_aset_batches(store: DictStore) -> None:
    await store.aset_batches([("4", {"a": 4}), ("5", {"a": 5})], batch_size=1)
    assert store.calls == [
        ("put_many", {"4": '{"a": 4}'}),
        ("put_many", {"5": '{"a": 5}'}),
    ]


async def test_base_store_aset_batches_default_batch_size(store: DictStore) -> None:
    await store.aset_batches((str(i), {}) for i in range(33))
    assert [len(call[1]) for call in store.calls] == [32, 1]


async def test_base_store_aset_batches_on_conflict(store: DictStore) -> None:
    await store.aset_batches([("1", {"b": 10})], on_conflict="merge")
    assert store.get("1") == {"a": 1, "b": 10}


# --- delete / clear / count / contains ---


def test_base_store_delete(store: DictStore) -> None:
    store.delete("1")
    assert store.calls == [("delete_many", ["1"])]


async def test_base_store_adelete(store: DictStore) -> None:
    await store.adelete("1")
    assert store.calls == [("delete_many", ["1"])]


def test_base_store_delete_many(store: DictStore) -> None:
    store.delete_many(["1", "missing", "1"])
    assert sorted(store.data) == ["2", "3"]


async def test_base_store_adelete_many(store: DictStore) -> None:
    await store.adelete_many(["1", "2"])
    assert sorted(store.data) == ["3"]


def test_base_store_clear(store: DictStore) -> None:
    store.clear()
    assert store.data == {}


async def test_base_store_aclear(store: DictStore) -> None:
    await store.aclear()
    assert store.data == {}


def test_base_store_count(store: DictStore) -> None:
    assert store.count() == 3


async def test_base_store_acount(store: DictStore) -> None:
    assert await store.acount() == 3


@pytest.mark.parametrize(("key", "expected"), [("1", True), ("missing", False)])
def test_base_store_contains(store: DictStore, key: str, expected: bool) -> None:
    assert store.contains(key) is expected


@pytest.mark.parametrize(("key", "expected"), [("1", True), ("missing", False)])
async def test_base_store_acontains(store: DictStore, key: str, expected: bool) -> None:
    assert await store.acontains(key) is expected


def test_base_store_contains_many(store: DictStore) -> None:
    assert store.contains_many(["1", "missing", "1"]) == [True, False, True]


async def test_base_store_acontains_many(store: DictStore) -> None:
    assert await store.acontains_many(["1", "missing", "1"]) == [True, False, True]


# --- filter ---


def test_base_store_filter_no_fields(store: DictStore) -> None:
    assert store.filter() == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_base_store_filter(store: DictStore) -> None:
    assert store.filter(a=2) == [{"a": 2}]


def test_base_store_filter_several_fields(store: DictStore) -> None:
    store.set_many({"4": {"a": 1, "b": 1}, "5": {"a": 1, "b": 2}})
    assert store.filter(a=1, b=2) == [{"a": 1, "b": 2}]


def test_base_store_filter_none_matches_null_and_absent(store: DictStore) -> None:
    store.set_many({"4": {"b": None}, "5": {"b": 1}})
    assert store.filter(b=None, a=None) == [{"b": None}]


def test_base_store_filter_compares_decoded_values(store: DictStore) -> None:
    store.set("4", {"tags": ("x",)})
    assert store.filter(tags=["x"]) == [{"tags": ["x"]}]


def test_base_store_filter_reads_in_batches(store: DictStore) -> None:
    store.filter(a=1)
    assert store.calls == [("iter_batches", 256)]


def test_base_store_filter_applies_filter_to_candidates() -> None:
    store = open_store(CandidatesStore)
    assert store.filter(a=3) == [{"a": 3}]


def test_base_store_filter_gives_fields_to_candidates() -> None:
    store = open_store(CandidatesStore)
    store.filter(a=3)
    assert store.calls == [("filter_candidates", {"a": 3})]


async def test_base_store_afilter(store: DictStore) -> None:
    assert await store.afilter(a=2) == [{"a": 2}]


async def test_base_store_afilter_applies_filter_to_candidates() -> None:
    store = open_store(CandidatesStore)
    assert await store.afilter(a=3) == [{"a": 3}]
    await store.aclose()


# --- iteration ---


def test_base_store_keys(store: DictStore) -> None:
    assert list(store.keys()) == ["1", "2", "3"]


async def test_base_store_akeys(store: DictStore) -> None:
    assert await collect(store.akeys()) == ["1", "2", "3"]


def test_base_store_keys_uses_key_primitive() -> None:
    store = open_store(KeysOnlyStore)
    assert list(store.keys()) == ["only", "keys"]


async def test_base_store_akeys_uses_key_primitive() -> None:
    store = open_store(KeysOnlyStore)
    assert await collect(store.akeys()) == ["only", "keys"]


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s: list(s.iter_batches()), id="iter_batches"),
        pytest.param(lambda s: s.filter(), id="filter"),
    ],
)
def test_base_store_values_are_not_read_with_key_primitive(
    operation: Callable[[BaseStore], Any],
) -> None:
    store = open_store(KeysOnlyStore)
    operation(store)
    assert [call[0] for call in store.calls] == ["iter_batches"]


def test_base_store_iter_batches(store: DictStore) -> None:
    assert list(store.iter_batches(batch_size=2)) == [
        {"1": {"a": 1}, "2": {"a": 2}},
        {"3": {"a": 3}},
    ]


async def test_base_store_aiter_batches(store: DictStore) -> None:
    assert await collect(store.aiter_batches(batch_size=2)) == [
        {"1": {"a": 1}, "2": {"a": 2}},
        {"3": {"a": 3}},
    ]


def test_base_store_values(store: DictStore) -> None:
    assert list(store.values(batch_size=2)) == [{"a": 1}, {"a": 2}, {"a": 3}]


async def test_base_store_avalues(store: DictStore) -> None:
    assert await collect(store.avalues(batch_size=2)) == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_base_store_values_returns_new_objects(store: DictStore) -> None:
    for value in store.values():
        value["a"] = 10
    assert store.get("1") == {"a": 1}


def test_base_store_iteration_releases_lock_between_batches(store: DictStore) -> None:
    held = [store._lock._is_owned() for _ in store.iter_batches(batch_size=1)]
    assert held == [False, False, False]


def test_base_store_iteration_holds_lock_while_reading(store: DictStore) -> None:
    list(store.iter_batches(batch_size=1))
    assert store.lock_held == [True, True, True]


async def test_base_store_aiteration_releases_lock_between_batches(store: DictStore) -> None:
    held = [store._lock._is_owned() async for _ in store.aiter_batches(batch_size=1)]
    assert held == [False, False, False]


@pytest.mark.parametrize(
    "iterate",
    [
        pytest.param(lambda s: s.iter_batches(batch_size=1), id="iter_batches"),
        pytest.param(lambda s: s.keys(), id="keys"),
        pytest.param(lambda s: s.values(batch_size=1), id="values"),
    ],
)
def test_base_store_stopped_iteration_closes_backend_iterator(
    store: DictStore, iterate: Callable[[BaseStore], Any]
) -> None:
    iterator = iterate(store)
    next(iterator)
    iterator.close()
    assert store.closed_iterators == 1


@pytest.mark.parametrize(
    "iterate",
    [
        pytest.param(lambda s: s.aiter_batches(batch_size=1), id="aiter_batches"),
        pytest.param(lambda s: s.akeys(), id="akeys"),
    ],
)
async def test_base_store_stopped_aiteration_closes_backend_iterator(
    store: DictStore, iterate: Callable[[BaseStore], Any]
) -> None:
    iterator = iterate(store)
    await anext(iterator)
    await iterator.aclose()
    assert store.closed_iterators == 1


def test_base_store_close_during_iteration_raises(store: DictStore) -> None:
    iterator = store.iter_batches(batch_size=1)
    next(iterator)
    store.close()
    with pytest.raises(RuntimeError, match=r"not open"):
        next(iterator)
    assert store.closed_iterators == 1


async def test_base_store_close_during_aiteration_raises(store: DictStore) -> None:
    iterator = store.aiter_batches(batch_size=1)
    await anext(iterator)
    await store.aclose()
    with pytest.raises(RuntimeError, match=r"not open"):
        await anext(iterator)
    assert store.closed_iterators == 1


async def test_base_store_stop_aiteration_of_closed_store_starts_no_thread(
    store: DictStore,
) -> None:
    iterator = store.aiter_batches(batch_size=1)
    await anext(iterator)
    await store.aclose()
    await iterator.aclose()
    assert store._executor is None


def test_base_store_iteration_of_iterator_without_close() -> None:
    store = open_store(ListIteratorStore)
    assert list(store.keys()) == ["1", "2", "3"]


# --- locks and threads ---


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s: s.get("1"), id="get"),
        pytest.param(lambda s: s.set("1", {}), id="put_many"),
        pytest.param(lambda s: s.set("1", {}, on_conflict="skip"), id="update"),
        pytest.param(lambda s: s.delete("1"), id="delete_many"),
        pytest.param(lambda s: s.clear(), id="clear"),
        pytest.param(lambda s: s.count(), id="count"),
        pytest.param(lambda s: s.contains("1"), id="contains_many"),
    ],
)
def test_base_store_primitive_holds_lock(
    store: DictStore, operation: Callable[[BaseStore], Any]
) -> None:
    operation(store)
    assert store.lock_held == [True]


def test_base_store_thread_safe_primitive_does_not_hold_lock() -> None:
    store = open_store(ThreadSafeStore)
    store.get("1")
    assert store.lock_held == [False]


ASYNC_PRIMITIVE_OPERATIONS: list[Any] = [
    pytest.param(lambda s: s.aget("1"), id="get_many"),
    pytest.param(lambda s: s.aset("1", {}), id="put_many"),
    pytest.param(lambda s: s.aset("1", {}, on_conflict="skip"), id="update"),
    pytest.param(lambda s: s.adelete("1"), id="delete_many"),
    pytest.param(lambda s: s.aclear(), id="clear"),
    pytest.param(lambda s: s.acount(), id="count"),
    pytest.param(lambda s: s.acontains("1"), id="contains_many"),
    pytest.param(lambda s: collect(s.aiter_batches()), id="iter_batches"),
    pytest.param(lambda s: s.afilter(), id="filter_candidates"),
]


@pytest.mark.parametrize("operation", ASYNC_PRIMITIVE_OPERATIONS)
async def test_base_store_async_primitive_runs_in_worker_thread(
    store: DictStore, operation: Callable[[BaseStore], Any]
) -> None:
    await operation(store)
    assert store.threads[0].startswith("persista-DictStore")


@pytest.mark.parametrize("operation", ASYNC_PRIMITIVE_OPERATIONS)
async def test_base_store_async_primitive_holds_lock(
    store: DictStore, operation: Callable[[BaseStore], Any]
) -> None:
    await operation(store)
    assert store.lock_held == [True]


@pytest.mark.parametrize("operation", ASYNC_PRIMITIVE_OPERATIONS)
async def test_base_store_thread_safe_async_primitive_runs_in_default_executor(
    operation: Callable[[BaseStore], Any],
) -> None:
    store = open_store(ThreadSafeStore)
    await operation(store)
    assert store.threads[0].startswith("asyncio_")


@pytest.mark.parametrize("operation", ASYNC_PRIMITIVE_OPERATIONS)
async def test_base_store_thread_safe_async_primitive_does_not_hold_lock(
    operation: Callable[[BaseStore], Any],
) -> None:
    store = open_store(ThreadSafeStore)
    await operation(store)
    assert store.lock_held == [False]


async def test_base_store_async_calls_share_one_worker_thread(store: DictStore) -> None:
    await store.aget("1")
    await store.acount()
    assert store.threads[0] == store.threads[1]


async def test_base_store_async_primitive_sees_context(store: DictStore) -> None:
    token = CONTEXT.set("caller")
    try:
        await store.aget("1")
    finally:
        CONTEXT.reset(token)
    assert store.contexts == ["caller"]


async def test_base_store_thread_safe_store_has_no_worker_thread() -> None:
    store = open_store(ThreadSafeStore)
    await store.aget("1")
    assert store._executor is None


async def test_base_store_async_after_reopen(store: DictStore) -> None:
    await store.aget("1")
    await store.aclose()
    await store.aopen()
    assert await store.aget("1") == {"a": 1}


# --- async primitives replaced by a backend ---


async def test_base_store_aget_uses_native_primitive() -> None:
    store = open_store(NativeAsyncStore)
    assert await store.aget("1") == {"native": True}


async def test_base_store_aget_many_uses_native_primitive() -> None:
    store = open_store(NativeAsyncStore)
    assert await store.aget_many(["1", "2"]) == [{"native": True}, None]


@pytest.mark.parametrize(
    "iterate",
    [
        pytest.param(lambda s: s.aiter_batches(), id="aiter_batches"),
        pytest.param(lambda s: s.avalues(), id="avalues"),
    ],
)
async def test_base_store_aiteration_uses_native_primitive(
    iterate: Callable[[BaseStore], Any],
) -> None:
    store = open_store(NativeAsyncStore)
    await collect(iterate(store))
    assert store.calls[0][0] == "aiter_batches"


async def test_base_store_akeys_uses_native_primitive() -> None:
    store = open_store(NativeAsyncStore)
    assert await collect(store.akeys()) == ["1"]


async def test_base_store_afilter_uses_native_primitive() -> None:
    store = open_store(NativeAsyncStore)
    assert await store.afilter(native=True) == [{"native": True}]


# --- default primitives ---


def test_base_store__contains_many(store: DictStore) -> None:
    assert store._contains_many(["1", "missing", "1"]) == {"1"}


def test_base_store__filter_candidates_yields_every_value(store: DictStore) -> None:
    assert list(store._filter_candidates({"a": 1})) == [store.data]


@pytest.mark.parametrize(
    ("batch_size", "expected"), [(2, [["1", "2"], ["3"]]), (3, [["1", "2", "3"]])]
)
def test_base_store__iter_key_batches(
    store: DictStore, batch_size: int, expected: list[list[str]]
) -> None:
    assert list(store._iter_key_batches(batch_size)) == expected


def test_base_store__iter_key_batches_empty_store() -> None:
    with DictStore() as store:
        assert list(store._iter_key_batches(2)) == []


def test_base_store__iter_key_batches_closes_backend_iterator(store: DictStore) -> None:
    iterator = store._iter_key_batches(1)
    next(iterator)
    iterator.close()
    assert store.closed_iterators == 1


def test_base_store__iter_key_batches_of_iterator_without_close() -> None:
    store = open_store(ListIteratorStore)
    assert list(store._iter_key_batches(5)) == [["1", "2", "3"]]


async def test_base_store__aiter_key_batches(store: DictStore) -> None:
    assert await collect(store._aiter_key_batches(2)) == [["1", "2"], ["3"]]


async def test_base_store__aget_many(store: DictStore) -> None:
    assert await store._aget_many(["1", "missing"]) == {"1": '{"a": 1}'}


async def test_base_store__aput_many(store: DictStore) -> None:
    await store._aput_many({"4": '{"a": 4}'})
    assert store.data["4"] == '{"a": 4}'


async def test_base_store__aupdate(store: DictStore) -> None:
    await store._aupdate(["1", "4"], lambda existing: {"4": existing["1"]})
    assert store.data["4"] == '{"a": 1}'


async def test_base_store__adelete_many(store: DictStore) -> None:
    await store._adelete_many(["1", "2"])
    assert sorted(store.data) == ["3"]


async def test_base_store__aclear(store: DictStore) -> None:
    await store._aclear()
    assert store.data == {}


async def test_base_store__acount(store: DictStore) -> None:
    assert await store._acount() == 3


async def test_base_store__acontains_many(store: DictStore) -> None:
    assert await store._acontains_many(["1", "missing"]) == {"1"}


async def test_base_store__aiter_batches(store: DictStore) -> None:
    assert await collect(store._aiter_batches(5)) == [store.data]


async def test_base_store__afilter_candidates(store: DictStore) -> None:
    assert await collect(store._afilter_candidates({"a": 1})) == [store.data]


async def test_base_store__aclose_does_nothing(store: DictStore) -> None:
    await store._aclose()
    assert store.calls == []


# --- template helpers ---


def test_base_store__call(store: DictStore) -> None:
    assert store._call(sorted, store.data) == ["1", "2", "3"]


def test_base_store__call_closed_store_raises() -> None:
    with pytest.raises(RuntimeError, match=r"not open"):
        DictStore()._call(sorted, [])


async def test_base_store__run_in_thread(store: DictStore) -> None:
    assert await store._run_in_thread(sorted, [2, 1]) == [1, 2]


async def test_base_store__run_in_thread_raises_error_of_function(store: DictStore) -> None:
    with pytest.raises(ZeroDivisionError, match=r"division"):
        await store._run_in_thread(divmod, 1, 0)


async def test_base_store__shutdown_executor(store: DictStore) -> None:
    await store._run_in_thread(sorted, [])
    store._shutdown_executor()
    assert store._executor is None


def test_base_store__shutdown_executor_without_executor() -> None:
    store = DictStore()
    store._shutdown_executor()
    assert store._executor is None


def test_base_store__batches(store: DictStore) -> None:
    assert list(store._batches(store._iter_batches, 5)) == [store.data]


async def test_base_store__abatches(store: DictStore) -> None:
    assert await collect(store._abatches(store._iter_batches, 5)) == [store.data]


@pytest.mark.parametrize("iterator_lock", [None, threading.Lock()])
@pytest.mark.parametrize(("batches", "expected"), [([{"1": "{}"}], {"1": "{}"}), ([], None)])
def test_base_store__next_batch(
    batches: list[dict[str, str]], expected: Any, iterator_lock: threading.Lock | None
) -> None:
    assert BaseStore._next_batch(iter(batches), iterator_lock) == expected


@pytest.mark.parametrize("iterator_lock", [None, threading.Lock()])
def test_base_store__close_iterator(store: DictStore, iterator_lock: threading.Lock | None) -> None:
    iterator = store._iter_batches(1)
    next(iterator)
    store._close_iterator(iterator, iterator_lock)
    assert store.closed_iterators == 1


def test_base_store__close_iterator_without_close_method(store: DictStore) -> None:
    iterator = iter([{"1": "{}"}])
    store._close_iterator(iterator)
    assert next(iterator) == {"1": "{}"}


def test_base_store__encode_items(store: DictStore) -> None:
    assert store._encode_items({"1": {"a": 1}}) == {"1": '{"a": 1}'}


def test_base_store__encode_items_empty(store: DictStore) -> None:
    assert store._encode_items({}) == {}


def test_base_store__encode_items_converts_str_subclass_key(store: DictStore) -> None:
    [key] = store._encode_items({StrSubclass("1"): {}})
    assert type(key) is str


def test_base_store__encode_items_same_string_twice_raises(store: DictStore) -> None:
    with pytest.raises(ValueError, match=r"Keys must be different strings"):
        store._encode_items({"1": {}, StrSubclass("1"): {}})


class StrSubclass(str):
    r"""A ``str`` that is only equal to itself."""

    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)


def test_base_store__decode_many(store: DictStore) -> None:
    assert store._decode_many(["1", "2"], {"1": '{"a": 1}'}) == [{"a": 1}, None]


@pytest.mark.parametrize(
    ("value", "fields", "expected"),
    [
        pytest.param({"a": 1, "b": 2}, {"a": 1}, True, id="match"),
        pytest.param({"a": 1}, {}, True, id="no_field"),
        pytest.param({"a": 1}, {"a": 2}, False, id="other_value"),
        pytest.param({"a": 1}, {"a": 1, "b": 2}, False, id="one_field_differs"),
        pytest.param({}, {"a": None}, True, id="missing_is_none"),
    ],
)
def test_base_store__matches(value: dict, fields: dict, expected: bool) -> None:
    assert BaseStore._matches(value, fields) is expected


def test_base_store__matching_values(store: DictStore) -> None:
    batch = {"1": '{"a": 1}', "2": '{"a": 2}', "3": "{}"}
    assert store._matching_values(batch, {"a": 2}) == [{"a": 2}]
