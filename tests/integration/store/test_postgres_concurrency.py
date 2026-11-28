r"""Concurrency tests of :class:`~persista.store.PostgresStore` with a
real server: several writers of the same table (threads, tasks and
instances).

Most tests use two stores on the same table, so no lock of an instance
protects the writes: only the server does.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import JsonCodec, PickleCodec, PostgresStore
from persista.testing.fixtures import psycopg_available
from persista.utils.imports import is_psycopg_available
from tests.integration.store.postgres_helpers import (
    drop_tables,
    get_postgres_conninfo,
    postgres_available,
)
from tests.integration.store.test_sql_concurrency import (
    NUM_TRIALS,
    NUM_WRITES,
    amerge_fields,
    atry_to_create,
    merge_fields,
    run_in_threads,
    try_to_create,
)

if is_psycopg_available():
    import psycopg
    from psycopg import sql

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator

    from persista.store import Codec

pytestmark = [psycopg_available, postgres_available]

# The prefix of the tables of this module.
PREFIX = f"concurrency_{uuid.uuid4().hex[:12]}_"

# More keys than a write locks one by one: it locks the table.
MANY_KEYS = [f"many-{i}" for i in range(100)]

# A write that never ends because of a deadlock fails the test.
TIMEOUT = 60.0

Stores = tuple[PostgresStore, PostgresStore]


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> Generator[None, None, None]:
    r"""Remove the tables of the tests from the server."""
    yield
    drop_tables(PREFIX)


def create_store(table: str, codec: Codec | None = None) -> PostgresStore:
    r"""Return a store of a table whose statements cannot wait forever."""
    return PostgresStore(
        get_postgres_conninfo(),
        codec=codec,
        table=table,
        options=f"-c statement_timeout={int(TIMEOUT * 1000)}",
    )


@pytest.fixture
def table() -> str:
    r"""Return the name of a table that no other test uses."""
    return PREFIX + uuid.uuid4().hex


@pytest.fixture(params=[JsonCodec(), PickleCodec()], ids=["json", "pickle"])
def stores(request: pytest.FixtureRequest, table: str) -> Generator[Stores, None, None]:
    r"""Return two open stores of the same table."""
    with (
        create_store(table, request.param) as first,
        create_store(table, request.param) as second,
    ):
        yield first, second


@pytest.fixture
async def astores(stores: Stores) -> AsyncGenerator[Stores]:
    r"""Return two open stores, and close their async connections."""
    yield stores
    for store in stores:
        await store.aclose()


class PausingCodec(JsonCodec):
    r"""A JSON codec whose next decoding waits for the test.

    A merge decodes the existing value between its read and its write, in
    its transaction: this pauses it there.
    """

    def __init__(self) -> None:
        self.armed = False
        self.paused = threading.Event()
        self.release = threading.Event()

    def decode(self, payload: str | bytes) -> dict[str, Any]:
        if self.armed:
            self.armed = False
            self.paused.set()
            self.release.wait(timeout=TIMEOUT)
        return super().decode(payload)


REMOVALS = [
    pytest.param(lambda s: s.set("a", {"new": 1}), {"new": 1}, id="set"),
    pytest.param(lambda s: s.set_many({"a": {"new": 1}, "b": {}}), {"new": 1}, id="set_many"),
    pytest.param(
        lambda s: s.set_many({key: {"new": 1} for key in ["a", *MANY_KEYS]}),
        {"new": 1},
        id="set_many_table_lock",
    ),
    pytest.param(lambda s: s.delete("a"), None, id="delete"),
    pytest.param(lambda s: s.delete_many(["a", "b"]), None, id="delete_many"),
    pytest.param(lambda s: s.delete_many(["a", *MANY_KEYS]), None, id="delete_many_table_lock"),
    pytest.param(lambda s: s.clear(), None, id="clear"),
]

ASYNC_REMOVALS = [
    pytest.param(lambda s: s.aset("a", {"new": 1}), {"new": 1}, id="aset"),
    pytest.param(lambda s: s.aset_many({"a": {"new": 1}, "b": {}}), {"new": 1}, id="aset_many"),
    pytest.param(
        lambda s: s.aset_many({key: {"new": 1} for key in ["a", *MANY_KEYS]}),
        {"new": 1},
        id="aset_many_table_lock",
    ),
    pytest.param(lambda s: s.adelete("a"), None, id="adelete"),
    pytest.param(lambda s: s.adelete_many(["a", "b"]), None, id="adelete_many"),
    pytest.param(lambda s: s.adelete_many(["a", *MANY_KEYS]), None, id="adelete_many_table_lock"),
    pytest.param(lambda s: s.aclear(), None, id="aclear"),
]

# A merge that locks the key "a", and one that locks the table.
MERGES = [
    pytest.param({"a": {"merged": True}}, id="key_lock"),
    pytest.param({key: {"merged": True} for key in ["a", *MANY_KEYS]}, id="table_lock"),
]


#########################################
#     Tests for the locks of writes     #
#########################################


@pytest.mark.parametrize("items", MERGES)
@pytest.mark.parametrize(("remove", "expected"), REMOVALS)
def test_write_waits_for_a_merge_in_progress(
    table: str,
    items: dict[str, dict],
    remove: Callable[[PostgresStore], None],
    expected: dict | None,
) -> None:
    r"""Test that an overwrite, a delete or a clear of another instance
    waits for a merge that has read the value but not written it yet, so
    the merge cannot bring back what it removes (regression test: they
    took no lock)."""
    codec = PausingCodec()
    with create_store(table, codec) as first, create_store(table) as second:
        first.set("a", {"old": True})
        codec.armed = True
        with ThreadPoolExecutor(2) as executor:
            merge = executor.submit(first.set_many, items, on_conflict="merge")
            assert codec.paused.wait(timeout=TIMEOUT)
            removal = executor.submit(remove, second)
            waited = not wait([removal], timeout=0.5).done
            codec.release.set()
            merge.result(timeout=TIMEOUT)
            removal.result(timeout=TIMEOUT)
        assert (waited, second.get("a")) == (True, expected)


@pytest.mark.parametrize(("remove", "expected"), ASYNC_REMOVALS)
async def test_async_write_waits_for_a_merge_in_progress(
    table: str,
    remove: Callable[[PostgresStore], Awaitable[None]],
    expected: dict | None,
) -> None:
    r"""Async equivalent of
    ``test_write_waits_for_a_merge_in_progress``."""
    codec = PausingCodec()
    with create_store(table, codec) as first, create_store(table) as second:
        first.set("a", {"old": True})
        codec.armed = True
        merge = asyncio.ensure_future(
            asyncio.to_thread(first.set, "a", {"merged": True}, on_conflict="merge")
        )
        assert await asyncio.to_thread(codec.paused.wait, TIMEOUT)
        removal = asyncio.ensure_future(remove(second))
        done, _ = await asyncio.wait([removal], timeout=0.5)
        codec.release.set()
        await asyncio.wait_for(asyncio.gather(merge, removal), TIMEOUT)
        assert (done, await second.aget("a")) == (set(), expected)
        await second.aclose()


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(lambda s: s.set("new", {"v": 1}), id="set"),
        pytest.param(lambda s: s.set_many({"new": {"v": 1}, "b": {}}), id="set_many"),
        pytest.param(
            lambda s: s.set_many({key: {"v": 1} for key in ["new", *MANY_KEYS]}),
            id="set_many_table_lock",
        ),
    ],
)
def test_overwrite_waits_for_a_merge_that_creates_the_key(
    table: str, write: Callable[[PostgresStore], None]
) -> None:
    r"""Test that an overwrite that waits for a merge which creates its
    key replaces the value of the merge."""
    codec = PausingCodec()
    with create_store(table, codec) as first, create_store(table) as second:
        first.set("a", {})
        codec.armed = True
        with ThreadPoolExecutor(2) as executor:
            items = {"a": {}, "new": {"merged": True}}
            merge = executor.submit(first.set_many, items, on_conflict="merge")
            assert codec.paused.wait(timeout=TIMEOUT)
            overwrite = executor.submit(write, second)
            waited = not wait([overwrite], timeout=0.5).done
            codec.release.set()
            merge.result(timeout=TIMEOUT)
            overwrite.result(timeout=TIMEOUT)
        assert (waited, second.get("new")) == (True, {"v": 1})


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(lambda s: s.set("b", {}), id="set"),
        pytest.param(lambda s: s.set_many({"b": {}, "c": {}}), id="set_many"),
        pytest.param(lambda s: s.delete("b"), id="delete"),
        pytest.param(lambda s: s.set("b", {}, on_conflict="merge"), id="merge"),
    ],
)
def test_write_of_other_keys_does_not_wait(
    table: str, write: Callable[[PostgresStore], None]
) -> None:
    r"""Test that a write is not blocked by a merge of other keys."""
    codec = PausingCodec()
    with create_store(table, codec) as first, create_store(table) as second:
        first.set("a", {})
        codec.armed = True
        with ThreadPoolExecutor(2) as executor:
            merge = executor.submit(first.set, "a", {}, on_conflict="merge")
            assert codec.paused.wait(timeout=TIMEOUT)
            other = executor.submit(write, second)
            done = other.exception(timeout=10)
            codec.release.set()
            merge.result(timeout=TIMEOUT)
        assert done is None


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(lambda s: s.set("a", {}), id="set"),
        pytest.param(lambda s: s.clear(), id="clear"),
    ],
)
def test_write_of_another_table_does_not_wait(
    table: str, write: Callable[[PostgresStore], None]
) -> None:
    r"""Test that the locks of a table do not block the writes of
    another table, even for the same keys."""
    codec = PausingCodec()
    with create_store(table, codec) as first, create_store(f"{table[:50]}_2") as second:
        first.set_many({key: {} for key in ["a", *MANY_KEYS]})
        codec.armed = True
        with ThreadPoolExecutor(2) as executor:
            items = {key: {} for key in ["a", *MANY_KEYS]}
            merge = executor.submit(first.set_many, items, on_conflict="merge")
            assert codec.paused.wait(timeout=TIMEOUT)
            other = executor.submit(write, second)
            done = other.exception(timeout=10)
            codec.release.set()
            merge.result(timeout=TIMEOUT)
        assert done is None


@pytest.mark.parametrize(
    "read",
    [
        pytest.param(lambda s: s.get("a"), id="get"),
        pytest.param(lambda s: s.get_many(["a", "b"]), id="get_many"),
        pytest.param(lambda s: s.filter(), id="filter"),
        pytest.param(lambda s: list(s.keys()), id="keys"),
        pytest.param(lambda s: s.count(), id="count"),
    ],
)
def test_read_does_not_wait(table: str, read: Callable[[PostgresStore], Any]) -> None:
    r"""Test that the reads are not blocked by a merge that locks the
    table."""
    codec = PausingCodec()
    with create_store(table, codec) as first, create_store(table) as second:
        first.set("a", {})
        codec.armed = True
        with ThreadPoolExecutor(2) as executor:
            items = {key: {} for key in ["a", *MANY_KEYS]}
            merge = executor.submit(first.set_many, items, on_conflict="merge")
            assert codec.paused.wait(timeout=TIMEOUT)
            other = executor.submit(read, second)
            done = other.exception(timeout=10)
            codec.release.set()
            merge.result(timeout=TIMEOUT)
        assert done is None


def test_merge_locks_the_table_before_it_reads(table: str) -> None:
    r"""Test that a merge holds the lock of the table that PostgreSQL
    takes for a write while it waits between its read and its write, as
    an upsert does, so a statement that waits for the table cannot make
    the writes wait for each other."""
    codec = PausingCodec()
    name = f"persista-{uuid.uuid4().hex}"
    with PostgresStore(
        get_postgres_conninfo(), codec=codec, table=table, application_name=name
    ) as store:
        store.set("a", {})
        codec.armed = True
        with ThreadPoolExecutor(1) as executor:
            merge = executor.submit(store.set, "a", {}, on_conflict="merge")
            assert codec.paused.wait(timeout=TIMEOUT)
            with psycopg.connect(get_postgres_conninfo(), autocommit=True) as server:
                modes = server.execute(
                    "SELECT l.mode FROM pg_locks AS l "
                    "JOIN pg_stat_activity AS a ON a.pid = l.pid "
                    "JOIN pg_class AS c ON c.oid = l.relation "
                    "WHERE a.application_name = %s AND c.relname = %s",
                    (name, table[:63]),
                ).fetchall()
            codec.release.set()
            merge.result(timeout=TIMEOUT)
        assert ("RowExclusiveLock",) in modes


def test_writes_continue_while_another_program_creates_indexes(table: str) -> None:
    r"""Test that the writes and the statements of another program that
    lock the table all end."""
    stop = threading.Event()

    def create_indexes() -> None:
        with psycopg.connect(get_postgres_conninfo(), autocommit=True) as server:
            index = sql.Identifier(f"{table[:50]}_index")
            create = sql.SQL("CREATE INDEX {} ON {} (key)").format(index, sql.Identifier(table))
            drop = sql.SQL("DROP INDEX {}").format(index)
            while not stop.is_set():
                server.execute(create)
                server.execute(drop)

    def write(store: PostgresStore) -> None:
        for i in range(NUM_WRITES):
            store.set("a", {"i": i})
            store.set("a", {"i": i}, on_conflict="merge")
            store.delete("a")

    with create_store(table) as first, create_store(table) as second:
        with ThreadPoolExecutor(3) as executor:
            indexes = executor.submit(create_indexes)
            writes = [executor.submit(write, store) for store in (first, second)]
            try:
                for future in writes:
                    future.result(timeout=TIMEOUT)
            finally:
                stop.set()
            indexes.result(timeout=TIMEOUT)
        assert first.count() == 0


async def test_cancelled_write_waiting_for_a_key_is_not_applied(table: str) -> None:
    r"""Test that an async write cancelled while it waits for the lock of
    a key writes nothing, and leaves its store usable."""
    codec = PausingCodec()
    with create_store(table, codec) as first, create_store(table) as second:
        first.set("a", {})
        codec.armed = True
        merge = asyncio.ensure_future(
            asyncio.to_thread(first.set, "a", {"merged": True}, on_conflict="merge")
        )
        assert await asyncio.to_thread(codec.paused.wait, TIMEOUT)
        removal = asyncio.ensure_future(second.adelete("a"))
        done, _ = await asyncio.wait([removal], timeout=0.5)
        removal.cancel()
        await asyncio.wait([removal], timeout=10)
        codec.release.set()
        await asyncio.wait_for(merge, TIMEOUT)
        assert (done, removal.cancelled()) == (set(), True)
        await asyncio.wait_for(second.aset("b", {}), TIMEOUT)
        assert await second.aget_many(["a", "b"]) == [{"merged": True}, {}]
        await second.aclose()


#########################################
#     Tests for concurrent writes     #
#########################################


def test_raise_succeeds_for_one_instance_only(stores: Stores) -> None:
    r"""Test that of two instances that create the same key with
    ``raise``, exactly one succeeds, and its value is kept."""
    winners: list[tuple[str, str]] = []
    keys = [str(i) for i in range(NUM_TRIALS)]
    barrier = threading.Barrier(2)

    def write(store: PostgresStore, writer: str) -> None:
        for key in keys:
            barrier.wait(timeout=TIMEOUT)
            try_to_create(store, key, writer, winners)

    run_in_threads(lambda: write(stores[0], "first"), lambda: write(stores[1], "second"))
    assert sorted(winners) == sorted((key, stores[0].get(key)["writer"]) for key in keys)


async def test_raise_succeeds_for_one_async_instance_only(astores: Stores) -> None:
    r"""Test that of the concurrent ``aset`` calls of two instances that
    create the same key with ``raise``, exactly one succeeds."""
    winners: list[tuple[str, str]] = []
    await asyncio.gather(
        *(atry_to_create(astores[i % 2], "a", str(i), winners) for i in range(NUM_WRITES))
    )
    assert winners == [("a", astores[0].get("a")["writer"])]


@pytest.mark.parametrize("size", [2, 70], ids=["key_locks", "table_lock"])
def test_raise_with_several_keys_writes_all_or_nothing(stores: Stores, size: int) -> None:
    r"""Test that instances that create overlapping keys with ``raise``
    never write only a part of their keys."""
    keys = [f"{i:04d}" for i in range(20 * size)]
    barrier = threading.Barrier(2)

    def write(store: PostgresStore, writer: int) -> None:
        for start in range(writer * (size // 2), len(keys) - size, size):
            barrier.wait(timeout=TIMEOUT)
            items = {key: {"writer": f"{writer}-{start}"} for key in keys[start : start + size]}
            with contextlib.suppress(KeyError):
                store.set_many(items, on_conflict="raise")

    run_in_threads(lambda: write(stores[0], 0), lambda: write(stores[1], 1))
    writers = Counter(value["writer"] for value in stores[0].get_many(keys) if value is not None)
    # Every successful write has all of its keys.
    assert set(writers.values()) == {size}


def test_merge_does_not_lose_updates_of_two_instances(stores: Stores) -> None:
    r"""Test that concurrent merges of two instances keep every
    field."""
    run_in_threads(
        *(lambda s=s, p=p: merge_fields(s, p) for s, p in zip(stores, "ab", strict=True))
    )
    assert len(stores[0].get("a")) == 2 * NUM_WRITES


async def test_amerge_does_not_lose_updates_of_two_instances(astores: Stores) -> None:
    r"""Test that the concurrent ``aset`` merges of two instances keep
    every field."""
    await asyncio.gather(amerge_fields(astores[0], "a"), amerge_fields(astores[1], "b"))
    assert len(await astores[0].aget("a")) == 2 * NUM_WRITES


@pytest.mark.parametrize("instances", [(0, 0), (0, 1)], ids=["one_instance", "two_instances"])
async def test_merge_does_not_lose_updates_of_set_and_aset(
    astores: Stores, instances: tuple[int, int]
) -> None:
    r"""Test that merges from ``set`` in a thread and from ``aset``
    tasks keep every field."""
    sync_store, async_store = astores[instances[0]], astores[instances[1]]
    await asyncio.gather(
        asyncio.to_thread(merge_fields, sync_store, "sync"), amerge_fields(async_store, "async")
    )
    assert len(astores[0].get("a")) == 2 * NUM_WRITES


@pytest.mark.parametrize("instances", [(0, 0), (0, 1)], ids=["one_instance", "two_instances"])
async def test_raise_succeeds_once_with_set_and_aset(
    astores: Stores, instances: tuple[int, int]
) -> None:
    r"""Test that of a ``set`` and an ``aset`` that create the same key
    with ``raise``, exactly one succeeds."""
    sync_store, async_store = astores[instances[0]], astores[instances[1]]
    winners: list[tuple[str, str]] = []
    keys = [str(i) for i in range(NUM_TRIALS)]
    for key in keys:
        await asyncio.gather(
            asyncio.to_thread(try_to_create, sync_store, key, "sync", winners),
            atry_to_create(async_store, key, "async", winners),
        )
    assert sorted(winners) == sorted((key, astores[0].get(key)["writer"]) for key in keys)


async def test_concurrent_aset_many_raise_on_one_instance(astores: Stores) -> None:
    r"""Test that concurrent ``aset_many`` calls with ``raise`` on one
    instance do not nest their transactions: each writes all its keys or
    none (regression test: they shared the connection)."""
    store = astores[0]
    # The writes i and i + 1 share a key.
    calls = [
        store.aset_many({str(i): {"writer": i}, str(i + 1): {"writer": i}}, on_conflict="raise")
        for i in range(NUM_WRITES)
    ]
    results = await asyncio.gather(*calls, return_exceptions=True)
    written = {
        key: value["writer"]
        async for batch in store.aiter_batches()
        for key, value in batch.items()
    }
    expected = {
        str(key): i for i, result in enumerate(results) if result is None for key in (i, i + 1)
    }
    errors = {type(result) for result in results if result is not None}
    assert (written, errors) == (expected, {KeyError})


async def test_concurrent_aset_many_skip_on_one_instance(astores: Stores) -> None:
    r"""Test that concurrent ``aset_many`` calls with ``skip`` on one
    instance keep the first value of every key."""
    store = astores[0]
    await asyncio.gather(
        *(
            store.aset_many({str(i): {"writer": i}, str(i + 1): {"writer": i}}, on_conflict="skip")
            for i in range(NUM_WRITES)
        )
    )
    # The calls use the connection in their order.
    values = await store.aget_many([str(i) for i in range(NUM_WRITES + 1)])
    assert [value["writer"] for value in values] == [0, *range(NUM_WRITES)]


async def test_concurrent_aset_many_merge_on_one_instance(astores: Stores) -> None:
    r"""Test that concurrent ``aset_many`` calls with ``merge`` on one
    instance keep every field."""
    store = astores[0]
    await asyncio.gather(
        *(
            store.aset_many({"a": {f"a-{i}": i}, "b": {f"b-{i}": i}}, on_conflict="merge")
            for i in range(NUM_WRITES)
        )
    )
    assert [len(value) for value in await store.aget_many(["a", "b"])] == [NUM_WRITES] * 2


async def test_concurrent_calls_of_every_kind_on_one_instance(astores: Stores) -> None:
    r"""Test that reads, writes, deletes, clears and iterations can run
    at the same time on one instance."""
    store = astores[0]

    async def iterate() -> None:
        async for _ in store.aiter_batches(batch_size=2):
            await store.aget("a")

    calls = [
        call
        for i in range(10)
        for call in (
            store.aset(str(i), {}),
            store.aset_many({"a": {}, "b": {}}, on_conflict="merge"),
            store.aset(f"raise-{i}", {}, on_conflict="raise"),
            store.adelete(str(i - 1)),
            store.afilter(),
            store.acount(),
            iterate(),
        )
    ]
    await asyncio.wait_for(asyncio.gather(*calls), TIMEOUT)
    await store.aclear()
    assert await store.acount() == 0


def replace_values(store: PostgresStore) -> None:
    r"""Overwrite, delete and clear a value several times."""
    for i in range(NUM_WRITES):
        store.set("a", {f"old-{i}": True})
        store.delete("a")
        store.set_many({"a": {f"old-{i}": True}, "b": {}})
        store.clear()
    store.set("a", {"last": True})


async def areplace_values(store: PostgresStore) -> None:
    r"""Async equivalent of ``replace_values``."""
    for i in range(NUM_WRITES):
        await store.aset("a", {f"old-{i}": True})
        await store.adelete("a")
        await store.aset_many({"a": {f"old-{i}": True}, "b": {}})
        await store.aclear()
    await store.aset("a", {"last": True})


def test_merge_with_concurrent_overwrite_delete_and_clear(stores: Stores) -> None:
    r"""Test that merges that run with the overwrites, deletes and
    clears of another instance never bring back a field that was
    removed."""
    first, second = stores
    run_in_threads(lambda: merge_fields(first, "merged"), lambda: replace_values(second))
    assert [field for field in first.get("a") if field.startswith("old")] == []


async def test_amerge_with_concurrent_overwrite_delete_and_clear(astores: Stores) -> None:
    r"""Async equivalent of
    ``test_merge_with_concurrent_overwrite_delete_and_clear``."""
    first, second = astores
    await asyncio.gather(amerge_fields(first, "merged"), areplace_values(second))
    assert [field for field in await first.aget("a") if field.startswith("old")] == []


@pytest.mark.parametrize("instances", [(0, 0), (0, 1)], ids=["one_instance", "two_instances"])
async def test_set_and_aset_merges_with_concurrent_overwrite_delete_and_clear(
    astores: Stores, instances: tuple[int, int]
) -> None:
    r"""Test that merges from ``set`` in a thread and from ``aset`` tasks,
    run with overwrites, deletes and clears, never bring back a field
    that was removed."""
    sync_store, async_store = astores[instances[0]], astores[instances[1]]
    other = astores[1]
    await asyncio.gather(
        asyncio.to_thread(merge_fields, sync_store, "sync"),
        amerge_fields(async_store, "async"),
        asyncio.to_thread(replace_values, other),
    )
    assert [field for field in await other.aget("a") if field.startswith("old")] == []


def test_skip_and_raise_with_concurrent_delete_and_clear(stores: Stores) -> None:
    r"""Test that conditional writes that run with the deletes and
    clears of another instance do not fail."""
    first, second = stores

    def create() -> None:
        for i in range(NUM_WRITES):
            first.set("a", {"i": i}, on_conflict="skip")
            try_to_create(first, "a", "first", [])

    def delete() -> None:
        for _ in range(NUM_WRITES):
            second.delete("a")
            second.set("a", {})
            second.clear()
            second.delete_many(["a", "b"])

    run_in_threads(create, delete)
    assert first.count() <= 1


def test_overlapping_writes_in_any_order_do_not_deadlock(stores: Stores) -> None:
    r"""Test that writes of the same keys given in opposite orders,
    with key locks, table locks and clears, all succeed."""
    small = [str(i) for i in range(20)]
    large = [str(i) for i in range(100)]

    def write(store: PostgresStore, step: int) -> None:
        for i in range(NUM_WRITES // 2):
            keys = (large if i % 5 == 0 else small)[::step]
            store.set_many({key: {"i": i} for key in keys})
            store.set_many({key: {"i": i} for key in keys}, on_conflict="merge")
            store.delete_many(keys[:10])
            if i % 7 == 0:
                store.clear()

    run_in_threads(
        lambda: write(stores[0], 1),
        lambda: write(stores[1], -1),
    )
    assert stores[0].count() <= len(large)


async def test_async_overlapping_writes_do_not_deadlock(astores: Stores) -> None:
    r"""Async equivalent of
    ``test_overlapping_writes_in_any_order_do_not_deadlock``."""
    small = [str(i) for i in range(20)]

    async def write(store: PostgresStore, step: int) -> None:
        for i in range(NUM_WRITES // 2):
            keys = small[::step]
            await store.aset_many({key: {"i": i} for key in keys}, on_conflict="merge")
            await store.adelete_many(keys[:10])
            if i % 7 == 0:
                await store.aclear()

    await asyncio.wait_for(asyncio.gather(write(astores[0], 1), write(astores[1], -1)), TIMEOUT)
    assert await astores[0].acount() <= len(small)


def test_table_locked_writes_of_few_pairs_with_other_writes(stores: Stores) -> None:
    r"""Test that conditional writes that lock the table, and then write
    only a few pairs, end while other writes ask for the lock of the
    table (they ask for the locks of these pairs while they hold it)."""
    first, second = stores
    existing = {key: {} for key in MANY_KEYS}
    first.set_many(existing)

    def create() -> None:
        for i in range(NUM_WRITES):
            first.set_many(existing | {f"new-{i}": {}}, on_conflict="skip")

    def write() -> None:
        for i in range(NUM_WRITES):
            second.set("a", {"i": i})
            second.set_many({"a": {}, "b": {}}, on_conflict="merge")
            second.set_many(existing)

    run_in_threads(create, write)
    assert first.count() == len(MANY_KEYS) + NUM_WRITES + 2


def test_many_instances_write_many_keys(table: str) -> None:
    r"""Test that concurrent writes of many keys do not fill the lock
    table of the server (regression test of the table lock)."""

    def write(writer: int) -> None:
        with create_store(table) as store:
            items = {f"{writer}-{i}": {} for i in range(5_000)}
            store.set_many(items, on_conflict="raise")

    with ThreadPoolExecutor(8) as executor:
        list(executor.map(write, range(8)))
    with create_store(table) as store:
        assert store.count() == 40_000


def test_instances_create_the_table_at_the_same_time(table: str) -> None:
    r"""Test that stores that create the same table at the same time all
    open."""
    barrier = threading.Barrier(8)

    def open_store(writer: int) -> None:
        store = create_store(table)
        barrier.wait(timeout=TIMEOUT)
        with store:
            store.set(str(writer), {})

    with ThreadPoolExecutor(8) as executor:
        list(executor.map(open_store, range(8)))
    with create_store(table) as store:
        assert store.count() == 8


@pytest.mark.parametrize("on_conflict", ["overwrite", "merge", "raise"])
def test_writes_with_a_serializable_default_isolation(table: str, on_conflict: str) -> None:
    r"""Test that concurrent writes succeed when the server runs the
    transactions as serializable by default."""

    def write(writer: int) -> None:
        options = "-c default_transaction_isolation=serializable"
        with PostgresStore(get_postgres_conninfo(), table=table, options=options) as store:
            for i in range(NUM_WRITES):
                key = f"{writer}-{i}" if on_conflict == "raise" else "a"
                store.set(key, {f"{writer}-{i}": i}, on_conflict=on_conflict)

    with create_store(table):
        pass
    run_in_threads(lambda: write(0), lambda: write(1))
    with create_store(table) as store:
        assert store.count() == (2 * NUM_WRITES if on_conflict == "raise" else 1)


def test_iteration_during_writes_of_another_instance(stores: Stores) -> None:
    r"""Test that an iteration yields every key that stays present
    exactly once while another instance writes and deletes."""
    first, second = stores
    stable = [f"stable-{i:03d}" for i in range(NUM_WRITES)]
    first.set_many({key: {} for key in stable})
    visited: list[str] = []

    def iterate() -> None:
        visited.extend(key for batch in first.iter_batches(batch_size=3) for key in batch)

    def write() -> None:
        for i in range(NUM_WRITES):
            second.set(f"other-{i}", {})
            second.set(stable[i], {"updated": True})
            second.delete(f"other-{i - 1}")

    run_in_threads(iterate, write)
    assert sorted(key for key in visited if key.startswith("stable")) == stable


###################################
#     Tests for event loops       #
###################################


async def write_concurrently(store: PostgresStore, prefix: str) -> None:
    r"""Write several keys with concurrent ``aset`` calls."""
    await asyncio.gather(*(store.aset(f"{prefix}-{i}", {}) for i in range(NUM_WRITES)))


def test_async_use_in_two_event_loops(table: str) -> None:
    r"""Test that a store used with ``asyncio.run``, without ``aclose``,
    can be used in another event loop (regression test: the connection of
    the first loop was used again)."""
    with create_store(table) as store:
        asyncio.run(write_concurrently(store, "first"))
        asyncio.run(write_concurrently(store, "second"))
        assert store.count() == 2 * NUM_WRITES


def test_two_event_loops_in_two_threads(table: str) -> None:
    r"""Test that two event loops that run at the same time in two
    threads share a store."""
    barrier = threading.Barrier(2)

    async def write(store: PostgresStore, prefix: str) -> None:
        for i in range(NUM_WRITES):
            await store.aset("a", {f"{prefix}-{i}": i}, on_conflict="merge")
            # Both loops are running here, each with its connection.
            barrier.wait(timeout=TIMEOUT)

    with create_store(table) as store:
        with ThreadPoolExecutor(2) as executor:
            list(executor.map(lambda prefix: asyncio.run(write(store, prefix)), "ab"))
        assert len(store.get("a")) == 2 * NUM_WRITES
