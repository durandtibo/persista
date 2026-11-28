r"""Contract tests of the stores that implement the primitives of
``BaseStore``: one section per property of the ``persista.store``
package, run for every backend and every codec.

A backend is added to these tests by adding it to ``BACKENDS`` once it
implements the primitives. The behaviour that every backend already
shares is tested in ``test_consistency.py``.

The writes of several instances of the same data are tested in
``test_sql_concurrency.py``, ``test_lmdb_concurrency.py``,
``test_redis_concurrency.py`` and ``test_postgres_concurrency.py``. A file
store makes no such guarantee.
The credentials of the Redis URLs are tested in ``test_redis.py``, and
those of the PostgreSQL connection strings in ``test_postgres.py``.

The Redis and PostgreSQL backends need a reachable server, and remove
their data from it.
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import (
    BaseStore,
    DuckDBStore,
    FileStore,
    InMemoryStore,
    JsonCodec,
    LmdbStore,
    NullStore,
    PickleCodec,
    PostgresStore,
    RedisStore,
    SQLiteStore,
    store_from_uri,
)
from persista.testing.fixtures import (
    duckdb_available,
    lmdb_available,
    psycopg_available,
    redis_available,
)
from tests.integration.store.postgres_helpers import (
    drop_tables,
    get_postgres_conninfo,
    postgres_available,
)
from tests.integration.store.redis_helpers import (
    REDIS_URL,
    delete_namespaces,
    redis_server_available,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator
    from pathlib import Path

    from persista.store import Codec
    from persista.store.types import Payload, Plan

NUM_THREADS = 8
NUM_WRITES = 50

# The prefix of the Redis namespaces of this run of the tests.
REDIS_PREFIX = f"persista-contract-{uuid.uuid4().hex}"
# The prefix of the PostgreSQL tables of this run of the tests.
POSTGRES_PREFIX = f"contract_{uuid.uuid4().hex[:12]}_"


def postgres_store(codec: Codec, path: Path) -> BaseStore:
    r"""Return a PostgreSQL store with one table per directory, as the
    backends that use files."""
    table = POSTGRES_PREFIX + hashlib.sha256(str(path).encode()).hexdigest()[:24]
    return PostgresStore(get_postgres_conninfo() or "", codec=codec, table=table)


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
    def from_uri(cls, uri: str, *, read_only: bool = False, **kwargs: Any) -> PrimitivesOnlyStore:
        del uri, read_only
        return cls(**kwargs)

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


class IntValue(int):
    r"""A subclass of ``int``."""


class StrValue(str):
    r"""A subclass of ``str``."""

    __slots__ = ()


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
    "file": lambda codec, path: FileStore(path / "files", codec=codec),
    "lmdb": lambda codec, path: LmdbStore(path / "lmdb", codec=codec, map_size=2**26),
    # One namespace per directory, as the backends that use files.
    "redis": lambda codec, path: RedisStore(
        REDIS_URL, codec=codec, namespace=f"{REDIS_PREFIX}:{path}"
    ),
    "postgres": postgres_store,
}

# The backends that need an optional library or a server, and the marks
# that skip them.
MARKS: dict[str, list[pytest.MarkDecorator]] = {
    "duckdb": [duckdb_available],
    "duckdb_memory": [duckdb_available],
    "lmdb": [lmdb_available],
    "redis": [redis_available, redis_server_available],
    "postgres": [psycopg_available, postgres_available],
}

# The backends whose data outlives the store.
PERSISTENT = ["sqlite", "duckdb", "file", "lmdb", "redis", "postgres"]

# The backends whose data records the codec that wrote it.
CODEC_CHECKED = ["sqlite", "duckdb", "postgres"]

# The backends that have a read-only mode, which rejects the writes.
READ_ONLY = ["sqlite", "duckdb", "lmdb"]

# The keys that a backend documents it cannot keep.
SURROGATE_KEY = chr(0xD800)
REJECTED_KEYS: dict[str, list[str]] = {
    "sqlite": [SURROGATE_KEY],
    "duckdb": [SURROGATE_KEY],
    "file": ["a" * 251, "A" * 84, "x" * 2000, SURROGATE_KEY],
    "lmdb": ["", "x" * 512, "é" * 256, "x" * 2000, SURROGATE_KEY],
    "redis": [SURROGATE_KEY],
    # A NUL character, and more than 2692 bytes in UTF-8, whether the key
    # can be compressed or not.
    "postgres": [
        "a" + chr(0) + "b",
        SURROGATE_KEY,
        "x" * 2693,
        "é" * 1347,
        "".join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(160)),
    ],
}


def backend_params(names: list[str]) -> list[Any]:
    r"""Return one parameter per backend, with the mark of its optional
    library."""
    return [pytest.param(name, id=name, marks=MARKS.get(name, [])) for name in names]


CODECS: dict[str, Callable[[], Codec]] = {"json": JsonCodec, "pickle": PickleCodec}


@pytest.fixture(scope="module", autouse=True)
def _redis_cleanup() -> Generator[None, None, None]:
    r"""Remove the data of the Redis stores once the tests have run."""
    yield
    delete_namespaces(REDIS_PREFIX)


@pytest.fixture(scope="module", autouse=True)
def _postgres_cleanup() -> Generator[None, None, None]:
    r"""Remove the tables of the PostgreSQL stores once the tests have
    run."""
    yield
    drop_tables(POSTGRES_PREFIX)


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


@pytest.fixture(params=backend_params(list(BACKENDS)))
def pickle_store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Generator[BaseStore, None, None]:
    r"""Return an open store of every backend, with the pickle codec."""
    with BACKENDS[request.param](PickleCodec(), tmp_path) as store:
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


@pytest.fixture
def keys(request: pytest.FixtureRequest, unopened_store: BaseStore) -> list[str]:
    r"""Return the keys of ``KEYS`` that the backend of the store
    accepts."""
    del unopened_store
    backend = request.node.callspec.params["unopened_store"]
    return [key for key in KEYS if key not in REJECTED_KEYS.get(backend, [])]


def test_keys_are_compared_exactly(store: BaseStore, keys: list[str]) -> None:
    store.set_many({key: {"index": i} for i, key in enumerate(keys)})
    assert store.get_many(keys) == [{"index": i} for i in range(len(keys))]


def test_keys_are_listed_exactly(store: BaseStore, keys: list[str]) -> None:
    store.set_many({key: {} for key in keys})
    assert sorted(store.keys()) == sorted(keys)


async def test_keys_are_listed_exactly_async(store: BaseStore, keys: list[str]) -> None:
    await store.aset_many({key: {} for key in keys})
    assert sorted(await collect(store.akeys())) == sorted(keys)


def test_deleting_one_case_of_a_key_keeps_the_other(store: BaseStore) -> None:
    store.set_many({"a": {"v": 1}, "A": {"v": 2}})
    store.delete("a")
    assert store.get_many(["a", "A"]) == [None, {"v": 2}]


# The message of a rejected key: the name of the store, or the message of
# sqlite3, whose error is already a ValueError.
REJECTED_KEY_MESSAGE = (
    r"DuckDBStore|FileStore|LmdbStore|RedisStore|PostgresStore|surrogates not allowed"
)


def rejected_key_params() -> list[Any]:
    r"""Return one parameter per key that a backend rejects."""
    return [
        pytest.param(backend, key, id=f"{backend}-{i}", marks=MARKS.get(backend, []))
        for backend, rejected in REJECTED_KEYS.items()
        for i, key in enumerate(rejected)
    ]


KEY_OPERATIONS = [
    pytest.param(lambda s, k: s.get(k), id="get"),
    pytest.param(lambda s, k: s.get_many(["a", k]), id="get_many"),
    pytest.param(lambda s, k: s.contains(k), id="contains"),
    pytest.param(lambda s, k: s.contains_many(["a", k]), id="contains_many"),
    pytest.param(lambda s, k: s.set(k, {}), id="set"),
    pytest.param(lambda s, k: s.set_many({"a": {}, "b": {}, k: {}}), id="set_many"),
    pytest.param(
        lambda s, k: s.set_many({"a": {}, "b": {}, k: {}}, on_conflict="raise"),
        id="set_many_raise",
    ),
    pytest.param(
        lambda s, k: s.set_many({"a": {}, "b": {}, k: {}}, on_conflict="skip"),
        id="set_many_skip",
    ),
    pytest.param(
        lambda s, k: s.set_many({"a": {}, "b": {}, k: {}}, on_conflict="merge"),
        id="set_many_merge",
    ),
    pytest.param(lambda s, k: s.delete(k), id="delete"),
    pytest.param(lambda s, k: s.delete_many(["a", k]), id="delete_many"),
]

ASYNC_KEY_OPERATIONS = [
    pytest.param(lambda s, k: s.aget(k), id="aget"),
    pytest.param(lambda s, k: s.aget_many(["a", k]), id="aget_many"),
    pytest.param(lambda s, k: s.acontains(k), id="acontains"),
    pytest.param(lambda s, k: s.acontains_many(["a", k]), id="acontains_many"),
    pytest.param(lambda s, k: s.aset(k, {}), id="aset"),
    pytest.param(lambda s, k: s.aset_many({"a": {}, "b": {}, k: {}}), id="aset_many"),
    pytest.param(
        lambda s, k: s.aset_many({"a": {}, "b": {}, k: {}}, on_conflict="merge"),
        id="aset_many_merge",
    ),
    pytest.param(lambda s, k: s.adelete(k), id="adelete"),
    pytest.param(lambda s, k: s.adelete_many(["a", k]), id="adelete_many"),
]


@pytest.mark.parametrize(("backend", "key"), rejected_key_params())
@pytest.mark.parametrize("operation", KEY_OPERATIONS)
def test_rejected_key_raises_and_changes_nothing(
    backend: str, key: str, tmp_path: Path, operation: Callable[[BaseStore, str], Any]
) -> None:
    with BACKENDS[backend](JsonCodec(), tmp_path) as store:
        store.set("a", {"v": 1})
        with pytest.raises(ValueError, match=REJECTED_KEY_MESSAGE):
            operation(store, key)
        assert dict(next(store.iter_batches())) == {"a": {"v": 1}}


@pytest.mark.parametrize(("backend", "key"), rejected_key_params())
@pytest.mark.parametrize("operation", ASYNC_KEY_OPERATIONS)
async def test_rejected_key_raises_and_changes_nothing_async(
    backend: str, key: str, tmp_path: Path, operation: Callable[[BaseStore, str], Any]
) -> None:
    async with BACKENDS[backend](JsonCodec(), tmp_path) as store:
        await store.aset("a", {"v": 1})
        with pytest.raises(ValueError, match=REJECTED_KEY_MESSAGE):
            await operation(store, key)
        assert await store.afilter() == {"a": {"v": 1}}


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
    pytest.param({"large": 1e22, "negative": -1.5e300, "small": 1e-7}, id="floats"),
]


def typed(value: Any) -> str:
    r"""Return the ``repr`` of a value with the keys of its dicts sorted.

    It also compares the types (``1``, ``1.0`` and ``True``, or
    ``tuple`` and ``list``), but not the order of the keys, which a
    ``JSONB`` column does not keep.
    """

    def order(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: order(item[key]) for key in sorted(item, key=repr)}
        if isinstance(item, (list, tuple)):
            return type(item)(map(order, item))
        return item

    return repr(order(value))


@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize(
    "read",
    [
        pytest.param(lambda s: s.get("a"), id="get"),
        pytest.param(lambda s: s.get_many(["a"])[0], id="get_many"),
        pytest.param(lambda s: s.filter()["a"], id="filter"),
        pytest.param(lambda s: next(iter(s.values())), id="values"),
        pytest.param(lambda s: next(iter(s.iter_batches()))["a"], id="iter_batches"),
    ],
)
def test_read_returns_codec_round_trip(
    store: BaseStore, codec: Codec, value: dict, read: Callable[[BaseStore], dict]
) -> None:
    store.set("a", value)
    assert typed(read(store)) == typed(codec.decode(codec.encode(value)))


@pytest.mark.parametrize("value", VALUES)
async def test_async_read_returns_codec_round_trip(
    store: BaseStore, codec: Codec, value: dict
) -> None:
    await store.aset("a", value)
    results = [
        await store.aget("a"),
        *await store.aget_many(["a"]),
        *(await store.afilter()).values(),
        *await collect(store.avalues()),
    ]
    assert typed(results) == typed([codec.decode(codec.encode(value))] * 4)


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
        pytest.param(lambda s: s.filter()["a"], id="filter"),
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

EMOJI = chr(0x1F389)
# "é" as one character, and as "e" followed by a combining accent.
COMPOSED = chr(0xE9)
DECOMPOSED = "e" + chr(0x301)

# One document per kind of value of the field "v".
DOCUMENTS: dict[str, dict[str, Any]] = {
    "int_0": {"v": 0},
    "int_1": {"v": 1},
    "float_1": {"v": 1.0},
    "float_1_5": {"v": 1.5},
    "negative_zero": {"v": -0.0},
    "str_1": {"v": "1"},
    "str_1_0": {"v": "1.0"},
    "str_padded": {"v": " 1"},
    "str": {"v": "abc"},
    "str_upper": {"v": "ABC"},
    "str_empty": {"v": ""},
    "str_true": {"v": "true"},
    "str_null": {"v": "null"},
    "str_list": {"v": "[1]"},
    "str_quote": {"v": "a'b\"c\\d\n"},
    "composed": {"v": COMPOSED},
    "decomposed": {"v": DECOMPOSED},
    "emoji": {"v": EMOJI},
    "true": {"v": True},
    "false": {"v": False},
    "none": {"v": None},
    "absent": {},
    "other_case": {"V": 1},
    "nested_field": {"w": {"v": 1}},
    "list_empty": {"v": []},
    "list_1": {"v": [1]},
    "list_float": {"v": [1.0]},
    "list_true": {"v": [True]},
    "list_str": {"v": ["1"]},
    "list_pair": {"v": [1, "1"]},
    "list_nested": {"v": [[1, {"a": False}]]},
    "dict_empty": {"v": {}},
    "dict_1": {"v": {"a": 1}},
    "dict_true": {"v": {"a": True}},
    "dict_two": {"v": {"a": 1, "b": None}},
    # The largest integers that a double keeps exactly, and beyond.
    "safe_int": {"v": 2**53 - 1},
    "int_2_53": {"v": 2**53},
    "int_2_53_plus_1": {"v": 2**53 + 1},
    "float_2_53": {"v": float(2**53)},
    "int_64": {"v": 2**63 - 1},
    "int_2_64": {"v": 2**64},
    "int_10_30": {"v": 10**30},
    "int_10_22": {"v": 10**22},
    "float_10_22": {"v": 1e22},
}

# The expected value of the field "v", and the keys of the matching
# documents.
FILTERS: list[Any] = [
    pytest.param(0, ["int_0", "negative_zero"], id="int_0"),
    pytest.param(1, ["float_1", "int_1"], id="int_1"),
    pytest.param(1.0, ["float_1", "int_1"], id="float_1"),
    pytest.param(1.5, ["float_1_5"], id="float_1_5"),
    pytest.param(-0.0, ["int_0", "negative_zero"], id="negative_zero"),
    pytest.param("1", ["str_1"], id="str_1"),
    pytest.param("1.0", ["str_1_0"], id="str_1_0"),
    pytest.param(" 1", ["str_padded"], id="str_padded"),
    pytest.param("abc", ["str"], id="str"),
    pytest.param("", ["str_empty"], id="str_empty"),
    pytest.param("true", ["str_true"], id="str_true"),
    pytest.param("null", ["str_null"], id="str_null"),
    pytest.param("[1]", ["str_list"], id="str_list"),
    pytest.param('{"a":1}', [], id="str_dict"),
    pytest.param("a'b\"c\\d\n", ["str_quote"], id="str_quote"),
    pytest.param("' OR '1'='1", [], id="str_injection"),
    pytest.param(COMPOSED, ["composed"], id="composed"),
    pytest.param(DECOMPOSED, ["decomposed"], id="decomposed"),
    pytest.param(EMOJI, ["emoji"], id="emoji"),
    pytest.param("abc" + chr(0), [], id="str_nul"),
    pytest.param(chr(0), [], id="nul"),
    pytest.param(chr(0xD800), [], id="surrogate"),
    pytest.param(True, ["true"], id="true"),
    pytest.param(False, ["false"], id="false"),
    pytest.param(None, ["absent", "nested_field", "none", "other_case"], id="none"),
    pytest.param([], ["list_empty"], id="list_empty"),
    pytest.param([1], ["list_1", "list_float"], id="list_1"),
    pytest.param((1,), ["list_1", "list_float"], id="tuple_1"),
    pytest.param([True], ["list_true"], id="list_true"),
    pytest.param(["1"], ["list_str"], id="list_str"),
    pytest.param([1, "1"], ["list_pair"], id="list_pair"),
    pytest.param(["1", 1], [], id="list_other_order"),
    pytest.param([[1, {"a": False}]], ["list_nested"], id="list_nested"),
    pytest.param([[1, {"a": 0}]], [], id="list_nested_int_for_bool"),
    pytest.param({}, ["dict_empty"], id="dict_empty"),
    pytest.param({"a": 1}, ["dict_1"], id="dict_1"),
    pytest.param({"a": 1.0}, ["dict_1"], id="dict_float"),
    pytest.param({"a": True}, ["dict_true"], id="dict_true"),
    pytest.param({"b": None, "a": 1}, ["dict_two"], id="dict_other_order"),
    pytest.param({"a": 1, "c": None}, [], id="dict_other_key"),
    pytest.param(2**53 - 1, ["safe_int"], id="safe_int"),
    pytest.param(2**53, ["float_2_53", "int_2_53"], id="int_2_53"),
    pytest.param(float(2**53), ["float_2_53", "int_2_53"], id="float_2_53"),
    pytest.param(2**53 + 1, ["int_2_53_plus_1"], id="int_2_53_plus_1"),
    pytest.param(2**63 - 1, ["int_64"], id="int_64"),
    pytest.param(2**64, ["int_2_64"], id="int_2_64"),
    pytest.param(10**30, ["int_10_30"], id="int_10_30"),
    pytest.param(1e30, [], id="float_10_30"),
    pytest.param(10**22, ["float_10_22", "int_10_22"], id="int_10_22"),
    pytest.param(1e22, ["float_10_22", "int_10_22"], id="float_10_22"),
    pytest.param(10**400, [], id="int_10_400"),
    pytest.param(float("nan"), [], id="nan"),
    pytest.param([float("nan")], [], id="list_nan"),
    pytest.param(float("inf"), [], id="inf"),
    pytest.param({1}, [], id="set"),
    pytest.param(b"abc", [], id="bytes"),
    pytest.param(2, [], id="no_match"),
]


@pytest.mark.parametrize(("expected", "keys"), FILTERS)
def test_filter_matches_equal_values(store: BaseStore, expected: object, keys: list[str]) -> None:
    store.set_many(DOCUMENTS)
    assert sorted(store.filter(v=expected)) == keys


@pytest.mark.parametrize(("expected", "keys"), FILTERS)
async def test_afilter_matches_equal_values(
    store: BaseStore, expected: object, keys: list[str]
) -> None:
    await store.aset_many(DOCUMENTS)
    assert sorted(await store.afilter(v=expected)) == keys


def test_filter_returns_values_by_key(store: BaseStore) -> None:
    store.set_many({"a": {"v": 1, "w": "x"}, "b": {"v": 2}, "c": {"v": 1}})
    assert store.filter(v=1) == {"a": {"v": 1, "w": "x"}, "c": {"v": 1}}


def test_filter_without_field_returns_every_pair(store: BaseStore) -> None:
    store.set_many({str(i): {"v": i} for i in range(600)})
    assert store.filter() == {str(i): {"v": i} for i in range(600)}


def test_filter_empty_store(store: BaseStore) -> None:
    assert store.filter(v=1) == {}


# Integers of several magnitudes that a database can be asked for.
NUMBERS = [
    -(2**53 - 1),
    -(10**15),
    -123456789,
    -1,
    7,
    2**31,
    123456789012345,
    10**15,
    2**52 + 1,
    2**53 - 1,
]


@pytest.mark.parametrize("number", NUMBERS)
def test_filter_int_matches_int_and_float(store: BaseStore, number: int) -> None:
    store.set_many(
        {
            "int": {"v": number},
            "float": {"v": float(number)},
            "str": {"v": str(number)},
            "next": {"v": number - 1},
        }
    )
    assert sorted(store.filter(v=number)) == ["float", "int"]


@pytest.mark.parametrize(
    ("fields", "keys"),
    [
        pytest.param({"a": 1, "b": "x"}, ["both"], id="int_str"),
        pytest.param({"a": 1, "b": None}, ["no_b"], id="int_none"),
        pytest.param({"a": 1, "c d": True}, ["unsafe"], id="int_unsafe_name"),
        pytest.param({"a": 1.0, "b": "x"}, ["both"], id="float_str"),
        pytest.param({"a": "1", "b": "x"}, ["text"], id="str_str"),
    ],
)
def test_filter_combines_fields(store: BaseStore, fields: dict, keys: list[str]) -> None:
    store.set_many(
        {
            "both": {"a": 1, "b": "x"},
            "no_b": {"a": 1},
            "unsafe": {"a": 1, "b": "y", "c d": True},
            "text": {"a": "1", "b": "x"},
            "other": {"a": True, "b": "x", "c d": 1},
        }
    )
    assert sorted(store.filter(**fields)) == keys


FIELD_NAMES = [
    "x-y",
    "a b",
    "a.b",
    "a'b",
    'a"b',
    "a\\b",
    "a[0]",
    "$",
    "%s",
    "?",
    "*",
    "/a",
    "1",
    "",
    "a\n",
    COMPOSED,
    EMOJI,
    "order",
    "select",
    "key",
    "value",
    "null",
    "true",
    "self",
    "fields",
    "field_filters",
    "batch_size",
    "_",
    "__x__",
    "A1_b",
    "x" * 200,
]


@pytest.mark.parametrize("expected", [1, "x", None])
@pytest.mark.parametrize("field", FIELD_NAMES)
def test_filter_accepts_any_field_name(store: BaseStore, field: str, expected: object) -> None:
    store.set_many({"match": {field: expected}, "other": {field: 2}})
    assert store.filter(**{field: expected}) == {"match": {field: expected}}


@pytest.mark.parametrize(("field", "other"), [("a", "A"), ("A", "a")])
@pytest.mark.parametrize("expected", [1, "x"])
def test_filter_field_names_are_case_sensitive(
    store: BaseStore, field: str, other: str, expected: object
) -> None:
    store.set_many({"first": {other: 2, field: expected}, "second": {field: 2, other: expected}})
    assert list(store.filter(**{field: expected})) == ["first"]


def test_filter_many_fields(store: BaseStore) -> None:
    fields = {f"f{i}": i for i in range(1500)}
    store.set_many({"match": fields, "other": {**fields, "f1499": 0}})
    assert list(store.filter(**fields)) == ["match"]


def test_filter_does_not_read_a_dotted_name_as_a_path(store: BaseStore) -> None:
    store.set_many({"flat": {"a.b": 1}, "nested": {"a": {"b": 1}}})
    assert list(store.filter(**{"a.b": 1})) == ["flat"]


@pytest.mark.parametrize("expected", [1, "x"])
def test_filter_deeply_nested_value(store: BaseStore, expected: object) -> None:
    # Deeper than what the JSON functions of SQLite accept.
    deep: list[Any] = []
    for _ in range(1500):
        deep = [deep]
    store.set_many({"deep": {"v": expected, "deep": deep}, "flat": {"v": expected}})
    assert sorted(store.filter(v=expected)) == ["deep", "flat"]


def test_filter_str_with_nul(request: pytest.FixtureRequest, store: BaseStore) -> None:
    params = request.node.callspec.params
    if params["unopened_store"] == "postgres" and params["codec"] == "json":
        pytest.skip("JSONB cannot keep a NUL character")
    text = "a" + chr(0) + "b"
    store.set_many({"nul": {"v": text}, "prefix": {"v": "a"}})
    assert list(store.filter(v=text)) == ["nul"]


@pytest.mark.parametrize(
    ("expected", "key"),
    [pytest.param(IntValue(1), "int", id="int"), pytest.param(StrValue("1"), "str", id="str")],
)
def test_filter_value_of_a_subclass(store: BaseStore, expected: object, key: str) -> None:
    store.set_many({"int": {"v": 1}, "str": {"v": "1"}, "bool": {"v": True}})
    assert list(store.filter(v=expected)) == [key]


@pytest.mark.parametrize(
    "expected",
    [
        pytest.param({1, 2}, id="set"),
        pytest.param(b"ab", id="bytes"),
        pytest.param((1, [2]), id="tuple"),
        pytest.param({1: "a", (2,): None}, id="non_str_keys"),
        pytest.param(Decimal("1.5"), id="decimal"),
        pytest.param(float("inf"), id="inf"),
    ],
)
def test_filter_matches_values_that_only_pickle_keeps(
    pickle_store: BaseStore, expected: object
) -> None:
    pickle_store.set_many({"match": {"v": expected}, "other": {"v": 2}})
    assert list(pickle_store.filter(v=expected)) == ["match"]


def test_filter_nan_matches_nothing_with_a_stored_nan(pickle_store: BaseStore) -> None:
    pickle_store.set("a", {"v": float("nan")})
    assert pickle_store.filter(v=float("nan")) == {}


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


def uri_options(store: BaseStore) -> dict[str, Any]:
    r"""Return the arguments of the constructor that the URI of a store
    does not describe, and that ``from_uri`` needs to read its data."""
    if isinstance(store, RedisStore):
        return {"codec": store._codec, "namespace": store.namespace}
    if isinstance(store, PostgresStore):
        return {"codec": store._codec, "table": store._table}
    return {}


@pytest.mark.parametrize("backend", backend_params(PERSISTENT))
def test_uri_reconnects_to_the_data(backend: str, codec: Codec, tmp_path: Path) -> None:
    with BACKENDS[backend](codec, tmp_path) as store:
        store.set("a", {"v": 1})
    with store.from_uri(store.to_uri(), **uri_options(store)) as restored:
        assert restored.get("a") == {"v": 1}


@pytest.mark.parametrize("backend", backend_params(["file", "sqlite", "duckdb", "lmdb"]))
def test_store_from_uri_reads_the_data_of_a_local_store(
    backend: str, codec: Codec, tmp_path: Path
) -> None:
    with BACKENDS[backend](codec, tmp_path) as store:
        store.set("a", {"v": 1})
    with store_from_uri(store.to_uri()) as restored:
        assert restored.get("a") == {"v": 1}


@pytest.mark.parametrize("backend", backend_params([*BACKENDS]))
def test_from_uri_accepts_the_codec(backend: str, codec: Codec, tmp_path: Path) -> None:
    store = BACKENDS[backend](codec, tmp_path)
    restored = store.from_uri(store.to_uri(), codec=codec)
    assert restored._codec is codec


@pytest.mark.parametrize("backend", backend_params(PERSISTENT))
def test_read_only_store_reads_the_data(backend: str, codec: Codec, tmp_path: Path) -> None:
    with BACKENDS[backend](codec, tmp_path) as store:
        store.set("a", {"v": 1})
    with store.from_uri(store.to_uri(), read_only=True, **uri_options(store)) as restored:
        assert restored.get("a") == {"v": 1}


@pytest.mark.parametrize("backend", backend_params(READ_ONLY))
def test_read_only_store_does_not_create_anything(
    backend: str, codec: Codec, tmp_path: Path
) -> None:
    missing = BACKENDS[backend](codec, tmp_path / "missing")
    restored = missing.from_uri(missing.to_uri(), read_only=True)
    # Each driver has its own error for a database that does not exist.
    errors = r"unable to open database|database does not exist|No LMDB environment"
    with pytest.raises(Exception, match=errors):
        restored.open()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("backend", backend_params(CODEC_CHECKED))
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


def test_repr_does_not_show_the_number_of_values(any_store: BaseStore) -> None:
    with any_store as store:
        before = repr(store)
        store.set("a", {})
        assert repr(store) == before


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
