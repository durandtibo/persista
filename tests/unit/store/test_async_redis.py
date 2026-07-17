from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import AsyncPickleRedisStore, AsyncRedisStore

if TYPE_CHECKING:
    from persista.store import AsyncBaseRedisStore

fakeredis = pytest.importorskip("fakeredis")


MODULE = "persista.store.async_redis"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _use_fake_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    # A single fake server instance is used regardless of `store_cls`, since
    # AsyncRedisStore/AsyncPickleRedisStore only differ in serialization, and
    # both request the correct `decode_responses` mode via `from_url` kwargs.
    monkeypatch.setattr(
        f"{MODULE}.redis.Redis.from_url",
        lambda *_args, **kwargs: fakeredis.aioredis.FakeRedis(
            decode_responses=kwargs.get("decode_responses", True)
        ),
    )


@pytest.fixture(params=[AsyncRedisStore, AsyncPickleRedisStore], ids=["json", "pickle"])
def store_cls(request: pytest.FixtureRequest) -> type[AsyncBaseRedisStore]:
    return request.param


@pytest.fixture
async def store(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[AsyncBaseRedisStore]
) -> AsyncGenerator[AsyncBaseRedisStore]:
    _use_fake_redis(monkeypatch)
    async with store_cls() as store:
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


####################################
#     Tests for AsyncRedisStore    #
####################################


# --- constructor ---


async def test_init_defaults(store: AsyncBaseRedisStore) -> None:
    assert await store.count() == 0


async def test_init_accepts_redis_from_url_kwargs(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[AsyncBaseRedisStore]
) -> None:
    _use_fake_redis(monkeypatch)
    async with store_cls(socket_timeout=5.0) as store:
        assert await store.count() == 0


# --- repr/str ---


async def test_repr(store: AsyncBaseRedisStore) -> None:
    assert repr(store).startswith(f"{type(store).__name__}(")


async def test_str(store: AsyncBaseRedisStore) -> None:
    assert str(store).startswith(f"{type(store).__name__}(")


async def test_repr_after_close_does_not_raise(store: AsyncBaseRedisStore) -> None:
    await store.close()
    assert repr(store).startswith(f"{type(store).__name__}(")


# --- set ---


