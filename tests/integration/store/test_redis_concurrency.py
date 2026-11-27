r"""Concurrency tests of :class:`~persista.store.RedisStore` with a real
server: several writers of the same namespace (threads, tasks and
instances).

Each test uses two stores on the same namespace, so only the server
protects the writes.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import uuid
from collections import Counter
from typing import TYPE_CHECKING

import pytest

from persista.store import PickleCodec, RedisStore
from persista.testing.fixtures import redis_available
from tests.integration.store.redis_helpers import (
    REDIS_URL,
    delete_namespaces,
    redis_server_available,
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

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator

    from persista.store import Codec

pytestmark = [redis_available, redis_server_available]

# The prefix of the namespaces of this module.
PREFIX = f"persista-concurrency-{uuid.uuid4().hex}"

# More than the writes of a writer, so that all can be in progress.
MAX_CONNECTIONS = 2 * NUM_WRITES + 10

Stores = tuple[RedisStore, RedisStore]


@pytest.fixture(scope="module", autouse=True)
def _cleanup() -> Generator[None, None, None]:
    r"""Remove the data of the tests from the server."""
    yield
    delete_namespaces(PREFIX)


@pytest.fixture(params=[None, PickleCodec()], ids=["json", "pickle"])
def stores(request: pytest.FixtureRequest) -> Generator[Stores, None, None]:
    r"""Return two open stores of the same namespace."""
    codec: Codec | None = request.param
    namespace = f"{PREFIX}-{uuid.uuid4().hex}"

    def create() -> RedisStore:
        return RedisStore(
            REDIS_URL, codec=codec, namespace=namespace, max_connections=MAX_CONNECTIONS
        )

    with create() as first, create() as second:
        yield first, second


@pytest.fixture
async def astores(stores: Stores) -> AsyncGenerator[Stores]:
    r"""Return two open stores, and close their async clients."""
    yield stores
    for store in stores:
        await store.aclose()


def stored_keys(store: RedisStore) -> tuple[list[str], list[str]]:
    r"""Return the keys listed in the set of a namespace, and the keys
    that have a value on the server."""
    prefix = f"{store.namespace}:v:"
    names = store.client.scan_iter(match=f"{prefix}*", count=1000)
    return sorted(store.keys()), sorted(name.decode().removeprefix(prefix) for name in names)


def replace_values(store: RedisStore) -> None:
    r"""Overwrite, delete and clear a value several times."""
    for i in range(NUM_WRITES):
        store.set("a", {f"old-{i}": True})
        store.delete("a")
        store.set_many({"a": {f"old-{i}": True}, "b": {}})
        store.clear()
    store.set("a", {"last": True})


async def areplace_values(store: RedisStore) -> None:
    r"""Async equivalent of ``replace_values``."""
    for i in range(NUM_WRITES):
        await store.aset("a", {f"old-{i}": True})
        await store.adelete("a")
        await store.aset_many({"a": {f"old-{i}": True}, "b": {}})
        await store.aclear()
    await store.aset("a", {"last": True})


#########################################
#     Tests for concurrent writes     #
#########################################


def test_raise_succeeds_for_one_instance_only(stores: Stores) -> None:
    r"""Test that of two instances that create the same key with
    ``raise``, exactly one succeeds, and its value is kept."""
    winners: list[tuple[str, str]] = []
    keys = [str(i) for i in range(NUM_TRIALS)]
    barrier = threading.Barrier(2)

    def write(store: RedisStore, writer: str) -> None:
        for key in keys:
            barrier.wait(timeout=60)
            try_to_create(store, key, writer, winners)

    run_in_threads(lambda: write(stores[0], "first"), lambda: write(stores[1], "second"))
    assert sorted(winners) == sorted((key, stores[0].get(key)["writer"]) for key in keys)


async def test_raise_succeeds_for_one_task_only(astores: Stores) -> None:
    r"""Test that of the concurrent ``aset`` calls of two instances that
    create the same key with ``raise``, exactly one succeeds."""
    winners: list[tuple[str, str]] = []
    await asyncio.gather(
        *(atry_to_create(astores[i % 2], "a", str(i), winners) for i in range(NUM_WRITES))
    )
    assert winners == [("a", astores[0].get("a")["writer"])]


def test_raise_with_several_keys_writes_all_or_nothing(stores: Stores) -> None:
    r"""Test that instances that create overlapping keys with ``raise``
    never write only a part of their keys."""
    keys = [str(i) for i in range(NUM_TRIALS + 1)]
    barrier = threading.Barrier(2)

    def write(store: RedisStore, offset: int) -> None:
        for i in range(offset, NUM_TRIALS, 2):
            barrier.wait(timeout=60)
            items = {key: {"writer": i} for key in keys[i : i + 2]}
            with contextlib.suppress(KeyError):
                store.set_many(items, on_conflict="raise")

    run_in_threads(lambda: write(stores[0], 0), lambda: write(stores[1], 1))
    writers = Counter(value["writer"] for value in stores[0].get_many(keys) if value is not None)
    # Every successful write has both of its keys.
    assert set(writers.values()) == {2}


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

    def write(store: RedisStore, prefix: str) -> None:
        for i in range(NUM_WRITES):
            items = {key: {f"{prefix}-{i}": i} for key in ("a", "b", "c")}
            store.set_many(items, on_conflict="merge")

    run_in_threads(lambda: write(stores[0], "x"), lambda: write(stores[1], "y"))
    assert [len(value) for value in stores[0].get_many(["a", "b", "c"])] == [2 * NUM_WRITES] * 3


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


def test_merge_with_concurrent_overwrite_and_delete(stores: Stores) -> None:
    r"""Test that merges that run with the overwrites, deletes and
    clears of another instance never bring back a field that was
    removed."""
    first, second = stores
    run_in_threads(lambda: merge_fields(first, "merged"), lambda: replace_values(second))
    assert [field for field in first.get("a") if field.startswith("old")] == []


async def test_amerge_with_concurrent_overwrite_and_delete(astores: Stores) -> None:
    r"""Test that async merges that run with the async overwrites,
    deletes and clears of another instance never bring back a field that
    was removed."""
    first, second = astores
    await asyncio.gather(amerge_fields(first, "merged"), areplace_values(second))
    assert [field for field in await first.aget("a") if field.startswith("old")] == []


@pytest.mark.parametrize(
    "delete",
    [
        pytest.param(lambda s: s.delete_many(["a", "b"]), id="delete"),
        pytest.param(lambda s: s.clear(), id="clear"),
    ],
)
def test_keys_set_stays_consistent_with_the_values(
    stores: Stores, delete: Callable[[RedisStore], None]
) -> None:
    r"""Test that concurrent writes, deletes and clears leave the set of
    the keys with exactly the keys that have a value."""
    first, second = stores

    def write() -> None:
        for i in range(NUM_WRITES):
            first.set("a", {"i": i}, on_conflict="skip")
            first.set_many({f"key-{i}": {}, "b": {}})
            first.set(f"other-{i}", {}, on_conflict="raise")

    def remove() -> None:
        for i in range(NUM_WRITES):
            delete(second)
            second.set(f"second-{i}", {})

    run_in_threads(write, remove)
    listed, stored = stored_keys(first)
    assert listed == stored


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
