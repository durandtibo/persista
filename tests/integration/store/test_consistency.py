r"""Consistency tests across every ``BaseStore`` implementation.

Each concrete store (:class:`~persista.store.InMemoryStore`,
:class:`~persista.store.SQLiteStore`, :class:`~persista.store.DuckDBStore`,
:class:`~persista.store.RedisStore`,
:class:`~persista.store.PickleRedisStore`) is expected to implement the
exact same behavior for the :class:`~persista.store.BaseStore` contract.
The tests below are parametrized over every available backend (stores
whose optional dependency is missing, or whose server is unreachable, are
skipped rather than omitted) so that a single test body runs -- and must
pass -- identically for every implementation.
"""

from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from typing import Any

import pytest

from persista.store import (
    BaseRedisStore,
    BaseStore,
    DuckDBStore,
    InMemoryStore,
    PickleRedisStore,
    RedisStore,
    SQLiteStore,
)
from persista.utils.imports import is_duckdb_available, is_redis_available

if is_redis_available():
    import redis

REDIS_URL = os.environ.get("PERSISTA_TEST_REDIS_URL", "redis://localhost:6379/0")


def _redis_server_reachable() -> bool:
    if not is_redis_available():
        return False
    try:
        redis.Redis.from_url(REDIS_URL, socket_connect_timeout=1).ping()
    except redis.exceptions.RedisError:
        return False
    return True


def _is_redis_store(store: BaseStore) -> bool:
    return is_redis_available() and isinstance(store, BaseRedisStore)


def _store_factories() -> list[pytest.mark.ParameterSet]:
    r"""Return one ``pytest.param`` per store backend.

    Each param wraps a zero-argument factory that creates a fresh, empty
    store instance. Stores whose optional dependency is not installed
    (DuckDB, Redis), or whose server is unreachable (Redis), are marked
    as skipped rather than omitted, so they are still visible (as skips)
    in `pytest -k`/reports.
    """
    redis_skip = pytest.mark.skipif(
        not _redis_server_reachable(), reason="Requires a reachable Redis server"
    )
    return [
        pytest.param(InMemoryStore, id="in_memory"),
        pytest.param(lambda: SQLiteStore(":memory:"), id="sqlite"),
        pytest.param(
            lambda: DuckDBStore(":memory:"),
            id="duckdb",
            marks=pytest.mark.skipif(not is_duckdb_available(), reason="Requires duckdb"),
        ),
        pytest.param(lambda: RedisStore(REDIS_URL), id="redis", marks=redis_skip),
        pytest.param(lambda: PickleRedisStore(REDIS_URL), id="pickle_redis", marks=redis_skip),
    ]


@pytest.fixture(params=_store_factories())
def store(request: pytest.FixtureRequest) -> Generator[BaseStore, None, None]:
    with request.param() as store:
        # RedisStore has no per-test namespace, so a shared server must be
        # cleared before/after each test to keep tests isolated.
        if _is_redis_store(store):
            store.delete_many(list(store.keys()))
        yield store
        if _is_redis_store(store):
            store.delete_many(list(store.keys()))


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


###############################################
#     Consistency tests for BaseStore API      #
###############################################


# --- get / set ---


def test_get_missing_key_returns_none(store: BaseStore) -> None:
    assert store.get("nonexistent") is None


def test_set_then_get_round_trips(store: BaseStore) -> None:
    store.set("1", {"text": "hello", "n": 1})
    assert store.get("1") == {"text": "hello", "n": 1}


