r"""Concurrency tests of the SQL stores: several writers of the same
database (threads, tasks, instances and processes).

Each test uses two stores on the same data, so no lock of an instance
protects the writes: only the database, or the lock that the stores
share, does.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import DuckDBStore, PickleCodec, SQLiteStore
from persista.testing.fixtures import duckdb_available

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from persista.store import BaseStore

NUM_WRITES = 100
NUM_TRIALS = 100

# Long enough that a writer never gives up while the others write.
TIMEOUT = 60.0

Stores = tuple["BaseStore", "BaseStore"]

# Held while a thread records a result in a list or dict of a test.
RESULTS_LOCK = threading.Lock()


def sqlite_file(path: Path) -> BaseStore:
    r"""Return a store of a SQLite file."""
    return SQLiteStore(path / "data.sqlite", timeout=TIMEOUT)


def sqlite_pickle(path: Path) -> BaseStore:
    r"""Return a store of a SQLite file with the pickle codec."""
    return SQLiteStore(path / "data.sqlite", codec=PickleCodec(), timeout=TIMEOUT)


def sqlite_shared_cache(path: Path) -> BaseStore:
    r"""Return a store of an in-memory database that uses a shared
    cache."""
    return SQLiteStore(f"file:{path.name}?mode=memory&cache=shared", uri=True)


def duckdb_file(path: Path) -> BaseStore:
    r"""Return a store of a DuckDB file."""
    return DuckDBStore(path / "data.duckdb")


FACTORIES = [
    pytest.param(sqlite_file, id="sqlite"),
    pytest.param(sqlite_pickle, id="sqlite_pickle"),
    pytest.param(sqlite_shared_cache, id="sqlite_shared_cache"),
    pytest.param(duckdb_file, id="duckdb", marks=duckdb_available),
]


@pytest.fixture(params=FACTORIES)
def stores(request: pytest.FixtureRequest, tmp_path: Path) -> Generator[Stores, None, None]:
    r"""Return two open stores of the same data."""
    with request.param(tmp_path) as first, request.param(tmp_path) as second:
        yield first, second


def run_in_threads(*functions: Callable[[], Any]) -> None:
    r"""Run functions at the same time, each in a thread, and raise the
    first error."""
    barrier = threading.Barrier(len(functions))

    def run(function: Callable[[], Any]) -> None:
        barrier.wait()
        function()

    with ThreadPoolExecutor(len(functions)) as executor:
        list(executor.map(run, functions))


def try_to_create(store: BaseStore, key: str, writer: str, winners: list[tuple[str, str]]) -> None:
    r"""Write a key with ``raise`` and record the writer if it
    succeeds."""
    try:
        store.set(key, {"writer": writer}, on_conflict="raise")
    except KeyError:
        return
    with RESULTS_LOCK:
        winners.append((key, writer))


async def atry_to_create(
    store: BaseStore, key: str, writer: str, winners: list[tuple[str, str]]
) -> None:
    r"""Async equivalent of ``try_to_create``."""
    try:
        await store.aset(key, {"writer": writer}, on_conflict="raise")
    except KeyError:
        return
    with RESULTS_LOCK:
        winners.append((key, writer))


def merge_fields(store: BaseStore, prefix: str, key: str = "a") -> None:
    r"""Add ``NUM_WRITES`` fields to a value, one merge per field."""
    for i in range(NUM_WRITES):
        store.set(key, {f"{prefix}-{i}": i}, on_conflict="merge")


async def amerge_fields(store: BaseStore, prefix: str) -> None:
    r"""Async equivalent of ``merge_fields``, with concurrent tasks."""
    await asyncio.gather(
        *(store.aset("a", {f"{prefix}-{i}": i}, on_conflict="merge") for i in range(NUM_WRITES))
    )


def read(store: BaseStore) -> None:
    r"""Read a store several times, with every kind of read."""
    for _ in range(NUM_WRITES):
        store.get("a")
        store.filter()
        list(store.keys())
        store.count()


#########################################
#     Tests for concurrent writes     #
#########################################


def test_raise_succeeds_for_one_instance_only(stores: Stores) -> None:
    r"""Test that of two instances that create the same key with
    ``raise``, exactly one succeeds, and its value is kept."""
    winners: list[tuple[str, str]] = []
    keys = [str(i) for i in range(NUM_TRIALS)]
    barrier = threading.Barrier(2)

    def write(store: BaseStore, writer: str) -> None:
        for key in keys:
            barrier.wait(timeout=TIMEOUT)
            try_to_create(store, key, writer, winners)

    run_in_threads(lambda: write(stores[0], "first"), lambda: write(stores[1], "second"))
    assert sorted(winners) == sorted((key, stores[0].get(key)["writer"]) for key in keys)


def test_skip_keeps_the_value_of_one_instance(stores: Stores) -> None:
    r"""Test that two instances that write the same keys with ``skip``
    never replace the value written first."""
    seen: dict[str, str] = {}
    keys = [str(i) for i in range(NUM_TRIALS)]

    def write(store: BaseStore, writer: str) -> None:
        for key in keys:
            store.set(key, {"writer": writer}, on_conflict="skip")
            # The value read after a write must never change afterwards.
            read_writer = store.get(key)["writer"]
            with RESULTS_LOCK:
                seen[f"{writer}-{key}"] = read_writer

    run_in_threads(lambda: write(stores[0], "first"), lambda: write(stores[1], "second"))
    assert [seen[f"first-{key}"] for key in keys] == [seen[f"second-{key}"] for key in keys]


def test_merge_does_not_lose_updates_of_two_instances(stores: Stores) -> None:
    r"""Test that concurrent merges of two instances keep every
    field."""
    run_in_threads(
        *(lambda s=s, p=p: merge_fields(s, p) for s, p in zip(stores, "ab", strict=True))
    )
    assert len(stores[0].get("a")) == 2 * NUM_WRITES


def test_merge_several_keys_of_two_instances(stores: Stores) -> None:
    r"""Test that concurrent merges of several keys at once keep every
    field."""

    def write(store: BaseStore, prefix: str) -> None:
        for i in range(NUM_WRITES):
            items = {key: {f"{prefix}-{i}": i} for key in ("a", "b", "c")}
            store.set_many(items, on_conflict="merge")

    run_in_threads(lambda: write(stores[0], "x"), lambda: write(stores[1], "y"))
    assert [len(value) for value in stores[0].get_many(["a", "b", "c"])] == [2 * NUM_WRITES] * 3


@pytest.mark.parametrize("instances", [(0, 0), (0, 1)], ids=["one_instance", "two_instances"])
async def test_merge_does_not_lose_updates_of_set_and_aset(
    stores: Stores, instances: tuple[int, int]
) -> None:
    r"""Test that merges from ``set`` in a thread and from ``aset``
    tasks keep every field."""
    sync_store, async_store = stores[instances[0]], stores[instances[1]]
    await asyncio.gather(
        asyncio.to_thread(merge_fields, sync_store, "sync"), amerge_fields(async_store, "async")
    )
    assert len(stores[0].get("a")) == 2 * NUM_WRITES


@pytest.mark.parametrize("instances", [(0, 0), (0, 1)], ids=["one_instance", "two_instances"])
async def test_raise_succeeds_once_with_set_and_aset(
    stores: Stores, instances: tuple[int, int]
) -> None:
    r"""Test that of a ``set`` and an ``aset`` that create the same key
    with ``raise``, exactly one succeeds."""
    sync_store, async_store = stores[instances[0]], stores[instances[1]]
    winners: list[tuple[str, str]] = []
    keys = [str(i) for i in range(NUM_TRIALS)]
    for key in keys:
        await asyncio.gather(
            asyncio.to_thread(try_to_create, sync_store, key, "sync", winners),
            atry_to_create(async_store, key, "async", winners),
        )
    assert sorted(winners) == sorted((key, stores[0].get(key)["writer"]) for key in keys)


def test_merge_with_concurrent_overwrite_and_delete(stores: Stores) -> None:
    r"""Test that merges that run with the overwrites and deletes of
    another instance never bring back a field that was removed."""
    first, second = stores

    def replace() -> None:
        for i in range(NUM_WRITES):
            second.set("a", {f"old-{i}": True})
            second.delete("a")
            second.set_many({"a": {f"old-{i}": True}, "b": {}})
            second.clear()
        second.set("a", {"last": True})

    run_in_threads(lambda: merge_fields(first, "merged"), replace)
    assert [field for field in first.get("a") if field.startswith("old")] == []


def test_skip_and_raise_with_concurrent_delete(stores: Stores) -> None:
    r"""Test that conditional writes that run with the deletes of
    another instance do not fail."""
    first, second = stores

    def create() -> None:
        for i in range(NUM_WRITES):
            first.set("a", {"i": i}, on_conflict="skip")
            try_to_create(first, "a", "first", [])

    def delete() -> None:
        for _ in range(NUM_WRITES):
            second.delete("a")
            second.set("a", {})
            second.delete_many(["a", "b"])

    run_in_threads(create, delete)
    assert first.count() <= 1


def test_reads_during_writes_of_another_instance(stores: Stores) -> None:
    r"""Test that one instance reads while another one writes and
    deletes."""
    first, second = stores

    def write() -> None:
        for i in range(NUM_WRITES):
            second.set_many({"a": {"i": i}, "b": {"i": i}})
            second.set("a", {"j": i}, on_conflict="merge")
            second.delete("a")

    run_in_threads(lambda: read(first), write)
    assert first.get_many(["a", "b"]) == [None, {"i": NUM_WRITES - 1}]


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


@pytest.mark.parametrize("factory", FACTORIES)
def test_async_use_in_two_event_loops(factory: Callable[[Path], BaseStore], tmp_path: Path) -> None:
    r"""Test that two stores whose async calls waited for each other in
    one event loop can be used in another one."""
    with factory(tmp_path) as first, factory(tmp_path) as second:

        async def write(prefix: str) -> None:
            await asyncio.gather(
                amerge_fields(first, f"{prefix}-first"), amerge_fields(second, f"{prefix}-second")
            )

        asyncio.run(write("loop1"))
        asyncio.run(write("loop2"))
        assert len(first.get("a")) == 4 * NUM_WRITES


@pytest.mark.parametrize("factory", FACTORIES)
def test_reopen_in_another_event_loop(factory: Callable[[Path], BaseStore], tmp_path: Path) -> None:
    r"""Test that a store opened and closed with ``async with`` can be
    used again in another event loop."""
    store = factory(tmp_path)

    async def write(field: str) -> dict:
        async with store:
            await store.aset("a", {field: 1}, on_conflict="merge")
            return await store.aget("a")

    asyncio.run(write("first"))
    assert "second" in asyncio.run(write("second"))


@pytest.mark.parametrize("factory", FACTORIES)
def test_open_the_same_new_database_at_the_same_time(
    factory: Callable[[Path], BaseStore], tmp_path: Path
) -> None:
    r"""Test that instances that create the table of a new database at
    the same time all open."""
    opened = [factory(tmp_path) for _ in range(4)]
    run_in_threads(*(store.open for store in opened))
    count = sum(not store.closed for store in opened)
    for store in opened:
        store.close()
    assert count == 4


def merge_in_process(path: str, prefix: str) -> None:
    r"""Merge fields into a value of a SQLite file, from a new
    process."""
    with SQLiteStore(path, timeout=TIMEOUT) as store:
        merge_fields(store, prefix)


def test_merge_does_not_lose_updates_of_two_processes(tmp_path: Path) -> None:
    r"""Test that concurrent merges of two processes into a SQLite file
    keep every field."""
    path = str(tmp_path / "data.sqlite")
    with SQLiteStore(path):
        pass
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(2, mp_context=context) as executor:
        futures = [executor.submit(merge_in_process, path, prefix) for prefix in ("a", "b")]
        merge_in_process(path, "main")
        for future in futures:
            future.result(timeout=TIMEOUT)
    with SQLiteStore(path) as store:
        assert len(store.get("a")) == 3 * NUM_WRITES
