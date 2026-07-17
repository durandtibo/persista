from __future__ import annotations

from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import PickleRedisStore, RedisStore

if TYPE_CHECKING:
    from persista.store import BaseRedisStore

fakeredis = pytest.importorskip("fakeredis")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _use_fake_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    # A single fake server instance is used regardless of `store_cls`, since
    # RedisStore/PickleRedisStore only differ in serialization, and both
    # request the correct `decode_responses` mode via `from_url` kwargs.
    monkeypatch.setattr(
        "persista.store.redis.redis.Redis.from_url",
        lambda *_args, **kwargs: fakeredis.FakeRedis(
            decode_responses=kwargs.get("decode_responses", True)
        ),
    )


@pytest.fixture(params=[RedisStore, PickleRedisStore], ids=["json", "pickle"])
def store_cls(request: pytest.FixtureRequest) -> type[BaseRedisStore]:
    return request.param


@pytest.fixture
def store(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[BaseRedisStore]
) -> Generator[BaseRedisStore, None, None]:
    _use_fake_redis(monkeypatch)
    with store_cls() as store:
        yield store


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


def test_init_defaults(store: BaseRedisStore) -> None:
    assert store.count() == 0


def test_init_accepts_redis_from_url_kwargs(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[BaseRedisStore]
) -> None:
    _use_fake_redis(monkeypatch)
    with store_cls(socket_timeout=5.0) as store:
        assert store.count() == 0


# --- repr/str ---


def test_repr(store: BaseRedisStore) -> None:
    assert repr(store).startswith(f"{type(store).__name__}(")


def test_str(store: BaseRedisStore) -> None:
    assert str(store).startswith(f"{type(store).__name__}(")


def test_repr_after_close_does_not_raise(store: BaseRedisStore) -> None:
    store.close()
    assert repr(store).startswith(f"{type(store).__name__}(")


# --- set ---


