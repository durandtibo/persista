from __future__ import annotations

import threading
from collections.abc import Generator, Iterator
from typing import Any

import pytest

from persista.store import InMemoryStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> Generator[InMemoryStore, None, None]:
    with InMemoryStore() as store:
        yield store


###################################
#     Tests for InMemoryStore     #
###################################


def test_data(store: InMemoryStore) -> None:
    assert store.data == {}


def test_add_data(store: InMemoryStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.data == {"1": {"text": "hello"}}


# --- repr/str ---


def test_repr(store: InMemoryStore) -> None:
    assert repr(store).startswith("InMemoryStore(")


def test_str(store: InMemoryStore) -> None:
    assert str(store).startswith("InMemoryStore(")


# --- set ---


def test_set_increases_count(store: InMemoryStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.count() == 1


def test_set_stores_value(store: InMemoryStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.get("1") == {"text": "hello"}


def test_set_default_overwrites_existing(store: InMemoryStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


def test_set_on_conflict_raise(store: InMemoryStore) -> None:
    store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        store.set("1", {"text": "updated"}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}


def test_set_on_conflict_skip(store: InMemoryStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}


def test_set_on_conflict_overwrite(store: InMemoryStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}


def test_set_on_conflict_merge(store: InMemoryStore) -> None:
    store.set("1", {"text": "original", "author": "Alice"})
    store.set("1", {"text": "updated"}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


def test_set_on_conflict_new_key_is_unaffected(store: InMemoryStore) -> None:
    store.set("1", {"text": "hello"}, on_conflict="raise")
    assert store.get("1") == {"text": "hello"}


def test_set_on_conflict_invalid_raises(store: InMemoryStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set("1", {"text": "hello"}, on_conflict="bogus")


def test_set_does_not_alias_input(store: InMemoryStore) -> None:
    value = {"text": "hello"}
    store.set("1", value)
    value["text"] = "mutated"
    assert store.get("1") == {"text": "hello"}


# --- set_many ---


def test_set_many_increases_count(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


def test_set_many_empty_is_no_op(store: InMemoryStore) -> None:
    store.set_many({})
    assert store.count() == 0


def test_set_many_default_overwrites_existing(store: InMemoryStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


def test_set_many_on_conflict_raise(store: InMemoryStore) -> None:
    store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    # nothing from the conflicting batch should have been written
    assert store.get("1") == {"text": "original"}
    assert store.get("3") is None


def test_set_many_on_conflict_skip(store: InMemoryStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


def test_set_many_on_conflict_overwrite(store: InMemoryStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}
    assert store.get("2") == {"text": "new"}


def test_set_many_on_conflict_merge(store: InMemoryStore) -> None:
    store.set_many({"1": {"text": "original", "author": "Alice"}})
    store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


def test_set_many_on_conflict_invalid_raises(store: InMemoryStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set_many({"1": {"text": "hello"}}, on_conflict="bogus")


def test_set_many_does_not_alias_input(store: InMemoryStore) -> None:
    value = {"text": "hello"}
    store.set_many({"1": value})
    value["text"] = "mutated"
    assert store.get("1") == {"text": "hello"}


# --- set_batches ---


def test_set_batches_empty_is_no_op(store: InMemoryStore) -> None:
    store.set_batches([])
    assert store.count() == 0


def test_set_batches_writes_all_pairs(store: InMemoryStore) -> None:
    store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert store.count() == 3
    assert store.get("2") == {"v": 2}


def test_set_batches_consumes_a_generator(store: InMemoryStore) -> None:
    def gen() -> Iterator[tuple[str, dict[str, int]]]:
        for i in range(5):
            yield str(i), {"v": i}

    store.set_batches(gen(), batch_size=2)
    assert store.count() == 5


def test_set_batches_default_overwrites_existing(store: InMemoryStore) -> None:
    store.set("1", {"text": "original"})
    store.set_batches([("1", {"text": "updated"})])
    assert store.get("1") == {"text": "updated"}


def test_set_batches_on_conflict_raise_stops_at_offending_batch(store: InMemoryStore) -> None:
    store.set("2", {"text": "original"})
    with pytest.raises(KeyError, match=r"2"):
        store.set_batches(
            [("1", {"text": "a"}), ("2", {"text": "b"}), ("3", {"text": "c"})],
            batch_size=2,
            on_conflict="raise",
        )
    # first batch (keys 1 and 2) failed entirely, so "1" was never written
    assert store.get("1") is None
    # the conflicting key keeps its original value
    assert store.get("2") == {"text": "original"}
    # the third item was never reached because the second batch raised
    assert store.get("3") is None


def test_set_batches_on_conflict_skip(store: InMemoryStore) -> None:
    store.set("1", {"text": "original"})
    store.set_batches([("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


# --- get ---


def test_get_existing_value(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.get("1") == items["1"]


def test_get_missing_key_returns_none(store: InMemoryStore) -> None:
    assert store.get("nonexistent") is None


def test_get_returns_a_copy(store: InMemoryStore) -> None:
    store.set("1", {"tags": ["a"]})
    value = store.get("1")
    value["tags"].append("b")
    assert store.get("1") == {"tags": ["a"]}


# --- get_many ---


def test_get_many_returns_correct_length(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert len(store.get_many(["1", "2", "99"])) == 3


def test_get_many_returns_none_for_missing(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["1", "99", "2"])
    assert result[1] is None


def test_get_many_preserves_order(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


def test_get_many_empty_list_returns_empty_list(store: InMemoryStore) -> None:
    assert store.get_many([]) == []


# --- filter ---


def test_filter_no_args_returns_all(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert len(store.filter()) == len(items)


def test_filter_single_field(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


def test_filter_multiple_fields(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice", category="Programming")
    assert len(result) == 2


def test_filter_no_match_returns_empty(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.filter(author="Charlie") == []


def test_filter_preserves_full_value(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.filter(author="Bob", category="History")
    expected = [v for v in items.values() if v["author"] == "Bob"]
    assert sorted(result, key=lambda v: v["title"]) == sorted(expected, key=lambda v: v["title"])


def test_filter_empty_store_returns_empty(store: InMemoryStore) -> None:
    assert store.filter(author="Alice") == []


def test_filter_returns_copies(store: InMemoryStore) -> None:
    store.set("1", {"tags": ["a"]})
    result = store.filter()
    result[0]["tags"].append("b")
    assert store.get("1") == {"tags": ["a"]}


# --- delete ---


def test_delete_removes_value(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete("1")
    assert store.count() == len(items) - 1
    assert store.get("1") is None


def test_delete_nonexistent_is_silent(store: InMemoryStore) -> None:
    store.delete("nonexistent")


# --- delete_many ---


def test_delete_many_removes_values(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.count() == len(items) - 2
    assert store.get("1") is None
    assert store.get("3") is None


def test_delete_many_preserves_other_values(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.get("2") is not None
    assert store.get("4") is not None


def test_delete_many_empty_list_is_no_op(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many([])
    assert store.count() == len(items)


def test_delete_many_nonexistent_keys_are_silent(store: InMemoryStore) -> None:
    store.delete_many(["99", "100"])


def test_delete_many_single_key(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["2"])
    assert store.count() == len(items) - 1
    assert store.get("2") is None


# --- contains ---


def test_contains_true_when_key_present(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.contains("1")


def test_contains_false_when_key_missing(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert not store.contains("99")


def test_contains_false_when_store_empty(store: InMemoryStore) -> None:
    assert not store.contains("1")


# --- contains_many ---


def test_contains_many_all_found(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.contains_many(["1", "2", "3", "4"]) == [True, True, True, True]


def test_contains_many_all_missing(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.contains_many(["99", "100"]) == [False, False]


def test_contains_many_mixed(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.contains_many(["1", "99", "3", "42"]) == [True, False, True, False]


def test_contains_many_preserves_order(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.contains_many(["3", "99", "1", "42", "2"]) == [True, False, True, False, True]


def test_contains_many_empty_input_returns_empty_lists(store: InMemoryStore) -> None:
    assert store.contains_many([]) == []


def test_contains_many_empty_store_returns_all_missing(store: InMemoryStore) -> None:
    assert store.contains_many(["1", "2"]) == [False, False]


def test_contains_many_returns_list_of_bools(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.contains_many(["1", "99"])
    assert isinstance(result, list)
    assert all(isinstance(flag, bool) for flag in result)


# --- keys ---


def test_keys_empty_store_yields_nothing(store: InMemoryStore) -> None:
    assert list(store.keys()) == []


def test_keys_returns_all_keys(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert sorted(store.keys()) == sorted(items.keys())


def test_keys_is_lazy_not_exhausted_on_creation(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    """Calling keys() should not itself execute the query eagerly;
    deleting a key after creating the generator but before the first
    next() call should still be reflected, confirming the query executes
    lazily."""
    gen = store.keys()
    store.set_many(items)
    store.delete("1")
    assert sorted(gen) == sorted(k for k in items if k != "1")


# --- values ---


def test_values_empty_store_yields_nothing(store: InMemoryStore) -> None:
    assert list(store.values()) == []


def test_values_returns_all_values(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = list(store.values())
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


def test_values_is_lazy_generator(store: InMemoryStore) -> None:
    assert isinstance(store.values(), Iterator)


# --- iter_batches ---


def test_iter_batches_empty_store_yields_nothing(store: InMemoryStore) -> None:
    assert list(store.iter_batches()) == []


def test_iter_batches_returns_generator(store: InMemoryStore) -> None:
    result = store.iter_batches()
    assert isinstance(result, Iterator)


def test_iter_batches_default_batch_size(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches())
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


def test_iter_batches_yields_correct_batch_sizes(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert [len(b) for b in batches] == [2, 2]


def test_iter_batches_last_batch_may_be_smaller(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=3))
    assert [len(b) for b in batches] == [3, 1]


def test_iter_batches_batch_size_larger_than_store(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=100))
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


def test_iter_batches_batch_size_one(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=1))
    assert [len(b) for b in batches] == [1, 1, 1, 1]


def test_iter_batches_returns_all_key_value_pairs(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


def test_iter_batches_batches_are_dicts(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert all(isinstance(batch, dict) for batch in batches)


def test_iter_batches_zero_batch_size_raises(store: InMemoryStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=0))


def test_iter_batches_negative_batch_size_raises(store: InMemoryStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=-1))


def test_iter_batches_error_raised_before_any_query(store: InMemoryStore) -> None:
    """The ValueError should be raised eagerly on the first call to
    next(), not silently swallowed by generator laziness."""
    gen = store.iter_batches(batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        next(gen)


def test_iter_batches_does_not_mutate_store(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    list(store.iter_batches(batch_size=2))
    assert store.count() == len(items)


def test_iter_batches_survives_concurrent_mutation(store: InMemoryStore) -> None:
    """iter_batches snapshots the store up front, so a set() call
    interleaved between batches must not raise "dictionary changed size
    during iteration"."""
    for i in range(5):
        store.set(str(i), {"a": i})
    gen = store.iter_batches(batch_size=2)
    first = next(gen)
    store.set("new", {"a": 99})
    remaining = list(gen)
    assert len(first) == 2
    assert sum(len(batch) for batch in remaining) == 3
    assert store.count() == 6


# --- count ---


def test_count_empty_store(store: InMemoryStore) -> None:
    assert store.count() == 0


def test_count_after_set_many(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


# --- close ---


def test_close_discards_values(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.close()
    store.open()
    assert store.count() == 0


def test_close_is_idempotent(store: InMemoryStore) -> None:
    store.close()
    store.close()  # should not raise


def test_get_before_open_raises() -> None:
    store = InMemoryStore()
    with pytest.raises(RuntimeError, match="not open"):
        store.get("1")


def test_close_returns_none(store: InMemoryStore) -> None:
    assert store.close() is None


def test_get_after_close_returns_none(store: InMemoryStore) -> None:
    store.set("1", {"text": "hello"})
    store.close()
    store.open()
    assert store.get("1") is None


def test_set_after_close_is_usable_again(store: InMemoryStore) -> None:
    store.close()
    store.open()
    store.set("1", {"text": "hello"})
    assert store.get("1") == {"text": "hello"}
    assert store.count() == 1


# --- closed ---


def test_closed_false_before_close(store: InMemoryStore) -> None:
    assert not store.closed


def test_closed_true_after_close(store: InMemoryStore) -> None:
    store.close()
    assert store.closed


# --- context manager ---


def test_context_manager_returns_self() -> None:
    with InMemoryStore() as store:
        assert isinstance(store, InMemoryStore)


def test_context_manager_closes_on_normal_exit() -> None:
    with InMemoryStore() as store:
        store.set("1", {"text": "hello"})
        assert store.count() == 1

    # Closing an in-memory store discards its values.
    assert store.closed


def test_context_manager_closes_on_exception() -> None:
    msg = "boom"
    with pytest.raises(ValueError, match="boom"), InMemoryStore() as store:
        raise ValueError(msg)

    assert store.closed


def test_context_manager_usable_for_reads_and_writes() -> None:
    with InMemoryStore() as store:
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


# --- clear ---


def test_clear_removes_all_values(store: InMemoryStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.clear()
    assert store.count() == 0
    assert store.data == {}


def test_clear_empty_store_is_no_op(store: InMemoryStore) -> None:
    store.clear()
    assert store.count() == 0


def test_clear_returns_none(store: InMemoryStore) -> None:
    assert store.clear() is None


def test_clear_then_set_works(store: InMemoryStore) -> None:
    store.set("1", {"text": "hello"})
    store.clear()
    store.set("2", {"text": "world"})
    assert store.count() == 1
    assert store.get("2") == {"text": "world"}


def test_context_manager_multiple_open_close() -> None:
    in_memory_store = InMemoryStore()
    for i in range(3):
        with in_memory_store as store:
            assert not store.closed
            assert store.count() == 0
            store.set(str(i), {"text": "hello"})
            assert store.count() == 1
        assert store.closed


def test_context_manager_reopen_resets_closed() -> None:
    """Regression test: reopening via `with` must reset `closed` to False,
    matching every other store backend."""
    store = InMemoryStore()
    store.close()
    assert store.closed
    with store:
        assert not store.closed
    assert store.closed


# --- to_uri/from_uri ---


def test_to_uri_returns_memory_scheme(store: InMemoryStore) -> None:
    assert store.to_uri() == "memory://"


def test_from_uri_returns_empty_store() -> None:
    store = InMemoryStore.from_uri("memory://")
    store.open()
    assert store.count() == 0


def test_to_uri_from_uri_does_not_carry_data(
    store: InMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    reloaded = InMemoryStore.from_uri(store.to_uri())
    reloaded.open()
    assert reloaded.count() == 0


# --- async (via ThreadedAsyncStoreMixin) ---


# --- aget / aset ---


async def test_in_memory_store_aget_aset_round_trip(store: InMemoryStore) -> None:
    await store.aset("1", {"text": "hello"})
    assert await store.aget("1") == {"text": "hello"}


# --- aset_many ---


async def test_in_memory_store_aset_many_on_conflict_merge(store: InMemoryStore) -> None:
    await store.aset("1", {"a": 1})
    await store.aset_many({"1": {"b": 2}}, on_conflict="merge")
    assert await store.aget("1") == {"a": 1, "b": 2}


# --- afilter ---


async def test_in_memory_store_afilter(store: InMemoryStore) -> None:
    await store.aset_many({"1": {"author": "Alice"}, "2": {"author": "Bob"}})
    assert await store.afilter(author="Alice") == [{"author": "Alice"}]


# --- acount / aclear ---


async def test_in_memory_store_acount_and_aclear(store: InMemoryStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert await store.acount() == 2
    await store.aclear()
    assert await store.acount() == 0


# --- akeys ---


async def test_in_memory_store_akeys(store: InMemoryStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert sorted([key async for key in store.akeys()]) == ["1", "2"]


# --- aclose ---


async def test_in_memory_store_aclose_clears_data() -> None:
    store = InMemoryStore()
    await store.aopen()
    await store.aset("1", {"a": 1})
    await store.aclose()
    assert store.closed


# --- avalues ---


async def test_in_memory_store_avalues_iterates_all(store: InMemoryStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    values = [v async for v in store.avalues(batch_size=2)]
    assert sorted(v["a"] for v in values) == [1, 2, 3]


# --- aset_batches ---


async def test_in_memory_store_aset_batches(store: InMemoryStore) -> None:
    await store.aset_batches([("1", {"a": 1}), ("2", {"a": 2})], batch_size=1)
    assert await store.acount() == 2


# --- adelete_many ---


async def test_in_memory_store_adelete_many(store: InMemoryStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    await store.adelete_many(["1", "2"])
    assert sorted([key async for key in store.akeys()]) == ["3"]


# --- acontains_many ---


async def test_in_memory_store_acontains_many(store: InMemoryStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    assert await store.acontains_many(["1", "2", "3"]) == [True, True, False]


# --- context manager ---


async def test_in_memory_store_async_context_manager_returns_self() -> None:
    async with InMemoryStore() as store:
        assert isinstance(store, InMemoryStore)


async def test_in_memory_store_async_context_manager_closes_on_normal_exit() -> None:
    async with InMemoryStore() as store:
        await store.aset("1", {"text": "hello"})
        assert await store.acount() == 1

    assert store.closed


async def test_in_memory_store_async_context_manager_closes_on_exception() -> None:
    msg = "boom"
    with pytest.raises(ValueError, match="boom"):
        async with InMemoryStore() as store:
            raise ValueError(msg)

    assert store.closed


# --- aiter_batches ---


async def test_in_memory_store_aiter_batches_yields_correct_batch_sizes(
    store: InMemoryStore,
) -> None:
    await store.aset_many({str(i): {"a": i} for i in range(5)})
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert [len(batch) for batch in batches] == [2, 2, 1]


# --- aset / aget edge cases ---


async def test_in_memory_store_aset_does_not_alias_input(store: InMemoryStore) -> None:
    value = {"text": "hello"}
    await store.aset("1", value)
    value["text"] = "mutated"
    assert await store.aget("1") == {"text": "hello"}


async def test_in_memory_store_aget_returns_a_copy(store: InMemoryStore) -> None:
    await store.aset("1", {"tags": ["a"]})
    value = await store.aget("1")
    value["tags"].append("b")
    assert await store.aget("1") == {"tags": ["a"]}


async def test_in_memory_store_aiter_batches_zero_batch_size_raises(store: InMemoryStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        _ = [batch async for batch in store.aiter_batches(batch_size=0)]


async def test_in_memory_store_aiter_batches_negative_batch_size_raises(
    store: InMemoryStore,
) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        _ = [batch async for batch in store.aiter_batches(batch_size=-1)]


# --- concurrency ---


def test_concurrent_set_many_merge_does_not_lose_updates(store: InMemoryStore) -> None:
    """Many threads each merge a distinct field into the same key.

    The store's lock must serialize the check-then-act merge sequence,
    or concurrent writers reading the same stale base value would
    clobber each other's fields (a lost update).
    """
    store.set("k", {})
    n_threads = 16
    barrier = threading.Barrier(n_threads)

    def merge_one(i: int) -> None:
        barrier.wait()
        store.set("k", {f"field_{i}": i}, on_conflict="merge")

    threads = [threading.Thread(target=merge_one, args=(i,)) for i in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    result = store.get("k")
    assert result == {f"field_{i}": i for i in range(n_threads)}


def test_concurrent_set_on_conflict_raise_never_corrupts_value(store: InMemoryStore) -> None:
    """When many threads race to create the same key with
    on_conflict="raise", exactly one write must win and the stored value
    must be a single writer's value, not a mix."""
    n_threads = 16
    barrier = threading.Barrier(n_threads)
    successes: list[int] = []
    lock = threading.Lock()

    def create_one(i: int) -> None:
        barrier.wait()
        try:
            store.set("k", {"writer": i}, on_conflict="raise")
        except KeyError:
            return
        with lock:
            successes.append(i)

    threads = [threading.Thread(target=create_one, args=(i,)) for i in range(n_threads)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(successes) == 1
    assert store.get("k") == {"writer": successes[0]}
