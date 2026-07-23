from __future__ import annotations

from collections.abc import Generator, Iterator

import pytest

from persista.store import NullStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> Generator[NullStore, None, None]:
    with NullStore() as store:
        yield store


###############################
#     Tests for NullStore     #
###############################


# --- repr/str ---


def test_repr(store: NullStore) -> None:
    assert repr(store).startswith("NullStore(")


def test_str(store: NullStore) -> None:
    assert str(store).startswith("NullStore(")


# --- set / get ---


def test_set_then_get_is_a_miss(store: NullStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.get("1") is None


def test_set_does_not_increase_count(store: NullStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.count() == 0


def test_get_missing_key_returns_none(store: NullStore) -> None:
    assert store.get("nonexistent") is None


def test_set_on_conflict_bogus_does_not_raise(store: NullStore) -> None:
    store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- set_many / get_many ---


def test_set_many_does_not_increase_count(store: NullStore) -> None:
    store.set_many({"1": {"text": "hello"}, "2": {"text": "world"}})
    assert store.count() == 0


def test_get_many_returns_none_for_every_key(store: NullStore) -> None:
    store.set_many({"1": {"text": "hello"}})
    assert store.get_many(["1", "2"]) == [None, None]


def test_get_many_preserves_length(store: NullStore) -> None:
    assert store.get_many(["1", "2", "3"]) == [None, None, None]


def test_get_many_empty_list_returns_empty_list(store: NullStore) -> None:
    assert store.get_many([]) == []


# --- set_batches ---


def test_set_batches_does_not_increase_count(store: NullStore) -> None:
    store.set_batches([("1", {"v": 1}), ("2", {"v": 2})])
    assert store.count() == 0


# --- filter ---


def test_filter_no_args_returns_empty(store: NullStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.filter() == []


def test_filter_with_args_returns_empty(store: NullStore) -> None:
    store.set("1", {"author": "Alice"})
    assert store.filter(author="Alice") == []


# --- delete / delete_many ---


def test_delete_is_silent(store: NullStore) -> None:
    store.delete("1")


def test_delete_many_is_silent(store: NullStore) -> None:
    store.delete_many(["1", "2"])


# --- contains ---


def test_contains_always_false(store: NullStore) -> None:
    store.set("1", {"text": "hello"})
    assert not store.contains("1")


# --- contains_many ---


def test_contains_many_all_missing(store: NullStore) -> None:
    store.set("1", {"text": "hello"})
    found, missing = store.contains_many(["1", "2"])
    assert found == []
    assert missing == ["1", "2"]


def test_contains_many_empty_input_returns_empty_lists(store: NullStore) -> None:
    found, missing = store.contains_many([])
    assert found == []
    assert missing == []


# --- keys ---


def test_keys_yields_nothing(store: NullStore) -> None:
    store.set("1", {"text": "hello"})
    assert list(store.keys()) == []


# --- values ---


def test_values_yields_nothing(store: NullStore) -> None:
    store.set("1", {"text": "hello"})
    assert list(store.values()) == []


# --- iter_batches ---


def test_iter_batches_yields_nothing(store: NullStore) -> None:
    store.set("1", {"text": "hello"})
    assert list(store.iter_batches()) == []


def test_iter_batches_returns_generator(store: NullStore) -> None:
    assert isinstance(store.iter_batches(), Iterator)


# --- count ---


def test_count_is_always_zero(store: NullStore) -> None:
    assert store.count() == 0
    store.set("1", {"text": "hello"})
    assert store.count() == 0


# --- close / closed ---


def test_close_is_idempotent(store: NullStore) -> None:
    store.close()
    store.close()


def test_close_returns_none(store: NullStore) -> None:
    assert store.close() is None


def test_closed_false_before_close(store: NullStore) -> None:
    assert not store.closed


def test_closed_true_after_close(store: NullStore) -> None:
    store.close()
    assert store.closed


# --- clear ---


def test_clear_returns_none(store: NullStore) -> None:
    assert store.clear() is None


# --- context manager ---


def test_context_manager_returns_self() -> None:
    with NullStore() as store:
        assert isinstance(store, NullStore)


def test_context_manager_closes_on_exception() -> None:
    msg = "boom"
    with pytest.raises(ValueError, match="boom"), NullStore() as store:
        raise ValueError(msg)

    assert store.closed


# --- to_uri / from_uri ---


def test_to_uri_returns_null_scheme(store: NullStore) -> None:
    assert store.to_uri() == "null://"


def test_from_uri_returns_new_store() -> None:
    store = NullStore.from_uri("null://")
    assert store.count() == 0
    assert not store.closed


# --- async ---


async def test_null_store_aget_always_none() -> None:
    store = NullStore()
    await store.aset("1", {"a": 1})
    assert await store.aget("1") is None


async def test_null_store_acontains_always_false() -> None:
    store = NullStore()
    await store.aset("1", {"a": 1})
    assert await store.acontains("1") is False


async def test_null_store_acount_always_zero() -> None:
    store = NullStore()
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert await store.acount() == 0


async def test_null_store_akeys_empty() -> None:
    store = NullStore()
    keys = [key async for key in store.akeys()]
    assert keys == []


async def test_null_store_aiter_batches_empty() -> None:
    store = NullStore()
    batches = [batch async for batch in store.aiter_batches()]
    assert batches == []


async def test_null_store_afilter_always_empty() -> None:
    store = NullStore()
    await store.aset("1", {"a": 1})
    assert await store.afilter(a=1) == []


async def test_null_store_async_context_manager() -> None:
    async with NullStore() as store:
        assert not store.closed
    assert store.closed
