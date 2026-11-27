r"""Contract tests of the stores that implement the primitives of
``BaseStore``: one section per property of the ``persista.store``
package, run for every backend and every codec.

A backend is added to these tests by adding it to ``BACKENDS`` once it
implements the primitives. The behaviour that every backend already
shares is tested in ``test_consistency.py``.

Some properties are not covered yet, because the filter semantics are
not final (``True`` and ``1`` still match, and the SQL stores with a JSON
codec compare in the database, so the filter matrix leaves them out),
and because the listed backends have no limit on their keys and no
credentials. The writes of several instances of the same data are tested
in ``test_sql_concurrency.py``.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import (
    BaseStore,
    DuckDBStore,
    InMemoryStore,
    JsonCodec,
    NullStore,
    PickleCodec,
    SQLiteStore,
)
from persista.testing.fixtures import duckdb_available

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator
    from pathlib import Path

    from persista.store import Codec
    from persista.store.types import Payload, Plan

NUM_THREADS = 8
NUM_WRITES = 50


class PrimitivesOnlyStore(BaseStore):
    r"""A store that implements nothing but the primitives and the URI
    methods, as a custom backend does."""

    def __init__(self, *, codec: Codec | None = None) -> None:
        super().__init__(codec=codec)
        self.data: dict[str, Payload] = {}
        self.closed_iterators = 0

    def to_uri(self) -> str:
        return "primitives://"

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> PrimitivesOnlyStore:
        del uri, read_only
        return cls()

    def _open(self) -> None:
        pass

    def _close(self) -> None:
        pass

    def _get_many(self, keys: list[str]) -> dict[str, Payload]:
        return {key: self.data[key] for key in keys if key in self.data}

    def _put_many(self, items: dict[str, Payload]) -> None:
        self.data.update(items)

    def _update(self, keys: list[str], plan: Plan) -> None:
        self.data.update(plan(self._get_many(keys)))

    def _delete_many(self, keys: list[str]) -> None:
        for key in keys:
            self.data.pop(key, None)

    def _clear(self) -> None:
        self.data.clear()

    def _count(self) -> int:
        return len(self.data)

    def _iter_batches(self, batch_size: int) -> Iterator[dict[str, Payload]]:
        try:
            keys = list(self.data)
            for start in range(0, len(keys), batch_size):
                if batch := self._get_many(keys[start : start + batch_size]):
                    yield batch
        finally:
            self.closed_iterators += 1


class BlockingStore(PrimitivesOnlyStore):
    r"""A store whose reads wait until the test releases them."""

    def __init__(self) -> None:
        super().__init__()
        self.reading = threading.Event()
        self.release = threading.Event()

    def _get_many(self, keys: list[str]) -> dict[str, Payload]:
        self.reading.set()
        self.release.wait(timeout=10)
        return super()._get_many(keys)


# The backends that implement the primitives and keep data. Each factory
# takes the codec and a directory for the data.
BACKENDS: dict[str, Callable[[Codec, Path], BaseStore]] = {
    "in_memory": lambda codec, _path: InMemoryStore(codec=codec),
    "primitives_only": lambda codec, _path: PrimitivesOnlyStore(codec=codec),
    "sqlite": lambda codec, path: SQLiteStore(path / "data.sqlite", codec=codec),
    "sqlite_memory": lambda codec, _path: SQLiteStore(codec=codec),
    "duckdb": lambda codec, path: DuckDBStore(path / "data.duckdb", codec=codec),
    "duckdb_memory": lambda codec, _path: DuckDBStore(codec=codec),
}

# The backends that need an optional library, and the mark that skips them.
MARKS: dict[str, pytest.MarkDecorator] = {
    "duckdb": duckdb_available,
    "duckdb_memory": duckdb_available,
}

# The backends whose data outlives the store.
PERSISTENT = ["sqlite", "duckdb"]

# The backends that apply the filters in SQL with a JSON codec.
SQL_BACKENDS = ["sqlite", "sqlite_memory", "duckdb", "duckdb_memory"]


def backend_params(names: list[str]) -> list[Any]:
    r"""Return one parameter per backend, with the mark of its optional
    library."""
    return [
        pytest.param(name, id=name, marks=[MARKS[name]] if name in MARKS else []) for name in names
    ]


CODECS: dict[str, Callable[[], Codec]] = {"json": JsonCodec, "pickle": PickleCodec}


@pytest.fixture(params=list(CODECS))
def codec(request: pytest.FixtureRequest) -> Codec:
    return CODECS[request.param]()


@pytest.fixture(params=backend_params(list(BACKENDS)))
def unopened_store(request: pytest.FixtureRequest, codec: Codec, tmp_path: Path) -> BaseStore:
    return BACKENDS[request.param](codec, tmp_path)


@pytest.fixture
def store(unopened_store: BaseStore) -> Generator[BaseStore, None, None]:
    with unopened_store as store:
        yield store


@pytest.fixture(params=backend_params([*BACKENDS, "null"]))
def any_store(request: pytest.FixtureRequest, tmp_path: Path) -> BaseStore:
    r"""Return a closed store of every backend, including the one that
    keeps no data."""
    if request.param == "null":
        return NullStore()
    return BACKENDS[request.param](JsonCodec(), tmp_path)


async def collect(iterator: Any) -> list[Any]:
    r"""Return the items of an async iterator."""
    return [item async for item in iterator]


########################
#     Key domain       #
########################

KEYS = [
    "",
    "a",
    "A",
    " a",
    "a ",
    "1",
    "User:1",
    "user:1",
    "a/b",
    "../a",
    "%41",
    "__keys__",
    "é",
    "e" + chr(0x301),
    "🎉",
    "a" + chr(0) + "b",
    "a\nb",
    "x" * 2000,
]


def test_keys_are_compared_exactly(store: BaseStore) -> None:
    store.set_many({key: {"index": i} for i, key in enumerate(KEYS)})
    assert store.get_many(KEYS) == [{"index": i} for i in range(len(KEYS))]


def test_keys_are_listed_exactly(store: BaseStore) -> None:
    store.set_many({key: {} for key in KEYS})
    assert sorted(store.keys()) == sorted(KEYS)


@pytest.mark.parametrize("key", [1, None, b"a", ("a",)])
def test_non_str_key_raises_and_writes_nothing(store: BaseStore, key: object) -> None:
    with pytest.raises(TypeError, match=r"A key must be a str"):
        store.set_many({"a": {}, key: {}})
    assert store.count() == 0


########################
#     Value domain     #
########################


@pytest.mark.parametrize("value", [None, 1, "a", [("a", 1)]])
def test_value_that_is_not_a_dict_raises(store: BaseStore, value: object) -> None:
    with pytest.raises(TypeError, match=r"A value must be a dict"):
        store.set_many({"a": {}, "b": value})
    assert store.count() == 0


@pytest.mark.parametrize(
    ("value", "error", "match"),
    [
        pytest.param({1: "a", "1": "b"}, TypeError, r"keys must be str", id="int_key"),
        pytest.param({"a": [{True: 1}]}, TypeError, r"keys must be str", id="nested_bool_key"),
        pytest.param({"a": float("nan")}, ValueError, r"not JSON compliant", id="nan"),
        pytest.param({"a": float("-inf")}, ValueError, r"not JSON compliant", id="inf"),
        pytest.param({"a": chr(0xD800)}, ValueError, r"lone surrogate", id="surrogate"),
        pytest.param({"a": {1}}, TypeError, r"not JSON serializable", id="set"),
        pytest.param({"a": b"a"}, TypeError, r"not JSON serializable", id="bytes"),
    ],
)
@pytest.mark.parametrize("backend", backend_params(list(BACKENDS)))
def test_json_codec_rejects_value_that_would_lose_data(
    backend: str, tmp_path: Path, value: dict, error: type[Exception], match: str
) -> None:
    with BACKENDS[backend](JsonCodec(), tmp_path) as store:
        with pytest.raises(error, match=match):
            store.set_many({"a": {}, "b": value})
        assert store.count() == 0


######################
#     Round trip     #
######################

VALUES = [
    pytest.param({}, id="empty"),
    pytest.param({"none": None, "true": True, "int": 1, "float": 1.0, "str": "1"}, id="scalars"),
    pytest.param({"point": (1, 2), "nested": [{"a": ()}]}, id="tuples"),
    pytest.param({"big": 2**80, "é": "🎉", "": [[]]}, id="other"),
]


@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize(
    "read",
    [
        pytest.param(lambda s: s.get("a"), id="get"),
        pytest.param(lambda s: s.get_many(["a"])[0], id="get_many"),
        pytest.param(lambda s: s.filter()[0], id="filter"),
        pytest.param(lambda s: next(iter(s.values())), id="values"),
        pytest.param(lambda s: next(iter(s.iter_batches()))["a"], id="iter_batches"),
    ],
)
def test_read_returns_codec_round_trip(
    store: BaseStore, codec: Codec, value: dict, read: Callable[[BaseStore], dict]
) -> None:
    store.set("a", value)
    # repr also compares the types: 1, 1.0 and True, or tuple and list.
    assert repr(read(store)) == repr(codec.decode(codec.encode(value)))


@pytest.mark.parametrize("value", VALUES)
async def test_async_read_returns_codec_round_trip(
    store: BaseStore, codec: Codec, value: dict
) -> None:
    await store.aset("a", value)
    results = [
        await store.aget("a"),
        *await store.aget_many(["a"]),
        *await store.afilter(),
        *await collect(store.avalues()),
    ]
    assert repr(results) == repr([codec.decode(codec.encode(value))] * 4)


def test_pickle_codec_keeps_what_json_cannot_represent(tmp_path: Path) -> None:
    value = {1: {2}, "1": b"a", "nan": float("inf"), "surrogate": chr(0xD800)}
    with BACKENDS["in_memory"](PickleCodec(), tmp_path) as store:
        store.set("a", value)
        assert store.get("a") == value


#####################
#     Isolation     #
#####################


@pytest.mark.parametrize("on_conflict", ["raise", "skip", "overwrite", "merge"])
def test_mutating_a_written_value_does_not_change_the_store(
    store: BaseStore, on_conflict: str
) -> None:
    value = {"tags": ["a"]}
    store.set("a", value, on_conflict=on_conflict)
    value["tags"].append("b")
    assert store.get("a") == {"tags": ["a"]}


@pytest.mark.parametrize(
    "read",
    [
        pytest.param(lambda s: s.get("a"), id="get"),
        pytest.param(lambda s: s.get_many(["a"])[0], id="get_many"),
        pytest.param(lambda s: s.filter()[0], id="filter"),
        pytest.param(lambda s: next(iter(s.values())), id="values"),
        pytest.param(lambda s: next(iter(s.iter_batches()))["a"], id="iter_batches"),
    ],
)
def test_mutating_a_returned_value_does_not_change_the_store(
    store: BaseStore, read: Callable[[BaseStore], dict]
) -> None:
    store.set("a", {"tags": ["a"]})
    read(store)["tags"].append("b")
    assert store.get("a") == {"tags": ["a"]}


############################
#     Atomic conflicts     #
############################


def test_raise_with_one_conflict_writes_nothing(store: BaseStore) -> None:
    store.set("b", {"v": 1})
    with pytest.raises(KeyError, match=r"already exist"):
        store.set_many({"a": {"v": 2}, "b": {"v": 2}}, on_conflict="raise")
    assert dict(next(iter(store.iter_batches()))) == {"b": {"v": 1}}


def test_merge_does_not_lose_updates_of_other_threads(store: BaseStore) -> None:
    r"""Test that concurrent merges of one key keep every field."""

    def write(thread: int) -> None:
        for i in range(NUM_WRITES):
            store.set("a", {f"{thread}-{i}": i}, on_conflict="merge")

    with ThreadPoolExecutor(NUM_THREADS) as executor:
        list(executor.map(write, range(NUM_THREADS)))
    assert len(store.get("a")) == NUM_THREADS * NUM_WRITES


def test_raise_succeeds_for_one_thread_only(store: BaseStore) -> None:
    r"""Test that one of several concurrent writes with ``raise``
    succeeds, and that its value is kept."""
    barrier = threading.Barrier(NUM_THREADS)
    winners: list[int] = []
    lock = threading.Lock()

    def write(thread: int) -> None:
        barrier.wait()
        try:
            store.set("a", {"thread": thread}, on_conflict="raise")
        except KeyError:
            return
        with lock:
            winners.append(thread)

    with ThreadPoolExecutor(NUM_THREADS) as executor:
        list(executor.map(write, range(NUM_THREADS)))
    assert [store.get("a")] == [{"thread": winner} for winner in winners]


async def test_merge_does_not_lose_updates_of_sync_and_async_writes(store: BaseStore) -> None:
    r"""Test that merges from ``set`` in threads and from ``aset`` tasks
    keep every field."""

    def write() -> None:
        for i in range(NUM_WRITES):
            store.set("a", {f"sync-{i}": i}, on_conflict="merge")

    await asyncio.gather(
        asyncio.to_thread(write),
        *(store.aset("a", {f"async-{i}": i}, on_conflict="merge") for i in range(NUM_WRITES)),
    )
    assert len(store.get("a")) == 2 * NUM_WRITES


def test_merge_with_concurrent_overwrite_and_delete(store: BaseStore) -> None:
    r"""Test that a merge that runs with overwrites and deletes never
    brings back a field that was removed before it."""

    def merge() -> None:
        for _ in range(NUM_WRITES):
            store.set("a", {"merged": True}, on_conflict="merge")

    def replace() -> None:
        for _ in range(NUM_WRITES):
            store.set("a", {"old": True})
            store.delete("a")
        store.set("a", {"last": True})

    with ThreadPoolExecutor(2) as executor:
        futures = [executor.submit(merge), executor.submit(replace)]
        for future in futures:
            future.result()
    assert "old" not in store.get("a")


############################
#     Filter semantics     #
############################


@pytest.fixture
def filter_store(request: pytest.FixtureRequest, store: BaseStore, codec: Codec) -> BaseStore:
    r"""Return the store, except for the backends that do not use the
    filter of the base class yet."""
    backend = request.node.callspec.params["unopened_store"]
    if backend in SQL_BACKENDS and codec.name == "json":
        pytest.skip("The SQL stores with a JSON codec compare the values in the database")
    return store


DOCUMENTS = {
    "int": {"v": 1},
    "str": {"v": "1"},
    "float": {"v": 1.5},
    "none": {"v": None},
    "absent": {},
    "list": {"v": [1, "1"]},
}


@pytest.mark.parametrize(
    ("expected_value", "keys"),
    [
        pytest.param(1, ["int"], id="int"),
        pytest.param(1.0, ["int"], id="float_equal_to_int"),
        pytest.param("1", ["str"], id="str"),
        pytest.param(1.5, ["float"], id="float"),
        pytest.param(None, ["absent", "none"], id="none"),
        pytest.param([1, "1"], ["list"], id="list"),
        pytest.param(2, [], id="no_match"),
    ],
)
def test_filter_matches_equal_values(
    filter_store: BaseStore, expected_value: object, keys: list[str]
) -> None:
    store = filter_store
    store.set_many({key: {"key": key, **value} for key, value in DOCUMENTS.items()})
    assert sorted(value["key"] for value in store.filter(v=expected_value)) == keys


@pytest.mark.parametrize("field", ["x-y", "a b", "a.b", "a'b", 'a"b', "1", "é", "order", "fields"])
def test_filter_accepts_any_field_name(filter_store: BaseStore, field: str) -> None:
    store = filter_store
    store.set_many({"a": {field: 1}, "b": {field: 2}})
    assert store.filter(**{field: 1}) == [{field: 1}]


@pytest.mark.parametrize("fields", [{}, {"v": 1}])
async def test_afilter_matches_filter(store: BaseStore, fields: dict) -> None:
    store.set_many({str(i): {"v": i % 3} for i in range(600)})
    assert await store.afilter(**fields) == store.filter(**fields)


############################
#     Stable iteration     #
############################


@pytest.mark.parametrize("batch_size", [1, 3, 32])
def test_deleting_yielded_keys_visits_every_key_once(store: BaseStore, batch_size: int) -> None:
    store.set_many({str(i): {} for i in range(10)})
    visited: list[str] = []
    for batch in store.iter_batches(batch_size=batch_size):
        visited.extend(batch)
        store.delete_many(list(batch))
    assert sorted(visited) == [str(i) for i in range(10)]


def test_writes_during_iteration_keep_present_keys(store: BaseStore) -> None:
    store.set_many({str(i): {} for i in range(10)})
    visited: list[str] = []
    for i, key in enumerate(store.keys()):
        visited.append(key)
        store.set(f"new-{i}", {})
        store.set(key, {"updated": True})
    assert sorted(key for key in visited if not key.startswith("new-")) == [
        str(i) for i in range(10)
    ]


async def test_deleting_yielded_keys_visits_every_key_once_async(store: BaseStore) -> None:
    store.set_many({str(i): {} for i in range(10)})
    visited: list[str] = []
    async for batch in store.aiter_batches(batch_size=3):
        visited.extend(batch)
        await store.adelete_many(list(batch))
    assert sorted(visited) == [str(i) for i in range(10)]


def test_batches_are_bounded(store: BaseStore) -> None:
    store.set_many({str(i): {} for i in range(10)})
    assert max(len(batch) for batch in store.iter_batches(batch_size=3)) == 3


def test_other_threads_can_write_between_two_batches(store: BaseStore) -> None:
    r"""Test that an iteration does not keep the lock of the store while
    the caller handles a batch."""
    store.set_many({"a": {}, "b": {}})
    with ThreadPoolExecutor(1) as executor:
        for _ in store.iter_batches(batch_size=1):
            executor.submit(store.set, "c", {}).result(timeout=10)
    assert store.contains("c")


###########################
#     Persistent data     #
###########################


@pytest.mark.parametrize("backend", backend_params(PERSISTENT))
def test_uri_reconnects_to_the_data(backend: str, codec: Codec, tmp_path: Path) -> None:
    with BACKENDS[backend](codec, tmp_path) as store:
        store.set("a", {"v": 1})
    with store.from_uri(store.to_uri()) as restored:
        assert restored.get("a") == {"v": 1}


@pytest.mark.parametrize("backend", backend_params(PERSISTENT))
def test_read_only_store_reads_the_data(backend: str, codec: Codec, tmp_path: Path) -> None:
    with BACKENDS[backend](codec, tmp_path) as store:
        store.set("a", {"v": 1})
    with store.from_uri(store.to_uri(), read_only=True) as restored:
        assert restored.get("a") == {"v": 1}


@pytest.mark.parametrize("backend", backend_params(PERSISTENT))
def test_open_with_the_other_codec_raises(backend: str, codec: Codec, tmp_path: Path) -> None:
    with BACKENDS[backend](codec, tmp_path):
        pass
    other = PickleCodec() if codec.name == "json" else JsonCodec()
    store = BACKENDS[backend](other, tmp_path)
    with pytest.raises(ValueError, match=r"does not match the codec"):
        store.open()
    assert store.closed


#################################
#     Durable and owned data    #
#################################


def test_value_stays_until_deleted(store: BaseStore) -> None:
    store.set("a", {"v": 1})
    store.set_many({"b": {}, "c": {}})
    store.delete("b")
    assert store.get("a") == {"v": 1}


def test_clear_only_removes_own_data(store: BaseStore) -> None:
    store.set("a", {})
    with InMemoryStore() as other:
        other.set("a", {})
        other.clear()
    assert store.count() == 1


######################################
#     Lifecycle and empty inputs     #
######################################

SYNC_OPERATIONS = [
    pytest.param(lambda s: s.get("a"), id="get"),
    pytest.param(lambda s: s.get_many([]), id="get_many"),
    pytest.param(lambda s: s.set("a", {}), id="set"),
    pytest.param(lambda s: s.set_many({}), id="set_many"),
    pytest.param(lambda s: s.set_batches([]), id="set_batches"),
    pytest.param(lambda s: s.delete("a"), id="delete"),
    pytest.param(lambda s: s.delete_many([]), id="delete_many"),
    pytest.param(lambda s: s.clear(), id="clear"),
    pytest.param(lambda s: s.contains("a"), id="contains"),
    pytest.param(lambda s: s.contains_many([]), id="contains_many"),
    pytest.param(lambda s: s.filter(), id="filter"),
    pytest.param(lambda s: list(s.keys()), id="keys"),
    pytest.param(lambda s: list(s.values()), id="values"),
    pytest.param(lambda s: list(s.iter_batches()), id="iter_batches"),
    pytest.param(lambda s: s.count(), id="count"),
]

ASYNC_OPERATIONS = [
    pytest.param(lambda s: s.aget("a"), id="aget"),
    pytest.param(lambda s: s.aget_many([]), id="aget_many"),
    pytest.param(lambda s: s.aset("a", {}), id="aset"),
    pytest.param(lambda s: s.aset_many({}), id="aset_many"),
    pytest.param(lambda s: s.aset_batches([]), id="aset_batches"),
    pytest.param(lambda s: s.adelete("a"), id="adelete"),
    pytest.param(lambda s: s.adelete_many([]), id="adelete_many"),
    pytest.param(lambda s: s.aclear(), id="aclear"),
    pytest.param(lambda s: s.acontains("a"), id="acontains"),
    pytest.param(lambda s: s.acontains_many([]), id="acontains_many"),
    pytest.param(lambda s: s.afilter(), id="afilter"),
    pytest.param(lambda s: collect(s.akeys()), id="akeys"),
    pytest.param(lambda s: collect(s.avalues()), id="avalues"),
    pytest.param(lambda s: collect(s.aiter_batches()), id="aiter_batches"),
    pytest.param(lambda s: s.acount(), id="acount"),
]


@pytest.mark.parametrize("operation", SYNC_OPERATIONS)
def test_operation_before_open_raises(
    any_store: BaseStore, operation: Callable[[BaseStore], Any]
) -> None:
    with pytest.raises(RuntimeError, match=r"is not open"):
        operation(any_store)


@pytest.mark.parametrize("operation", SYNC_OPERATIONS)
def test_operation_after_close_raises(
    any_store: BaseStore, operation: Callable[[BaseStore], Any]
) -> None:
    with any_store:
        pass
    with pytest.raises(RuntimeError, match=r"is not open"):
        operation(any_store)


@pytest.mark.parametrize("operation", ASYNC_OPERATIONS)
async def test_async_operation_after_close_raises(
    any_store: BaseStore, operation: Callable[[BaseStore], Any]
) -> None:
    async with any_store:
        pass
    with pytest.raises(RuntimeError, match=r"is not open"):
        await operation(any_store)


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(lambda s: s.set_many({}, on_conflict="bogus"), id="set_many"),
        pytest.param(lambda s: s.set_batches([], on_conflict="bogus"), id="set_batches"),
    ],
)
def test_invalid_on_conflict_with_empty_input_raises(
    any_store: BaseStore, operation: Callable[[BaseStore], Any]
) -> None:
    with any_store, pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        operation(any_store)


def test_constructor_does_not_open(any_store: BaseStore) -> None:
    assert any_store.closed


def test_uri_gives_a_closed_store_of_the_same_class(any_store: BaseStore) -> None:
    restored = any_store.from_uri(any_store.to_uri())
    assert (type(restored), restored.closed) == (type(any_store), True)


#########################
#     Async threads     #
#########################


def test_async_use_in_two_event_loops(store: BaseStore) -> None:
    r"""Test that a store whose async calls waited for each other in one
    event loop can be used in another one."""

    async def write(prefix: str) -> None:
        await asyncio.gather(*(store.aset(f"{prefix}-{i}", {}) for i in range(NUM_WRITES)))

    asyncio.run(write("first"))
    asyncio.run(write("second"))
    assert store.count() == 2 * NUM_WRITES


async def test_waiting_calls_do_not_fill_the_default_executor() -> None:
    r"""Test that calls waiting for a busy store leave the default
    executor of the event loop free."""

    async with BlockingStore() as store:
        calls = [asyncio.ensure_future(store.aget(str(i))) for i in range(64)]
        try:
            assert await asyncio.wait_for(asyncio.to_thread(store.reading.wait, 10), timeout=10)
        finally:
            store.release.set()
        await asyncio.gather(*calls)


async def test_event_loop_is_not_blocked_while_the_store_is_busy() -> None:
    r"""Test that the event loop keeps running while a call waits for
    the backend."""

    async with BlockingStore() as store:
        call = asyncio.ensure_future(store.aget("a"))
        while not store.reading.is_set():
            await asyncio.sleep(0.001)
        running = not call.done()
        store.release.set()
        await call
    assert running


async def test_cancelling_an_iteration_closes_the_backend_iterator() -> None:
    r"""Test that cancelling an async iteration while the backend reads
    a batch closes the iterator once the read is done, and leaves the
    store usable."""

    async with BlockingStore() as store:
        store.set_many({"a": {}})
        task = asyncio.ensure_future(collect(store.akeys()))
        while not store.reading.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        store.release.set()
        with pytest.raises(asyncio.CancelledError, match=r"^$"):
            await task
        assert (await store.acount(), store.closed_iterators) == (1, 1)


async def test_cancelled_call_that_is_still_queued_does_not_run() -> None:
    r"""Test that a write cancelled before the store starts it is not
    applied."""

    async with BlockingStore() as store:
        read = asyncio.ensure_future(store.aget("a"))
        while not store.reading.is_set():
            await asyncio.sleep(0.001)
        write = asyncio.ensure_future(store.aset("a", {}))
        await asyncio.sleep(0)
        write.cancel()
        await asyncio.sleep(0)
        store.release.set()
        await read
        assert await store.acount() == 0
