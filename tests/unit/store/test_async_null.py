from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from persista.store import AsyncNullStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store() -> AsyncNullStore:
    return AsyncNullStore()


####################################
#     Tests for AsyncNullStore     #
####################################


# --- repr/str ---


async def test_repr(store: AsyncNullStore) -> None:
    assert repr(store).startswith("AsyncNullStore(")


async def test_str(store: AsyncNullStore) -> None:
    assert str(store).startswith("AsyncNullStore(")


# --- set / get ---


async def test_set_then_get_is_a_miss(store: AsyncNullStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.get("1") is None


async def test_set_does_not_increase_count(store: AsyncNullStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.count() == 0


async def test_get_missing_key_returns_none(store: AsyncNullStore) -> None:
    assert await store.get("nonexistent") is None


async def test_set_on_conflict_bogus_does_not_raise(store: AsyncNullStore) -> None:
    await store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- set_many / get_many ---


async def test_set_many_does_not_increase_count(store: AsyncNullStore) -> None:
    await store.set_many({"1": {"text": "hello"}, "2": {"text": "world"}})
    assert await store.count() == 0


async def test_get_many_returns_none_for_every_key(store: AsyncNullStore) -> None:
    await store.set_many({"1": {"text": "hello"}})
    assert await store.get_many(["1", "2"]) == [None, None]


async def test_get_many_preserves_length(store: AsyncNullStore) -> None:
    assert await store.get_many(["1", "2", "3"]) == [None, None, None]


async def test_get_many_empty_list_returns_empty_list(store: AsyncNullStore) -> None:
    assert await store.get_many([]) == []


# --- set_batches ---


async def test_set_batches_does_not_increase_count(store: AsyncNullStore) -> None:
    await store.set_batches([("1", {"v": 1}), ("2", {"v": 2})])
    assert await store.count() == 0


# --- filter ---


async def test_filter_no_args_returns_empty(store: AsyncNullStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.filter() == []


async def test_filter_with_args_returns_empty(store: AsyncNullStore) -> None:
    await store.set("1", {"author": "Alice"})
    assert await store.filter(author="Alice") == []


# --- delete / delete_many ---


async def test_delete_is_silent(store: AsyncNullStore) -> None:
    await store.delete("1")


async def test_delete_many_is_silent(store: AsyncNullStore) -> None:
    await store.delete_many(["1", "2"])


# --- contains ---


async def test_contains_always_false(store: AsyncNullStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.contains("1") is False


# --- contains_many ---


async def test_contains_many_all_missing(store: AsyncNullStore) -> None:
    await store.set("1", {"text": "hello"})
    found, missing = await store.contains_many(["1", "2"])
    assert found == []
    assert missing == ["1", "2"]


async def test_contains_many_empty_input_returns_empty_lists(store: AsyncNullStore) -> None:
    found, missing = await store.contains_many([])
    assert found == []
    assert missing == []


# --- keys ---


async def test_keys_yields_nothing(store: AsyncNullStore) -> None:
    await store.set("1", {"text": "hello"})
    result = [key async for key in store.keys()]  # noqa: SIM118
    assert result == []


# --- values ---


async def test_values_yields_nothing(store: AsyncNullStore) -> None:
    await store.set("1", {"text": "hello"})
    assert [value async for value in store.values()] == []


# --- iter_batches ---


async def test_iter_batches_yields_nothing(store: AsyncNullStore) -> None:
    await store.set("1", {"text": "hello"})
    assert [batch async for batch in store.iter_batches()] == []


async def test_iter_batches_returns_async_iterator(store: AsyncNullStore) -> None:
    assert isinstance(store.iter_batches(), AsyncIterator)


# --- count ---


async def test_count_is_always_zero(store: AsyncNullStore) -> None:
    assert await store.count() == 0
    await store.set("1", {"text": "hello"})
    assert await store.count() == 0


# --- close / closed ---


async def test_close_is_idempotent(store: AsyncNullStore) -> None:
    await store.close()
    await store.close()


async def test_close_returns_none(store: AsyncNullStore) -> None:
    assert await store.close() is None


async def test_closed_false_before_close(store: AsyncNullStore) -> None:
    assert not store.closed


async def test_closed_true_after_close(store: AsyncNullStore) -> None:
    await store.close()
    assert store.closed


# --- clear ---


async def test_clear_returns_none(store: AsyncNullStore) -> None:
    assert await store.clear() is None


# --- context manager ---


async def test_context_manager_returns_self() -> None:
    async with AsyncNullStore() as store:
        assert isinstance(store, AsyncNullStore)


async def test_context_manager_closes_on_exception() -> None:
    msg = "boom"
    store = AsyncNullStore()
    with pytest.raises(ValueError, match="boom"):
        async with store:
            raise ValueError(msg)

    assert store.closed
