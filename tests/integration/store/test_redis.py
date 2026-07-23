from __future__ import annotations

from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, Any

import pytest

from persista.testing.fixtures import redis_available
from persista.utils.imports import is_redis_available
from tests.integration.store.redis_helpers import REDIS_URL, redis_server_available

if TYPE_CHECKING:
    from persista.store import BaseRedisStore

if is_redis_available():
    from persista.store import PickleRedisStore, RedisStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=(["json", "pickle"] if is_redis_available() else []),
)
def store_cls(request: pytest.FixtureRequest) -> type[BaseRedisStore]:
    return {"json": RedisStore, "pickle": PickleRedisStore}[request.param]


@pytest.fixture
def store(store_cls: type[BaseRedisStore]) -> Generator[BaseRedisStore, None, None]:
    with store_cls(REDIS_URL) as store:
        # RedisStore/PickleRedisStore have no namespace prefix, so a shared
        # server must be cleared before/after each test to keep tests
        # isolated.
        store.delete_many(list(store.keys()))
        yield store
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


###############################
#     Tests for RedisStore    #
###############################


# --- constructor ---


@redis_available
@redis_server_available
def test_init_defaults(store: BaseRedisStore) -> None:
    assert store.count() == 0


@redis_available
@redis_server_available
def test_init_accepts_redis_from_url_kwargs(store_cls: type[BaseRedisStore]) -> None:
    with store_cls(REDIS_URL, socket_timeout=5.0) as store:
        store.delete_many(list(store.keys()))
        assert store.count() == 0


# --- repr/str ---


@redis_available
@redis_server_available
def test_repr(store: BaseRedisStore) -> None:
    assert repr(store).startswith(f"{type(store).__name__}(")


@redis_available
@redis_server_available
def test_str(store: BaseRedisStore) -> None:
    assert str(store).startswith(f"{type(store).__name__}(")


@redis_available
@redis_server_available
def test_repr_after_close_does_not_raise(store: BaseRedisStore) -> None:
    store.close()
    assert repr(store).startswith(f"{type(store).__name__}(")


# --- set ---


