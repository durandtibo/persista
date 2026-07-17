from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from typing import Any

import pytest

from persista.testing.fixtures import redis_available
from persista.utils.imports import is_redis_available

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


redis_server_available = pytest.mark.skipif(
    not _redis_server_reachable(), reason="Requires a reachable Redis server"
)

if is_redis_available():
    from persista.store import RedisStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> Generator[RedisStore, None, None]:
    with RedisStore(REDIS_URL) as store:
        # RedisStore has no namespace prefix, so clear any leftover keys
        # before and after each test to keep tests isolated on a shared server.
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
def test_init_defaults(store: RedisStore) -> None:
    assert store.count() == 0


@redis_available
@redis_server_available
def test_init_accepts_redis_from_url_kwargs() -> None:
    with RedisStore(REDIS_URL, socket_timeout=5.0) as store:
        store.delete_many(list(store.keys()))
        assert store.count() == 0


# --- repr/str ---


@redis_available
@redis_server_available
def test_repr(store: RedisStore) -> None:
    assert repr(store).startswith("RedisStore(")


@redis_available
@redis_server_available
def test_str(store: RedisStore) -> None:
    assert str(store).startswith("RedisStore(")


@redis_available
@redis_server_available
def test_repr_after_close_does_not_raise(store: RedisStore) -> None:
    store.close()
    assert repr(store).startswith("RedisStore(")


# --- set ---


@redis_available
@redis_server_available
def test_set_increases_count(store: RedisStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.count() == 1


@redis_available
@redis_server_available
def test_set_stores_value(store: RedisStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.get("1") == {"text": "hello"}


@redis_available
@redis_server_available
def test_set_default_overwrites_existing(store: RedisStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


@redis_available
@redis_server_available
def test_set_on_conflict_raise(store: RedisStore) -> None:
    store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        store.set("1", {"text": "updated"}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}


@redis_available
@redis_server_available
def test_set_on_conflict_skip(store: RedisStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}


@redis_available
@redis_server_available
def test_set_on_conflict_overwrite(store: RedisStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}


@redis_available
@redis_server_available
def test_set_on_conflict_merge(store: RedisStore) -> None:
    store.set("1", {"text": "original", "author": "Alice"})
    store.set("1", {"text": "updated"}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


@redis_available
@redis_server_available
def test_set_on_conflict_invalid_raises(store: RedisStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- set_many ---


@redis_available
@redis_server_available
def test_set_many_increases_count(store: RedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


@redis_available
@redis_server_available
def test_set_many_empty_is_no_op(store: RedisStore) -> None:
    store.set_many({})
    assert store.count() == 0


@redis_available
@redis_server_available
def test_set_many_on_conflict_raise(store: RedisStore) -> None:
    store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}
    assert store.get("3") is None


@redis_available
@redis_server_available
def test_set_many_on_conflict_skip(store: RedisStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


@redis_available
@redis_server_available
def test_set_many_on_conflict_merge(store: RedisStore) -> None:
    store.set_many({"1": {"text": "original", "author": "Alice"}})
    store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


# --- set_batches ---


@redis_available
@redis_server_available
def test_set_batches_writes_all_pairs(store: RedisStore) -> None:
    store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert store.count() == 3
    assert store.get("2") == {"v": 2}


# --- get / get_many ---


@redis_available
@redis_server_available
def test_get_missing_key_returns_none(store: RedisStore) -> None:
    assert store.get("nonexistent") is None


@redis_available
@redis_server_available
def test_get_many_preserves_order(store: RedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


@redis_available
@redis_server_available
def test_get_many_returns_none_for_missing(
    store: RedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["1", "99", "2"])
    assert result[1] is None


@redis_available
@redis_server_available
def test_get_many_empty_list_returns_empty_list(store: RedisStore) -> None:
    assert store.get_many([]) == []


# --- filter ---


@redis_available
@redis_server_available
def test_filter_no_args_returns_all(store: RedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert len(store.filter()) == len(items)


@redis_available
@redis_server_available
def test_filter_single_field(store: RedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


@redis_available
@redis_server_available
def test_filter_multiple_fields(store: RedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice", category="Programming")
    assert len(result) == 2


@redis_available
@redis_server_available
def test_filter_no_match_returns_empty(store: RedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.filter(author="Charlie") == []


@redis_available
@redis_server_available
def test_filter_integer_field_value(store: RedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


# --- delete / delete_many ---


@redis_available
@redis_server_available
def test_delete_removes_value(store: RedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete("1")
    assert store.count() == len(items) - 1
    assert store.get("1") is None


@redis_available
@redis_server_available
def test_delete_nonexistent_is_silent(store: RedisStore) -> None:
    store.delete("nonexistent")


@redis_available
@redis_server_available
def test_delete_many_removes_values(store: RedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.count() == len(items) - 2
    assert store.get("1") is None
    assert store.get("3") is None


@redis_available
@redis_server_available
def test_delete_many_empty_list_is_no_op(
    store: RedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many([])
    assert store.count() == len(items)


# --- contains_many ---


@redis_available
@redis_server_available
def test_contains_many_mixed(store: RedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "99", "3", "42"])
    assert sorted(found) == ["1", "3"]
    assert sorted(missing) == ["42", "99"]


@redis_available
@redis_server_available
def test_contains_many_empty_input_returns_empty_lists(store: RedisStore) -> None:
    found, missing = store.contains_many([])
    assert found == []
    assert missing == []


# --- keys / values ---


@redis_available
@redis_server_available
def test_keys_returns_all_keys(store: RedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert sorted(store.keys()) == sorted(items.keys())


@redis_available
@redis_server_available
def test_values_returns_all_values(store: RedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = list(store.values())
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


# --- iter_batches ---


@redis_available
@redis_server_available
def test_iter_batches_empty_store_yields_nothing(store: RedisStore) -> None:
    assert list(store.iter_batches()) == []


@redis_available
@redis_server_available
def test_iter_batches_returns_generator(store: RedisStore) -> None:
    assert isinstance(store.iter_batches(), Iterator)


@redis_available
@redis_server_available
def test_iter_batches_returns_all_key_value_pairs(
    store: RedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


@redis_available
@redis_server_available
def test_iter_batches_yields_correct_batch_sizes(
    store: RedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert sorted(len(b) for b in batches) == [2, 2]


@redis_available
@redis_server_available
def test_iter_batches_zero_batch_size_raises(store: RedisStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=0))


# --- close / context manager ---


@redis_available
@redis_server_available
def test_close_is_idempotent(store: RedisStore) -> None:
    store.close()
    store.close()  # should not raise


@redis_available
@redis_server_available
def test_close_returns_none(store: RedisStore) -> None:
    assert store.close() is None


@redis_available
@redis_server_available
def test_context_manager_returns_self() -> None:
    with RedisStore(REDIS_URL) as store:
        assert isinstance(store, RedisStore)
        store.delete_many(list(store.keys()))


@redis_available
@redis_server_available
def test_context_manager_usable_for_reads_and_writes() -> None:
    with RedisStore(REDIS_URL) as store:
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


@redis_available
@redis_server_available
def test_context_manager_multiple_open_close() -> None:
    redis_store = RedisStore(REDIS_URL)
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