async def test_set_increases_count(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.count() == 1


async def test_set_stores_value(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.get("1") == {"text": "hello"}


async def test_set_default_overwrites_existing(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"})
    assert await store.count() == 1
    assert await store.get("1") == {"text": "updated"}


async def test_set_on_conflict_raise(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        await store.set("1", {"text": "updated"}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}


async def test_set_on_conflict_skip(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}


async def test_set_on_conflict_overwrite(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert await store.get("1") == {"text": "updated"}


async def test_set_on_conflict_merge(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "original", "author": "Alice"})
    await store.set("1", {"text": "updated"}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


async def test_set_on_conflict_new_key_is_unaffected(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "hello"}, on_conflict="raise")
    assert await store.get("1") == {"text": "hello"}


async def test_set_on_conflict_invalid_raises(store: AsyncBaseRedisStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- set_many ---


async def test_set_many_increases_count(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


async def test_set_many_empty_is_no_op(store: AsyncBaseRedisStore) -> None:
    await store.set_many({})
    assert await store.count() == 0


async def test_set_many_default_overwrites_existing(store: AsyncBaseRedisStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}})
    assert await store.count() == 1
    assert await store.get("1") == {"text": "updated"}


async def test_set_many_on_conflict_raise(store: AsyncBaseRedisStore) -> None:
    await store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        await store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("3") is None


async def test_set_many_on_conflict_skip(store: AsyncBaseRedisStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("2") == {"text": "new"}


async def test_set_many_on_conflict_overwrite(store: AsyncBaseRedisStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert await store.get("1") == {"text": "updated"}
    assert await store.get("2") == {"text": "new"}


async def test_set_many_on_conflict_merge(store: AsyncBaseRedisStore) -> None:
    await store.set_many({"1": {"text": "original", "author": "Alice"}})
    await store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


async def test_set_many_on_conflict_invalid_raises(store: AsyncBaseRedisStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.set_many({"1": {"text": "hello"}}, on_conflict="bogus")


# --- set_batches ---


async def test_set_batches_empty_is_no_op(store: AsyncBaseRedisStore) -> None:
    await store.set_batches([])
    assert await store.count() == 0


async def test_set_batches_writes_all_pairs(store: AsyncBaseRedisStore) -> None:
    await store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert await store.count() == 3
    assert await store.get("2") == {"v": 2}


async def test_set_batches_consumes_a_generator(store: AsyncBaseRedisStore) -> None:
    def gen() -> Iterator[tuple[str, dict[str, int]]]:
        for i in range(5):
            yield str(i), {"v": i}

    await store.set_batches(gen(), batch_size=2)
    assert await store.count() == 5


async def test_set_batches_on_conflict_skip(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set_batches(
        [("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip"
    )
    assert await store.get("1") == {"text": "original"}
    assert await store.get("2") == {"text": "new"}


# --- count ---


async def test_count_empty_store(store: AsyncBaseRedisStore) -> None:
    assert await store.count() == 0


async def test_count_after_set_many(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


# --- get ---


async def test_get_existing_value(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.get("1") == items["1"]


async def test_get_missing_key_returns_none(store: AsyncBaseRedisStore) -> None:
    assert await store.get("nonexistent") is None


# --- get_many ---


async def test_get_many_returns_correct_length(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.get_many(["1", "2", "99"])) == 3


async def test_get_many_returns_none_for_missing(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["1", "99", "2"])
    assert result[1] is None


async def test_get_many_preserves_order(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


async def test_get_many_empty_list_returns_empty_list(store: AsyncBaseRedisStore) -> None:
    assert await store.get_many([]) == []


# --- filter ---


async def test_filter_no_args_returns_all(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.filter()) == len(items)


async def test_filter_single_field(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


async def test_filter_multiple_fields(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice", category="Programming")
    assert len(result) == 2


async def test_filter_no_match_returns_empty(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.filter(author="Charlie") == []


async def test_filter_preserves_full_value(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Bob", category="History")
    expected = [v for v in items.values() if v["author"] == "Bob"]
    assert sorted(result, key=lambda v: v["title"]) == sorted(expected, key=lambda v: v["title"])


async def test_filter_empty_store_returns_empty(store: AsyncBaseRedisStore) -> None:
    assert await store.filter(author="Alice") == []


async def test_filter_integer_field_value(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


async def test_filter_integer_value_no_match_returns_empty(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.filter(year=9999) == []


# --- delete ---


async def test_delete_removes_value(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete("1")
    assert await store.count() == len(items) - 1
    assert await store.get("1") is None


async def test_delete_nonexistent_is_silent(store: AsyncBaseRedisStore) -> None:
    await store.delete("nonexistent")


# --- delete_many ---


async def test_delete_many_removes_values(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["1", "3"])
    assert await store.count() == len(items) - 2
    assert await store.get("1") is None
    assert await store.get("3") is None


async def test_delete_many_preserves_other_values(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["1", "3"])
    assert await store.get("2") is not None
    assert await store.get("4") is not None


async def test_delete_many_empty_list_is_no_op(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many([])
    assert await store.count() == len(items)


async def test_delete_many_nonexistent_keys_are_silent(store: AsyncBaseRedisStore) -> None:
    await store.delete_many(["99", "100"])


async def test_delete_many_single_key(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["2"])
    assert await store.count() == len(items) - 1
    assert await store.get("2") is None


# --- contains_many ---


async def test_contains_many_all_found(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["1", "2", "3", "4"])
    assert sorted(found) == ["1", "2", "3", "4"]
    assert missing == []


async def test_contains_many_all_missing(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["99", "100"])
    assert found == []
    assert sorted(missing) == ["100", "99"]


async def test_contains_many_mixed(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["1", "99", "3", "42"])
    assert sorted(found) == ["1", "3"]
    assert sorted(missing) == ["42", "99"]


async def test_contains_many_empty_input_returns_empty_lists(
    store: AsyncBaseRedisStore,
) -> None:
    found, missing = await store.contains_many([])
    assert found == []
    assert missing == []


async def test_contains_many_empty_store_returns_all_missing(
    store: AsyncBaseRedisStore,
) -> None:
    found, missing = await store.contains_many(["1", "2"])
    assert found == []
    assert sorted(missing) == ["1", "2"]


async def test_contains_many_returns_tuple_of_two_lists(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.contains_many(["1", "99"])
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


# --- keys ---


async def test_keys_empty_store_yields_nothing(store: AsyncBaseRedisStore) -> None:
    assert [key async for key in store.keys()] == []  # noqa: SIM118


async def test_keys_returns_all_keys(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [key async for key in store.keys()]  # noqa: SIM118
    assert sorted(result) == sorted(items.keys())


# --- values ---


async def test_values_empty_store_yields_nothing(store: AsyncBaseRedisStore) -> None:
    assert [value async for value in store.values()] == []


async def test_values_returns_all_values(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [value async for value in store.values()]
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


async def test_values_is_lazy_async_generator(store: AsyncBaseRedisStore) -> None:
    assert isinstance(store.values(), AsyncIterator)


# --- iter_batches ---


async def test_iter_batches_empty_store_yields_nothing(store: AsyncBaseRedisStore) -> None:
    assert [batch async for batch in store.iter_batches()] == []


async def test_iter_batches_returns_async_generator(store: AsyncBaseRedisStore) -> None:
    result = store.iter_batches()
    assert isinstance(result, AsyncIterator)


async def test_iter_batches_default_batch_size(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches()]
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


async def test_iter_batches_yields_correct_batch_sizes(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=2)]
    assert sorted(len(b) for b in batches) == [2, 2]


async def test_iter_batches_batch_size_larger_than_store(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=100)]
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


async def test_iter_batches_returns_all_key_value_pairs(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    async for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


async def test_iter_batches_batches_are_dicts(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=2)]
    assert all(isinstance(batch, dict) for batch in batches)


async def test_iter_batches_zero_batch_size_raises(store: AsyncBaseRedisStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.iter_batches(batch_size=0):
            pass


async def test_iter_batches_negative_batch_size_raises(store: AsyncBaseRedisStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.iter_batches(batch_size=-1):
            pass


async def test_iter_batches_error_raised_before_any_query(store: AsyncBaseRedisStore) -> None:
    gen = store.iter_batches(batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        await anext(gen)


async def test_iter_batches_does_not_mutate_store(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    async for _ in store.iter_batches(batch_size=2):
        pass
    assert await store.count() == len(items)


# --- close ---


async def test_close_is_idempotent(store: AsyncBaseRedisStore) -> None:
    await store.close()
    await store.close()  # should not raise


async def test_close_returns_none(store: AsyncBaseRedisStore) -> None:
    assert await store.close() is None


# --- closed ---


async def test_closed_false_before_close(store: AsyncBaseRedisStore) -> None:
    assert not store.closed


async def test_closed_true_after_close(store: AsyncBaseRedisStore) -> None:
    await store.close()
    assert store.closed


# --- context manager ---


async def test_context_manager_returns_self(
    store: AsyncBaseRedisStore, store_cls: type[AsyncBaseRedisStore]
) -> None:
    assert isinstance(store, store_cls)


async def test_context_manager_closes_on_normal_exit(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[AsyncBaseRedisStore]
) -> None:
    _use_fake_redis(monkeypatch)
    async with store_cls() as store:
        await store.set("1", {"text": "hello"})
        assert await store.count() == 1
    assert store._closed


async def test_context_manager_closes_on_exception(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[AsyncBaseRedisStore]
) -> None:
    _use_fake_redis(monkeypatch)
    msg = "boom"
    store: AsyncBaseRedisStore = store_cls()
    with pytest.raises(ValueError, match="boom"):
        async with store:
            raise ValueError(msg)
    assert store._closed


async def test_context_manager_usable_for_reads_and_writes(store: AsyncBaseRedisStore) -> None:
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


async def test_context_manager_multiple_open_close_same_server(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[AsyncBaseRedisStore]
) -> None:
    """Reopening after close reconnects to the same Redis server, so
    previously written data is still there."""
    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        f"{MODULE}.redis.Redis.from_url",
        lambda *_args, **kwargs: fakeredis.aioredis.FakeRedis(
            server=server, decode_responses=kwargs.get("decode_responses", True)
        ),
    )
    redis_store = store_cls()
    for i in range(3):
        async with redis_store as store:
            await store.set(str(i), {"text": "hello"})
            assert await store.count() == i + 1


async def test_context_manager_multiple_open_close_server_reset(
    monkeypatch: pytest.MonkeyPatch, store_cls: type[AsyncBaseRedisStore]
) -> None:
    """Reopening after close connects to a server that lost its state
    (e.g. restarted), so previously written data is gone."""
    _use_fake_redis(monkeypatch)
    redis_store = store_cls()
    for _ in range(3):
        async with redis_store as store:
            assert await store.count() == 0
            await store.set("1", {"text": "hello"})
            assert await store.count() == 1


##################################################################
#     AsyncPickleRedisStore-specific serialization behavior      #
##################################################################

# The JSON and pickle variants share the exact same behavior for
# JSON-compatible values (covered by every test above, run against
# both `store_cls` params). They differ only in what they can encode:
# AsyncPickleRedisStore round-trips arbitrary Python objects,
# AsyncRedisStore silently normalizes them to their closest JSON
# equivalent.


async def test_pickle_store_round_trips_tuples_and_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_fake_redis(monkeypatch)
    async with AsyncPickleRedisStore() as store:
        await store.set("1", {"coordinates": (1, 2, 3), "tags": {"python", "redis"}})
        assert await store.get("1") == {"coordinates": (1, 2, 3), "tags": {"python", "redis"}}


async def test_json_store_normalizes_tuples_and_sets_are_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_fake_redis(monkeypatch)
    async with AsyncRedisStore() as store:
        await store.set("1", {"coordinates": (1, 2, 3)})
        # JSON has no tuple type, so it comes back as a list.
        assert await store.get("1") == {"coordinates": [1, 2, 3]}
        with pytest.raises(TypeError, match="not JSON serializable"):
            await store.set("2", {"tags": {"python", "redis"}})