@redis_available
@redis_server_available
def test_set_increases_count(store: BaseRedisStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.count() == 1


@redis_available
@redis_server_available
def test_set_stores_value(store: BaseRedisStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.get("1") == {"text": "hello"}


@redis_available
@redis_server_available
def test_set_default_overwrites_existing(store: BaseRedisStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


@redis_available
@redis_server_available
def test_set_on_conflict_raise(store: BaseRedisStore) -> None:
    store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        store.set("1", {"text": "updated"}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}


@redis_available
@redis_server_available
def test_set_on_conflict_skip(store: BaseRedisStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}


@redis_available
@redis_server_available
def test_set_on_conflict_overwrite(store: BaseRedisStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}


@redis_available
@redis_server_available
def test_set_on_conflict_merge(store: BaseRedisStore) -> None:
    store.set("1", {"text": "original", "author": "Alice"})
    store.set("1", {"text": "updated"}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


@redis_available
@redis_server_available
def test_set_on_conflict_invalid_raises(store: BaseRedisStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- set_many ---


@redis_available
@redis_server_available
def test_set_many_increases_count(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


@redis_available
@redis_server_available
def test_set_many_empty_is_no_op(store: BaseRedisStore) -> None:
    store.set_many({})
    assert store.count() == 0


@redis_available
@redis_server_available
def test_set_many_on_conflict_raise(store: BaseRedisStore) -> None:
    store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}
    assert store.get("3") is None


@redis_available
@redis_server_available
def test_set_many_on_conflict_skip(store: BaseRedisStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


@redis_available
@redis_server_available
def test_set_many_on_conflict_merge(store: BaseRedisStore) -> None:
    store.set_many({"1": {"text": "original", "author": "Alice"}})
    store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


# --- set_batches ---


@redis_available
@redis_server_available
def test_set_batches_writes_all_pairs(store: BaseRedisStore) -> None:
    store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert store.count() == 3
    assert store.get("2") == {"v": 2}


# --- get / get_many ---


@redis_available
@redis_server_available
def test_get_missing_key_returns_none(store: BaseRedisStore) -> None:
    assert store.get("nonexistent") is None


@redis_available
@redis_server_available
def test_get_many_preserves_order(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


@redis_available
@redis_server_available
def test_get_many_returns_none_for_missing(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["1", "99", "2"])
    assert result[1] is None


@redis_available
@redis_server_available
def test_get_many_empty_list_returns_empty_list(store: BaseRedisStore) -> None:
    assert store.get_many([]) == []


# --- filter ---


@redis_available
@redis_server_available
def test_filter_no_args_returns_all(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert len(store.filter()) == len(items)


@redis_available
@redis_server_available
def test_filter_single_field(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


@redis_available
@redis_server_available
def test_filter_multiple_fields(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice", category="Programming")
    assert len(result) == 2


@redis_available
@redis_server_available
def test_filter_no_match_returns_empty(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.filter(author="Charlie") == []


@redis_available
@redis_server_available
def test_filter_integer_field_value(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


# --- delete / delete_many ---


@redis_available
@redis_server_available
def test_delete_removes_value(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete("1")
    assert store.count() == len(items) - 1
    assert store.get("1") is None


@redis_available
@redis_server_available
def test_delete_nonexistent_is_silent(store: BaseRedisStore) -> None:
    store.delete("nonexistent")


@redis_available
@redis_server_available
def test_delete_many_removes_values(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.count() == len(items) - 2
    assert store.get("1") is None
    assert store.get("3") is None


@redis_available
@redis_server_available
def test_delete_many_empty_list_is_no_op(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many([])
    assert store.count() == len(items)


# --- contains_many ---


@redis_available
@redis_server_available
def test_contains_many_mixed(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "99", "3", "42"])
    assert sorted(found) == ["1", "3"]
    assert sorted(missing) == ["42", "99"]


@redis_available
@redis_server_available
def test_contains_many_empty_input_returns_empty_lists(store: BaseRedisStore) -> None:
    found, missing = store.contains_many([])
    assert found == []
    assert missing == []


# --- keys / values ---


@redis_available
@redis_server_available
def test_keys_returns_all_keys(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert sorted(store.keys()) == sorted(items.keys())


@redis_available
@redis_server_available
def test_values_returns_all_values(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = list(store.values())
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


# --- iter_batches ---


@redis_available
@redis_server_available
def test_iter_batches_empty_store_yields_nothing(store: BaseRedisStore) -> None:
    assert list(store.iter_batches()) == []


@redis_available
@redis_server_available
def test_iter_batches_returns_generator(store: BaseRedisStore) -> None:
    assert isinstance(store.iter_batches(), Iterator)


@redis_available
@redis_server_available
def test_iter_batches_returns_all_key_value_pairs(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


@redis_available
@redis_server_available
def test_iter_batches_yields_correct_batch_sizes(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert sorted(len(b) for b in batches) == [2, 2]


@redis_available
@redis_server_available
def test_iter_batches_zero_batch_size_raises(store: BaseRedisStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=0))


# --- close / context manager ---


@redis_available
@redis_server_available
def test_close_is_idempotent(store: BaseRedisStore) -> None:
    store.close()
    store.close()  # should not raise


@redis_available
@redis_server_available
def test_close_returns_none(store: BaseRedisStore) -> None:
    assert store.close() is None


@redis_available
@redis_server_available
def test_context_manager_returns_self(store_cls: type[BaseRedisStore]) -> None:
    with store_cls(REDIS_URL) as store:
        assert isinstance(store, store_cls)
        store.delete_many(list(store.keys()))


@redis_available
@redis_server_available
def test_context_manager_usable_for_reads_and_writes(store_cls: type[BaseRedisStore]) -> None:
    with store_cls(REDIS_URL) as store:
        store.delete_many(list(store.keys()))
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
        store.delete_many(list(store.keys()))


# --- to_uri / from_uri ---


@redis_available
@redis_server_available
def test_to_uri_from_uri_round_trips_data(store_cls: type[BaseRedisStore]) -> None:
    with store_cls(REDIS_URL) as store:
        store.delete_many(list(store.keys()))
        store.set("1", {"text": "hello", "author": "Alice"})
        uri = store.to_uri()
        try:
            with store_cls.from_uri(uri) as reloaded:
                assert reloaded.get("1") == {"text": "hello", "author": "Alice"}
        finally:
            store.delete_many(list(store.keys()))


@redis_available
@redis_server_available
def test_context_manager_multiple_open_close(store_cls: type[BaseRedisStore]) -> None:
    redis_store = store_cls(REDIS_URL)
    try:
        with redis_store as store:
            store.delete_many(list(store.keys()))
        for i in range(3):
            with redis_store as store:
                store.set(str(i), {"text": "hello"})
                assert store.get(str(i)) == {"text": "hello"}
    finally:
        with redis_store as store:
            store.delete_many(list(store.keys()))


# --- async round trips ---


@redis_available
@redis_server_available
async def test_redis_store_aget_aset_round_trip(store: BaseRedisStore) -> None:
    await store.aset("1", {"title": "Intro to Python"})
    assert await store.aget("1") == {"title": "Intro to Python"}


@redis_available
@redis_server_available
async def test_redis_store_afilter(store: BaseRedisStore) -> None:
    await store.aset_many({"1": {"author": "Alice"}, "2": {"author": "Bob"}})
    assert await store.afilter(author="Alice") == [{"author": "Alice"}]


@redis_available
@redis_server_available
async def test_redis_store_acontains_many(store: BaseRedisStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    found, missing = await store.acontains_many(["1", "3"])
    assert found == ["1"]
    assert missing == ["3"]


@redis_available
@redis_server_available
async def test_redis_store_akeys_aclear(store: BaseRedisStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert sorted([key async for key in store.akeys()]) == ["1", "2"]
    await store.aclear()
    assert await store.acount() == 0
