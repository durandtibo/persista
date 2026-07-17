r"""Consistency tests across every ``AsyncBaseStore`` implementation.

Each concrete async store (:class:`~persista.store.AsyncInMemoryStore`,
:class:`~persista.store.AsyncSQLiteStore`,
:class:`~persista.store.AsyncTypedSQLiteStore`,
:class:`~persista.store.AsyncRedisStore`,
:class:`~persista.store.AsyncPickleRedisStore`) is expected to implement
the exact same behavior for the :class:`~persista.store.AsyncBaseStore`
contract. The tests below are parametrized over every available backend
(stores whose optional dependency is missing, or whose server is
unreachable, are skipped rather than omitted) so that a single test body
runs -- and must pass -- identically for every implementation.

Mirrors ``test_consistency.py``, but for the async store hierarchy.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import pytest

from persista.store import (
    AsyncBaseRedisStore,
    AsyncBaseStore,
    AsyncInMemoryStore,
    AsyncPickleRedisStore,
    AsyncRedisStore,
    AsyncSQLiteStore,
    AsyncTypedSQLiteStore,
)
from persista.utils.imports import is_aiosqlite_available, is_redis_available
from tests.integration.store.redis_helpers import REDIS_URL, redis_server_reachable


def _is_redis_store(store: AsyncBaseStore) -> bool:
    return is_redis_available() and isinstance(store, AsyncBaseRedisStore)


def _store_factories() -> list[pytest.mark.ParameterSet]:
    r"""Return one ``pytest.param`` per async store backend.

    Each param wraps a zero-argument factory that creates a fresh, empty
    store instance. Stores whose optional dependency is not installed
    (SQLite driver, Redis), or whose server is unreachable (Redis), are
    marked as skipped rather than omitted, so they are still visible (as
    skips) in `pytest -k`/reports.
    """
    aiosqlite_skip = pytest.mark.skipif(not is_aiosqlite_available(), reason="Requires aiosqlite")
    redis_skip = pytest.mark.skipif(
        not redis_server_reachable(), reason="Requires a reachable Redis server"
    )
    return [
        pytest.param(AsyncInMemoryStore, id="in_memory"),
        pytest.param(lambda: AsyncSQLiteStore(":memory:"), id="sqlite", marks=aiosqlite_skip),
        pytest.param(
            lambda: AsyncTypedSQLiteStore(":memory:"),
            id="sqlite_typed",
            marks=aiosqlite_skip,
        ),
        pytest.param(lambda: AsyncRedisStore(REDIS_URL), id="redis", marks=redis_skip),
        pytest.param(lambda: AsyncPickleRedisStore(REDIS_URL), id="pickle_redis", marks=redis_skip),
    ]


@pytest.fixture(params=_store_factories())
async def store(request: pytest.FixtureRequest) -> AsyncGenerator[AsyncBaseStore, None]:
    async with request.param() as store:
        # AsyncRedisStore/AsyncPickleRedisStore have no per-test namespace,
        # so a shared server must be cleared before/after each test to keep
        # tests isolated.
        if _is_redis_store(store):
            await store.delete_many([key async for key in store.keys()])  # noqa: SIM118
        yield store
        if _is_redis_store(store):
            await store.delete_many([key async for key in store.keys()])  # noqa: SIM118


@pytest.fixture(scope="module")
def items() -> dict[str, dict[str, Any]]:
    return {
        "1": {
            "title": "Intro to Python",
            "author": "Alice",
            "year": 2022,
            "category": "Programming",
        },
        "2": {
            "title": "Advanced Python",
            "author": "Alice",
            "year": 2023,
            "category": "Programming",
        },
        "3": {"title": "History of Rome", "author": "Bob", "year": 2021, "category": "History"},
        "4": {"title": "History of Greece", "author": "Bob", "year": 2020, "category": "History"},
    }


#####################################################
#     Consistency tests for AsyncBaseStore API       #
#####################################################


# --- get / set ---


async def test_get_missing_key_returns_none(store: AsyncBaseStore) -> None:
    assert await store.get("nonexistent") is None


async def test_set_then_get_round_trips(store: AsyncBaseStore) -> None:
    await store.set("1", {"text": "hello", "n": 1})
    assert await store.get("1") == {"text": "hello", "n": 1}


async def test_set_default_overwrites_existing(store: AsyncBaseStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"})
    assert await store.get("1") == {"text": "updated"}
    assert await store.count() == 1


async def test_set_on_conflict_raise(store: AsyncBaseStore) -> None:
    await store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        await store.set("1", {"text": "updated"}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}


async def test_set_on_conflict_skip(store: AsyncBaseStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}


async def test_set_on_conflict_overwrite(store: AsyncBaseStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert await store.get("1") == {"text": "updated"}


async def test_set_on_conflict_merge(store: AsyncBaseStore) -> None:
    await store.set("1", {"text": "original", "author": "Alice"})
    await store.set("1", {"text": "updated"}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


async def test_set_on_conflict_invalid_raises(store: AsyncBaseStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- get_many ---


async def test_get_many_preserves_order(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.get_many(["3", "1", "2"]) == [items["3"], items["1"], items["2"]]


async def test_get_many_returns_none_for_missing(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["1", "99", "2"])
    assert result[1] is None


async def test_get_many_empty_list_returns_empty_list(store: AsyncBaseStore) -> None:
    assert await store.get_many([]) == []


# --- set_many ---


async def test_set_many_increases_count(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


async def test_set_many_empty_is_no_op(store: AsyncBaseStore) -> None:
    await store.set_many({})
    assert await store.count() == 0


async def test_set_many_on_conflict_raise(store: AsyncBaseStore) -> None:
    await store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        await store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("3") is None


async def test_set_many_on_conflict_skip(store: AsyncBaseStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("2") == {"text": "new"}


async def test_set_many_on_conflict_merge(store: AsyncBaseStore) -> None:
    await store.set_many({"1": {"text": "original", "author": "Alice"}})
    await store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


# --- set_batches ---


async def test_set_batches_writes_all_pairs(store: AsyncBaseStore) -> None:
    await store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert await store.count() == 3
    assert await store.get("2") == {"v": 2}


async def test_set_batches_empty_is_no_op(store: AsyncBaseStore) -> None:
    await store.set_batches([])
    assert await store.count() == 0


# --- filter ---


async def test_filter_no_args_returns_all(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.filter()) == len(items)


async def test_filter_single_field(store: AsyncBaseStore, items: dict[str, dict[str, Any]]) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


async def test_filter_multiple_fields(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.filter(author="Alice", category="Programming")) == 2


async def test_filter_no_match_returns_empty(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.filter(author="Charlie") == []


async def test_filter_integer_field_value(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


async def test_filter_empty_store_returns_empty(store: AsyncBaseStore) -> None:
    assert await store.filter(author="Alice") == []


# --- delete / delete_many ---


async def test_delete_removes_value(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete("1")
    assert await store.count() == len(items) - 1
    assert await store.get("1") is None


async def test_delete_nonexistent_is_silent(store: AsyncBaseStore) -> None:
    await store.delete("nonexistent")


async def test_delete_many_removes_values(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["1", "3"])
    assert await store.count() == len(items) - 2
    assert await store.get("1") is None
    assert await store.get("3") is None


async def test_delete_many_empty_list_is_no_op(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many([])
    assert await store.count() == len(items)


async def test_delete_many_nonexistent_keys_are_silent(store: AsyncBaseStore) -> None:
    await store.delete_many(["99", "100"])


# --- contains_many ---


async def test_contains_many_mixed(store: AsyncBaseStore, items: dict[str, dict[str, Any]]) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["1", "99", "3", "42"])
    assert sorted(found) == ["1", "3"]
    assert sorted(missing) == ["42", "99"]


async def test_contains_many_empty_input_returns_empty_lists(store: AsyncBaseStore) -> None:
    assert await store.contains_many([]) == ([], [])


async def test_contains_many_empty_store_returns_all_missing(store: AsyncBaseStore) -> None:
    found, missing = await store.contains_many(["1", "2"])
    assert found == []
    assert sorted(missing) == ["1", "2"]


# --- keys / values ---


async def test_keys_empty_store_yields_nothing(store: AsyncBaseStore) -> None:
    assert [key async for key in store.keys()] == []  # noqa: SIM118


async def test_keys_returns_all_keys(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [key async for key in store.keys()]  # noqa: SIM118
    assert sorted(result) == sorted(items.keys())


async def test_values_returns_all_values(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [value async for value in store.values()]
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


# --- iter_batches ---


async def test_iter_batches_empty_store_yields_nothing(store: AsyncBaseStore) -> None:
    assert [batch async for batch in store.iter_batches()] == []


async def test_iter_batches_returns_async_generator(store: AsyncBaseStore) -> None:
    assert isinstance(store.iter_batches(), AsyncIterator)


async def test_iter_batches_returns_all_key_value_pairs(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    async for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


async def test_iter_batches_yields_correct_batch_sizes(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=2)]
    assert sorted(len(b) for b in batches) == [2, 2]


async def test_iter_batches_zero_batch_size_raises(store: AsyncBaseStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.iter_batches(batch_size=0):
            pass


# --- count ---


async def test_count_empty_store(store: AsyncBaseStore) -> None:
    assert await store.count() == 0


async def test_count_after_set_many(
    store: AsyncBaseStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


# --- close / context manager ---


async def test_close_is_idempotent(store: AsyncBaseStore) -> None:
    await store.close()
    await store.close()  # should not raise


async def test_close_returns_none(store: AsyncBaseStore) -> None:
    assert await store.close() is None


async def test_context_manager_usable_for_reads_and_writes(store: AsyncBaseStore) -> None:
    await store.set_many(
        {
            "1": {"text": "hello", "author": "Alice"},
            "2": {"text": "world", "author": "Bob"},
        }
    )
    assert await store.count() == 2
    result = await store.filter(author="Alice")
    assert result[0]["text"] == "hello"
    await store.delete("1")
    assert await store.count() == 1


#########################################################
#     Cross-store comparisons in a single test           #
#########################################################

# The tests above run the exact same body once per backend (parametrized
# fixture), which is the main way this suite catches a backend that
# behaves differently. The test below goes one step further and compares
# every available backend's output *against each other* directly, within
# a single test, for a representative end-to-end workflow.


async def _all_available_stores() -> AsyncGenerator[tuple[str, AsyncBaseStore], None]:
    for factory_param in _store_factories():
        (factory,) = factory_param.values
        store_id = factory_param.id
        skip_marks = [m for m in factory_param.marks if m.name == "skipif"]
        if any(mark.args[0] for mark in skip_marks):
            continue
        store: AsyncBaseStore = factory()
        if _is_redis_store(store):
            await store.delete_many([key async for key in store.keys()])  # noqa: SIM118
        yield store_id, store


async def test_cross_store_outputs_are_identical(items: dict[str, dict[str, Any]]) -> None:
    results: dict[str, Any] = {}
    stores: list[AsyncBaseStore] = []
    try:
        async for store_id, store in _all_available_stores():
            stores.append(store)
            await store.set_many(items)
            await store.set("5", {"title": "Cooking Basics", "author": "Alice", "category": "Food"})
            await store.delete("5")
            await store.set("1", {**items["1"], "year": 2099}, on_conflict="merge")

            results[store_id] = {
                "count": await store.count(),
                "get_1": await store.get("1"),
                "get_missing": await store.get("nonexistent"),
                "get_many": await store.get_many(["3", "1", "99"]),
                "filter_alice": sorted(
                    (v["title"] for v in await store.filter(author="Alice")),
                ),
                "filter_none": await store.filter(author="Charlie"),
                "contains_many": await store.contains_many(["1", "99", "3"]),
                "keys": sorted([key async for key in store.keys()]),  # noqa: SIM118
                "values_titles": sorted([v["title"] async for v in store.values()]),
            }
    finally:
        for store in stores:
            if _is_redis_store(store):
                await store.delete_many([key async for key in store.keys()])  # noqa: SIM118
            await store.close()

    assert len(results) >= 2, "Need at least two available stores to compare"
    reference_id, reference = next(iter(results.items()))
    for store_id, result in results.items():
        assert result == reference, (
            f"Store {store_id!r} produced a different result than {reference_id!r}: "
            f"{result} != {reference}"
        )
