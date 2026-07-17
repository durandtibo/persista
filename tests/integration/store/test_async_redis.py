from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from typing import TYPE_CHECKING, Any

import pytest

from persista.testing.fixtures import redis_available
from persista.utils.imports import is_redis_available
from tests.integration.store.redis_helpers import REDIS_URL, redis_server_available

if TYPE_CHECKING:
    from persista.store.async_redis import AsyncBaseRedisStore

if is_redis_available():
    from persista.store import AsyncPickleRedisStore, AsyncRedisStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=(["json", "pickle"] if is_redis_available() else []),
)
def store_cls(request: pytest.FixtureRequest) -> type[AsyncBaseRedisStore]:
    return {"json": AsyncRedisStore, "pickle": AsyncPickleRedisStore}[request.param]


@pytest.fixture
async def store(store_cls: type[AsyncBaseRedisStore]) -> AsyncGenerator[AsyncBaseRedisStore]:
    async with store_cls(REDIS_URL) as store:
        # AsyncRedisStore/AsyncPickleRedisStore have no namespace prefix, so a
        # shared server must be cleared before/after each test to keep tests
        # isolated.
        await store.delete_many([key async for key in store.keys()])  # noqa: SIM118
        yield store
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


####################################
#     Tests for AsyncRedisStore    #
####################################


# --- constructor ---


@redis_available
@redis_server_available
async def test_init_defaults(store: AsyncBaseRedisStore) -> None:
    assert await store.count() == 0


@redis_available
@redis_server_available
async def test_init_accepts_redis_from_url_kwargs(store_cls: type[AsyncBaseRedisStore]) -> None:
    async with store_cls(REDIS_URL, socket_timeout=5.0) as store:
        await store.delete_many([key async for key in store.keys()])  # noqa: SIM118
        assert await store.count() == 0


# --- repr/str ---


@redis_available
@redis_server_available
async def test_repr(store: AsyncBaseRedisStore) -> None:
    assert repr(store).startswith(f"{type(store).__name__}(")


@redis_available
@redis_server_available
async def test_str(store: AsyncBaseRedisStore) -> None:
    assert str(store).startswith(f"{type(store).__name__}(")


@redis_available
@redis_server_available
async def test_repr_after_close_does_not_raise(store: AsyncBaseRedisStore) -> None:
    await store.close()
    assert repr(store).startswith(f"{type(store).__name__}(")


# --- set ---