def test_set_increases_count(store: BaseRedisStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.count() == 1


def test_set_stores_value(store: BaseRedisStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.get("1") == {"text": "hello"}


def test_set_default_overwrites_existing(store: BaseRedisStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


def test_set_on_conflict_raise(store: BaseRedisStore) -> None:
    store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        store.set("1", {"text": "updated"}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}


def test_set_on_conflict_skip(store: BaseRedisStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}


def test_set_on_conflict_overwrite(store: BaseRedisStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}


def test_set_on_conflict_merge(store: BaseRedisStore) -> None:
    store.set("1", {"text": "original", "author": "Alice"})
    store.set("1", {"text": "updated"}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


def test_set_on_conflict_new_key_is_unaffected(store: BaseRedisStore) -> None:
    store.set("1", {"text": "hello"}, on_conflict="raise")
    assert store.get("1") == {"text": "hello"}


def test_set_on_conflict_invalid_raises(store: BaseRedisStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- set_many ---


def test_set_many_increases_count(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


def test_set_many_empty_is_no_op(store: BaseRedisStore) -> None:
    store.set_many({})
    assert store.count() == 0


def test_set_many_default_overwrites_existing(store: BaseRedisStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


def test_set_many_on_conflict_raise(store: BaseRedisStore) -> None:
    store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}
    assert store.get("3") is None


def test_set_many_on_conflict_skip(store: BaseRedisStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


def test_set_many_on_conflict_overwrite(store: BaseRedisStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}
    assert store.get("2") == {"text": "new"}


def test_set_many_on_conflict_merge(store: BaseRedisStore) -> None:
    store.set_many({"1": {"text": "original", "author": "Alice"}})
    store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


def test_set_many_on_conflict_invalid_raises(store: BaseRedisStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set_many({"1": {"text": "hello"}}, on_conflict="bogus")


# --- set_batches ---


def test_set_batches_empty_is_no_op(store: BaseRedisStore) -> None:
    store.set_batches([])
    assert store.count() == 0


def test_set_batches_writes_all_pairs(store: BaseRedisStore) -> None:
    store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert store.count() == 3
    assert store.get("2") == {"v": 2}


def test_set_batches_consumes_a_generator(store: BaseRedisStore) -> None:
    def gen() -> Iterator[tuple[str, dict[str, int]]]:
        for i in range(5):
            yield str(i), {"v": i}

    store.set_batches(gen(), batch_size=2)
    assert store.count() == 5


def test_set_batches_on_conflict_skip(store: BaseRedisStore) -> None:
    store.set("1", {"text": "original"})
    store.set_batches([("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


# --- count ---


def test_count_empty_store(store: BaseRedisStore) -> None:
    assert store.count() == 0


def test_count_after_set_many(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


# --- get ---


def test_get_existing_value(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.get("1") == items["1"]


def test_get_missing_key_returns_none(store: BaseRedisStore) -> None:
    assert store.get("nonexistent") is None


# --- get_many ---


def test_get_many_returns_correct_length(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert len(store.get_many(["1", "2", "99"])) == 3


def test_get_many_returns_none_for_missing(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["1", "99", "2"])
    assert result[1] is None


def test_get_many_preserves_order(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


def test_get_many_empty_list_returns_empty_list(store: BaseRedisStore) -> None:
    assert store.get_many([]) == []


# --- filter ---


def test_filter_no_args_returns_all(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert len(store.filter()) == len(items)


def test_filter_single_field(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


def test_filter_multiple_fields(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice", category="Programming")
    assert len(result) == 2


def test_filter_no_match_returns_empty(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.filter(author="Charlie") == []


def test_filter_preserves_full_value(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.filter(author="Bob", category="History")
    expected = [v for v in items.values() if v["author"] == "Bob"]
    assert sorted(result, key=lambda v: v["title"]) == sorted(expected, key=lambda v: v["title"])


def test_filter_empty_store_returns_empty(store: BaseRedisStore) -> None:
    assert store.filter(author="Alice") == []


def test_filter_integer_field_value(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


def test_filter_integer_value_no_match_returns_empty(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.filter(year=9999) == []


# --- delete ---


def test_delete_removes_value(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete("1")
    assert store.count() == len(items) - 1
    assert store.get("1") is None


def test_delete_nonexistent_is_silent(store: BaseRedisStore) -> None:
    store.delete("nonexistent")


# --- delete_many ---


def test_delete_many_removes_values(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.count() == len(items) - 2
    assert store.get("1") is None
    assert store.get("3") is None


def test_delete_many_preserves_other_values(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.get("2") is not None
    assert store.get("4") is not None


def test_delete_many_empty_list_is_no_op(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many([])
    assert store.count() == len(items)


def test_delete_many_nonexistent_keys_are_silent(store: BaseRedisStore) -> None:
    store.delete_many(["99", "100"])


def test_delete_many_single_key(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["2"])
    assert store.count() == len(items) - 1
    assert store.get("2") is None


# --- contains_many ---


def test_contains_many_all_found(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "2", "3", "4"])
    assert sorted(found) == ["1", "2", "3", "4"]
    assert missing == []


def test_contains_many_all_missing(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["99", "100"])
    assert found == []
    assert sorted(missing) == ["100", "99"]


def test_contains_many_mixed(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "99", "3", "42"])
    assert sorted(found) == ["1", "3"]
    assert sorted(missing) == ["42", "99"]


def test_contains_many_empty_input_returns_empty_lists(store: BaseRedisStore) -> None:
    found, missing = store.contains_many([])
    assert found == []
    assert missing == []


def test_contains_many_empty_store_returns_all_missing(store: BaseRedisStore) -> None:
    found, missing = store.contains_many(["1", "2"])
    assert found == []
    assert sorted(missing) == ["1", "2"]


def test_contains_many_returns_tuple_of_two_lists(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.contains_many(["1", "99"])
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


# --- keys ---


def test_keys_empty_store_yields_nothing(store: BaseRedisStore) -> None:
    assert list(store.keys()) == []


def test_keys_returns_all_keys(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert sorted(store.keys()) == sorted(items.keys())


# --- values ---


def test_values_empty_store_yields_nothing(store: BaseRedisStore) -> None:
    assert list(store.values()) == []


def test_values_returns_all_values(store: BaseRedisStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = list(store.values())
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


def test_values_is_lazy_generator(store: BaseRedisStore) -> None:
    assert isinstance(store.values(), Iterator)


# --- iter_batches ---


def test_iter_batches_empty_store_yields_nothing(store: BaseRedisStore) -> None:
    assert list(store.iter_batches()) == []


def test_iter_batches_returns_generator(store: BaseRedisStore) -> None:
    result = store.iter_batches()
    assert isinstance(result, Iterator)


def test_iter_batches_default_batch_size(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches())
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


def test_iter_batches_yields_correct_batch_sizes(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert sorted(len(b) for b in batches) == [2, 2]


def test_iter_batches_batch_size_larger_than_store(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=100))
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


def test_iter_batches_returns_all_key_value_pairs(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


def test_iter_batches_batches_are_dicts(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert all(isinstance(batch, dict) for batch in batches)


def test_iter_batches_zero_batch_size_raises(store: BaseRedisStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=0))


def test_iter_batches_negative_batch_size_raises(store: BaseRedisStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=-1))


def test_iter_batches_error_raised_before_any_query(store: BaseRedisStore) -> None:
    gen = store.iter_batches(batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        next(gen)


def test_iter_batches_does_not_mutate_store(
    store: BaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    list(store.iter_batches(batch_size=2))
    assert store.count() == len(items)


# --- close ---


def test_close_is_idempotent(store: BaseRedisStore) -> None:
    store.close()
    store.close()  # should not raise


def test_close_returns_none(store: BaseRedisStore) -> None:
    assert store.close() is None


# --- closed ---


def test_closed_false_before_close(store: BaseRedisStore) -> None:
    assert not store.closed


def test_closed_true_after_close(store: BaseRedisStore) -> None:
    store.close()
    assert store.closed


# --- context manager ---


def test_context_manager_returns_self(
    store: BaseRedisStore, store_cls: type[BaseRedisStore]
) -> None:
    assert isinstance(store, store_cls)


def test_context_manager_closes_on_normal_exit(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[BaseRedisStore]
) -> None:
    _use_fake_redis(monkeypatch)
    with store_cls() as store:
        store.set("1", {"text": "hello"})
        assert store.count() == 1
    assert store._closed


def test_context_manager_closes_on_exception(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[BaseRedisStore]
) -> None:
    _use_fake_redis(monkeypatch)
    msg = "boom"
    with pytest.raises(ValueError, match="boom"), store_cls() as store:
        raise ValueError(msg)
    assert store._closed


def test_context_manager_usable_for_reads_and_writes(store: BaseRedisStore) -> None:
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


def test_context_manager_multiple_open_close_same_server(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[BaseRedisStore]
) -> None:
    """Reopening after close reconnects to the same Redis server, so
    previously written data is still there."""
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        "persista.store.redis.redis.Redis.from_url",
        lambda *_args, **kwargs: fakeredis.FakeRedis(
            server=server, decode_responses=kwargs.get("decode_responses", True)
        ),
    )
    redis_store = store_cls()
    for i in range(3):
        with redis_store as store:
            store.set(str(i), {"text": "hello"})
            assert store.count() == i + 1


def test_context_manager_multiple_open_close_server_reset(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[BaseRedisStore]
) -> None:
    """Reopening after close connects to a server that lost its state
    (e.g. restarted), so previously written data is gone."""
    _use_fake_redis(monkeypatch)
    redis_store = store_cls()
    for _ in range(3):
        with redis_store as store:
            assert store.count() == 0
            store.set("1", {"text": "hello"})
            assert store.count() == 1


##########################################################
#     PickleRedisStore-specific serialization behavior    #
##########################################################

# The JSON and pickle variants share the exact same behavior for
# JSON-compatible values (covered by every test above, run against
# both `store_cls` params). They differ only in what they can encode:
# PickleRedisStore round-trips arbitrary Python objects, RedisStore
# silently normalizes them to their closest JSON equivalent.


def test_pickle_store_round_trips_tuples_and_sets(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_fake_redis(monkeypatch)
    with PickleRedisStore() as store:
        store.set("1", {"coordinates": (1, 2, 3), "tags": {"python", "redis"}})
        assert store.get("1") == {"coordinates": (1, 2, 3), "tags": {"python", "redis"}}


def test_json_store_normalizes_tuples_and_sets_are_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_fake_redis(monkeypatch)
    with RedisStore() as store:
        store.set("1", {"coordinates": (1, 2, 3)})
        # JSON has no tuple type, so it comes back as a list.
        assert store.get("1") == {"coordinates": [1, 2, 3]}
        with pytest.raises(TypeError, match="not JSON serializable"):
            store.set("2", {"tags": {"python", "redis"}})
