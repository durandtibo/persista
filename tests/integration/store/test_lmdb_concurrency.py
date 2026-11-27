r"""Concurrency tests of ``LmdbStore``: several writers of the same
environment.

LMDB cannot open a path twice in one process, so the writers that use
two stores are two processes. The writers of one process (threads and
tasks) share one store; ``test_contract.py`` tests them too.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import threading
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING

from persista.store import LmdbStore
from persista.testing.fixtures import lmdb_available
from persista.utils.imports import is_lmdb_available

if is_lmdb_available():
    import lmdb

if TYPE_CHECKING:
    from collections.abc import Callable
    from multiprocessing.synchronize import Barrier
    from pathlib import Path

pytestmark = lmdb_available

NUM_WRITES = 100
NUM_TRIALS = 100
MAP_SIZE = 2**26
TIMEOUT = 60.0


def open_store(path: Path) -> LmdbStore:
    r"""Return a store of the environment of a test."""
    return LmdbStore(path, map_size=MAP_SIZE)


def merge_fields(path: str, writer: str, barrier: Barrier) -> None:
    r"""Merge fields into one value, from another process."""
    with LmdbStore(path, map_size=MAP_SIZE) as store:
        barrier.wait(timeout=TIMEOUT)
        for i in range(NUM_WRITES):
            store.set("a", {f"{writer}-{i}": i}, on_conflict="merge")


def claim_keys(path: str, writer: str, barrier: Barrier) -> list[str]:
    r"""Write keys with ``raise``, from another process, and return the
    keys whose write succeeded."""
    won: list[str] = []
    with LmdbStore(path, map_size=MAP_SIZE) as store:
        barrier.wait(timeout=TIMEOUT)
        for i in range(NUM_TRIALS):
            try:
                store.set(str(i), {"writer": writer}, on_conflict="raise")
            except KeyError:
                continue
            won.append(str(i))
    return won


def replace_and_delete(path: str, writer: str, barrier: Barrier) -> None:
    r"""Overwrite and delete one value, from another process."""
    del writer
    with LmdbStore(path, map_size=MAP_SIZE) as store:
        barrier.wait(timeout=TIMEOUT)
        for _ in range(NUM_WRITES):
            store.set("a", {"old": True})
            store.delete("a")
        store.set("a", {"last": True})


def open_twice(path: str) -> str:
    r"""Open a second store of a path that this process has open, and
    return the error."""
    with LmdbStore(path, map_size=MAP_SIZE):
        try:
            LmdbStore(path, map_size=MAP_SIZE).open()
        except lmdb.Error as exc:
            return str(exc)
    return ""


def run_in_processes(path: Path, *functions: Callable) -> list:
    r"""Run functions at the same time, each in a process, and return
    their results."""
    context = multiprocessing.get_context("spawn")
    with (
        context.Manager() as manager,
        ProcessPoolExecutor(len(functions), mp_context=context) as executor,
    ):
        barrier = manager.Barrier(len(functions))
        futures = [
            executor.submit(function, str(path), f"writer{i}", barrier)
            for i, function in enumerate(functions)
        ]
        return [future.result(timeout=TIMEOUT) for future in futures]


#############################
#     Several processes     #
#############################


def test_merge_does_not_lose_updates_of_two_processes(tmp_path: Path) -> None:
    r"""Test that concurrent merges of two processes keep every
    field."""
    run_in_processes(tmp_path, merge_fields, merge_fields)
    with open_store(tmp_path) as store:
        assert len(store.get("a")) == 2 * NUM_WRITES


def test_raise_succeeds_for_one_process_only(tmp_path: Path) -> None:
    r"""Test that each key written with ``raise`` by two processes is
    written by exactly one of them."""
    first, second = run_in_processes(tmp_path, claim_keys, claim_keys)
    assert sorted(first + second, key=int) == [str(i) for i in range(NUM_TRIALS)]


def test_merge_with_overwrite_and_delete_of_another_process(tmp_path: Path) -> None:
    r"""Test that a merge never brings back a field that another process
    removed before it."""
    run_in_processes(tmp_path, merge_fields, replace_and_delete)
    with open_store(tmp_path) as store:
        assert "old" not in store.get("a")


def test_open_store_reads_the_writes_of_another_process(tmp_path: Path) -> None:
    r"""Test that an open store sees what another process writes."""
    context = multiprocessing.get_context("spawn")
    with (
        open_store(tmp_path) as store,
        context.Manager() as manager,
        ProcessPoolExecutor(1, mp_context=context) as executor,
    ):
        executor.submit(merge_fields, str(tmp_path), "other", manager.Barrier(1)).result(
            timeout=TIMEOUT
        )
        assert len(store.get("a")) == NUM_WRITES


#######################
#     One process     #
#######################


def test_second_store_of_a_path_cannot_be_opened(tmp_path: Path) -> None:
    r"""Test that LMDB refuses to open a path twice in one process."""
    assert "already open in this process" in open_twice(str(tmp_path))


def test_path_can_be_opened_after_close(tmp_path: Path) -> None:
    r"""Test that a path can be opened again once the first store is
    closed."""
    with open_store(tmp_path) as store:
        store.set("a", {})
    with open_store(tmp_path) as store:
        assert store.contains("a")


async def test_raise_succeeds_once_with_set_and_aset(tmp_path: Path) -> None:
    r"""Test that, of a ``set`` in a thread and an ``aset`` of the same
    key with ``raise``, exactly one succeeds."""
    errors: list[str] = []
    lock = threading.Lock()

    def write(store: LmdbStore, key: str) -> None:
        try:
            store.set(key, {}, on_conflict="raise")
        except KeyError:
            with lock:
                errors.append(key)

    async def awrite(store: LmdbStore, key: str) -> None:
        try:
            await store.aset(key, {}, on_conflict="raise")
        except KeyError:
            with lock:
                errors.append(key)

    with open_store(tmp_path) as store:
        for i in range(NUM_TRIALS):
            await asyncio.gather(asyncio.to_thread(write, store, str(i)), awrite(store, str(i)))
    assert sorted(errors, key=int) == [str(i) for i in range(NUM_TRIALS)]


def test_close_while_threads_use_the_store(tmp_path: Path) -> None:
    r"""Test that closing a store that other threads read and write
    gives them a ``RuntimeError``."""
    store = open_store(tmp_path)
    store.open()
    started = threading.Event()
    errors: list[str] = []
    lock = threading.Lock()

    def use() -> None:
        try:
            while True:
                store.set("a", {})
                store.get("a")
                list(store.keys())
                started.set()
        except RuntimeError as exc:
            with lock:
                errors.append(str(exc))

    threads = [threading.Thread(target=use) for _ in range(4)]
    for thread in threads:
        thread.start()
    started.wait(timeout=TIMEOUT)
    store.close()
    for thread in threads:
        thread.join(timeout=TIMEOUT)
    assert ["is not open" in error for error in errors] == [True] * 4