@redis_available
@redis_server_available
async def test_set_increases_count(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.count() == 1


@redis_available
@redis_server_available
async def test_set_stores_value(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.get("1") == {"text": "hello"}


@redis_available
@redis_server_available
async def test_set_default_overwrites_existing(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"})
    assert await store.count() == 1
    assert await store.get("1") == {"text": "updated"}


@redis_available
@redis_server_available
async def test_set_on_conflict_raise(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        await store.set("1", {"text": "updated"}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}


@redis_available
@redis_server_available
async def test_set_on_conflict_skip(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}


@redis_available
@redis_server_available
async def test_set_on_conflict_overwrite(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert await store.get("1") == {"text": "updated"}


@redis_available
@redis_server_available
async def test_set_on_conflict_merge(store: AsyncBaseRedisStore) -> None:
    await store.set("1", {"text": "original", "author": "Alice"})
    await store.set("1", {"text": "updated"}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


@redis_available
@redis_server_available
async def test_set_on_conflict_invalid_raises(store: AsyncBaseRedisStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- set_many ---


@redis_available
@redis_server_available
async def test_set_many_increases_count(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


@redis_available
@redis_server_available
async def test_set_many_empty_is_no_op(store: AsyncBaseRedisStore) -> None:
    await store.set_many({})
    assert await store.count() == 0


@redis_available
@redis_server_available
async def test_set_many_on_conflict_raise(store: AsyncBaseRedisStore) -> None:
    await store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        await store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("3") is None


@redis_available
@redis_server_available
async def test_set_many_on_conflict_skip(store: AsyncBaseRedisStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("2") == {"text": "new"}


@redis_available
@redis_server_available
async def test_set_many_on_conflict_merge(store: AsyncBaseRedisStore) -> None:
    await store.set_many({"1": {"text": "original", "author": "Alice"}})
    await store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


# --- set_batches ---


@redis_available
@redis_server_available
async def test_set_batches_writes_all_pairs(store: AsyncBaseRedisStore) -> None:
    await store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert await store.count() == 3
    assert await store.get("2") == {"v": 2}


# --- get / get_many ---


@redis_available
@redis_server_available
async def test_get_missing_key_returns_none(store: AsyncBaseRedisStore) -> None:
    assert await store.get("nonexistent") is None


@redis_available
@redis_server_available
async def test_get_many_preserves_order(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


@redis_available
@redis_server_available
async def test_get_many_returns_none_for_missing(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["1", "99", "2"])
    assert result[1] is None


@redis_available
@redis_server_available
async def test_get_many_empty_list_returns_empty_list(store: AsyncBaseRedisStore) -> None:
    assert await store.get_many([]) == []


# --- filter ---


@redis_available
@redis_server_available
async def test_filter_no_args_returns_all(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.filter()) == len(items)


@redis_available
@redis_server_available
async def test_filter_single_field(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


@redis_available
@redis_server_available
async def test_filter_multiple_fields(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice", category="Programming")
    assert len(result) == 2


@redis_available
@redis_server_available
async def test_filter_no_match_returns_empty(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.filter(author="Charlie") == []


@redis_available
@redis_server_available
async def test_filter_integer_field_value(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


# --- delete / delete_many ---


@redis_available
@redis_server_available
async def test_delete_removes_value(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete("1")
    assert await store.count() == len(items) - 1
    assert await store.get("1") is None


@redis_available
@redis_server_available
async def test_delete_nonexistent_is_silent(store: AsyncBaseRedisStore) -> None:
    await store.delete("nonexistent")


@redis_available
@redis_server_available
async def test_delete_many_removes_values(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["1", "3"])
    assert await store.count() == len(items) - 2
    assert await store.get("1") is None
    assert await store.get("3") is None


@redis_available
@redis_server_available
async def test_delete_many_empty_list_is_no_op(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many([])
    assert await store.count() == len(items)


# --- contains_many ---


@redis_available
@redis_server_available
async def test_contains_many_mixed(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["1", "99", "3", "42"])
    assert sorted(found) == ["1", "3"]
    assert sorted(missing) == ["42", "99"]


@redis_available
@redis_server_available
async def test_contains_many_empty_input_returns_empty_lists(
    store: AsyncBaseRedisStore,
) -> None:
    found, missing = await store.contains_many([])
    assert found == []
    assert missing == []


# --- keys / values ---


@redis_available
@redis_server_available
async def test_keys_returns_all_keys(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [key async for key in store.keys()]  # noqa: SIM118
    assert sorted(result) == sorted(items.keys())


@redis_available
@redis_server_available
async def test_values_returns_all_values(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [value async for value in store.values()]
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


# --- iter_batches ---


@redis_available
@redis_server_available
async def test_iter_batches_empty_store_yields_nothing(store: AsyncBaseRedisStore) -> None:
    assert [batch async for batch in store.iter_batches()] == []


@redis_available
@redis_server_available
async def test_iter_batches_returns_async_generator(store: AsyncBaseRedisStore) -> None:
    assert isinstance(store.iter_batches(), AsyncIterator)


@redis_available
@redis_server_available
async def test_iter_batches_returns_all_key_value_pairs(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    async for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


@redis_available
@redis_server_available
async def test_iter_batches_yields_correct_batch_sizes(
    store: AsyncBaseRedisStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=2)]
    assert sorted(len(b) for b in batches) == [2, 2]


@redis_available
@redis_server_available
async def test_iter_batches_zero_batch_size_raises(store: AsyncBaseRedisStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.iter_batches(batch_size=0):
            pass


# --- close / context manager ---


@redis_available
@redis_server_available
async def test_close_is_idempotent(store: AsyncBaseRedisStore) -> None:
    await store.close()
    await store.close()  # should not raise


@redis_available
@redis_server_available
async def test_close_returns_none(store: AsyncBaseRedisStore) -> None:
    assert await store.close() is None


@redis_available
@redis_server_available
async def test_context_manager_returns_self(store_cls: type[AsyncBaseRedisStore]) -> None:
    async with store_cls(REDIS_URL) as store:
        assert isinstance(store, store_cls)
        await store.delete_many([key async for key in store.keys()])  # noqa: SIM118


@redis_available
@redis_server_available
async def test_context_manager_usable_for_reads_and_writes(
    store_cls: type[AsyncBaseRedisStore],
) -> None:
    async with store_cls(REDIS_URL) as store:
        await store.delete_many([key async for key in store.keys()])  # noqa: SIM118
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
        await store.delete_many([key async for key in store.keys()])  # noqa: SIM118


@redis_available
@redis_server_available
async def test_context_manager_multiple_open_close(
    store_cls: type[AsyncBaseRedisStore],
) -> None:
    redis_store = store_cls(REDIS_URL)
    try:
        async with redis_store as store:
            await store.delete_many([key async for key in store.keys()])  # noqa: SIM118
        for i in range(3):
            async with redis_store as store:
                await store.set(str(i), {"text": "hello"})
                assert await store.get(str(i)) == {"text": "hello"}
    finally:
        async with redis_store as store:
            await store.delete_many([key async for key in store.keys()])  # noqa: SIM118