def test_set_default_overwrites_existing(store: BaseStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"})
    assert store.get("1") == {"text": "updated"}
    assert store.count() == 1


def test_set_on_conflict_raise(store: BaseStore) -> None:
    store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        store.set("1", {"text": "updated"}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}


def test_set_on_conflict_skip(store: BaseStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}


def test_set_on_conflict_overwrite(store: BaseStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}


def test_set_on_conflict_merge(store: BaseStore) -> None:
    store.set("1", {"text": "original", "author": "Alice"})
    store.set("1", {"text": "updated"}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


def test_set_on_conflict_invalid_raises(store: BaseStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- get_many ---


def test_get_many_preserves_order(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.get_many(["3", "1", "2"]) == [items["3"], items["1"], items["2"]]


def test_get_many_returns_none_for_missing(
    store: BaseStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["1", "99", "2"])
    assert result[1] is None


def test_get_many_empty_list_returns_empty_list(store: BaseStore) -> None:
    assert store.get_many([]) == []


# --- set_many ---


def test_set_many_increases_count(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


def test_set_many_empty_is_no_op(store: BaseStore) -> None:
    store.set_many({})
    assert store.count() == 0


def test_set_many_on_conflict_raise(store: BaseStore) -> None:
    store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}
    assert store.get("3") is None


def test_set_many_on_conflict_skip(store: BaseStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


def test_set_many_on_conflict_merge(store: BaseStore) -> None:
    store.set_many({"1": {"text": "original", "author": "Alice"}})
    store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


# --- set_batches ---


def test_set_batches_writes_all_pairs(store: BaseStore) -> None:
    store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert store.count() == 3
    assert store.get("2") == {"v": 2}


def test_set_batches_empty_is_no_op(store: BaseStore) -> None:
    store.set_batches([])
    assert store.count() == 0


# --- filter ---


def test_filter_no_args_returns_all(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert len(store.filter()) == len(items)


def test_filter_single_field(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


def test_filter_multiple_fields(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert len(store.filter(author="Alice", category="Programming")) == 2


def test_filter_no_match_returns_empty(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.filter(author="Charlie") == []


def test_filter_integer_field_value(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


def test_filter_empty_store_returns_empty(store: BaseStore) -> None:
    assert store.filter(author="Alice") == []


# --- delete / delete_many ---


def test_delete_removes_value(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete("1")
    assert store.count() == len(items) - 1
    assert store.get("1") is None


def test_delete_nonexistent_is_silent(store: BaseStore) -> None:
    store.delete("nonexistent")


def test_delete_many_removes_values(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.count() == len(items) - 2
    assert store.get("1") is None
    assert store.get("3") is None


def test_delete_many_empty_list_is_no_op(
    store: BaseStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many([])
    assert store.count() == len(items)


def test_delete_many_nonexistent_keys_are_silent(store: BaseStore) -> None:
    store.delete_many(["99", "100"])


# --- contains_many ---


def test_contains_many_mixed(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "99", "3", "42"])
    assert sorted(found) == ["1", "3"]
    assert sorted(missing) == ["42", "99"]


def test_contains_many_empty_input_returns_empty_lists(store: BaseStore) -> None:
    assert store.contains_many([]) == ([], [])


def test_contains_many_empty_store_returns_all_missing(store: BaseStore) -> None:
    found, missing = store.contains_many(["1", "2"])
    assert found == []
    assert sorted(missing) == ["1", "2"]


# --- keys / values ---


def test_keys_empty_store_yields_nothing(store: BaseStore) -> None:
    assert list(store.keys()) == []


def test_keys_returns_all_keys(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert sorted(store.keys()) == sorted(items.keys())


def test_values_returns_all_values(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = list(store.values())
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


# --- iter_batches ---


def test_iter_batches_empty_store_yields_nothing(store: BaseStore) -> None:
    assert list(store.iter_batches()) == []


def test_iter_batches_returns_generator(store: BaseStore) -> None:
    assert isinstance(store.iter_batches(), Iterator)


def test_iter_batches_returns_all_key_value_pairs(
    store: BaseStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


def test_iter_batches_yields_correct_batch_sizes(
    store: BaseStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert sorted(len(b) for b in batches) == [2, 2]


def test_iter_batches_zero_batch_size_raises(store: BaseStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=0))


# --- count ---


def test_count_empty_store(store: BaseStore) -> None:
    assert store.count() == 0


def test_count_after_set_many(store: BaseStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


# --- close / context manager ---


def test_close_is_idempotent(store: BaseStore) -> None:
    store.close()
    store.close()  # should not raise


def test_close_returns_none(store: BaseStore) -> None:
    assert store.close() is None


def test_context_manager_usable_for_reads_and_writes(store: BaseStore) -> None:
    store.set_many(
        {
            "1": {"text": "hello", "author": "Alice"},
            "2": {"text": "world", "author": "Bob"},
        }
    )
    assert store.count() == 2
    assert store.filter(author="Alice")[0]["text"] == "hello"
    store.delete("1")
    assert store.count() == 1


####################################################
#     Cross-store comparisons in a single test      #
####################################################

# The tests above run the exact same body once per backend (parametrized
# fixture), which is the main way this suite catches a backend that
# behaves differently. The test below goes one step further and compares
# every available backend's output *against each other* directly, within
# a single test, for a representative end-to-end workflow.


def _all_available_stores() -> Generator[tuple[str, BaseStore], None, None]:
    for factory_param in _store_factories():
        (factory,) = factory_param.values
        store_id = factory_param.id
        skip_marks = [m for m in factory_param.marks if m.name == "skipif"]
        if any(mark.args[0] for mark in skip_marks):
            continue
        store: BaseStore = factory()
        if _is_redis_store(store):
            store.delete_many(list(store.keys()))
        yield store_id, store


def test_cross_store_outputs_are_identical(items: dict[str, dict[str, Any]]) -> None:
    results: dict[str, Any] = {}
    stores: list[BaseStore] = []
    try:
        for store_id, store in _all_available_stores():
            stores.append(store)
            store.set_many(items)
            store.set("5", {"title": "Cooking Basics", "author": "Alice", "category": "Food"})
            store.delete("5")
            store.set("1", {**items["1"], "year": 2099}, on_conflict="merge")

            results[store_id] = {
                "count": store.count(),
                "get_1": store.get("1"),
                "get_missing": store.get("nonexistent"),
                "get_many": store.get_many(["3", "1", "99"]),
                "filter_alice": sorted(
                    (v["title"] for v in store.filter(author="Alice")),
                ),
                "filter_none": store.filter(author="Charlie"),
                "contains_many": store.contains_many(["1", "99", "3"]),
                "keys": sorted(store.keys()),
                "values_titles": sorted(v["title"] for v in store.values()),
            }
    finally:
        for store in stores:
            if _is_redis_store(store):
                store.delete_many(list(store.keys()))
            store.close()

    assert len(results) >= 2, "Need at least two available stores to compare"
    reference_id, reference = next(iter(results.items()))
    for store_id, result in results.items():
        assert result == reference, (
            f"Store {store_id!r} produced a different result than {reference_id!r}: "
            f"{result} != {reference}"
        )
