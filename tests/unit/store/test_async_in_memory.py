from __future__ import annotations

from typing import Any

import pytest

from persista.store import AsyncInMemoryStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store() -> AsyncInMemoryStore:
    return AsyncInMemoryStore()


@pytest.fixture
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


########################################
#     Tests for AsyncInMemoryStore     #
########################################


async def test_data(store: AsyncInMemoryStore) -> None:
    assert store.data == {}


async def test_add_data(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"text": "hello"})
    assert store.data == {"1": {"text": "hello"}}


# --- repr/str ---


async def test_repr(store: AsyncInMemoryStore) -> None:
    assert repr(store).startswith("AsyncInMemoryStore(")


async def test_str(store: AsyncInMemoryStore) -> None:
    assert str(store).startswith("AsyncInMemoryStore(")


# --- set ---


async def test_set_increases_count(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.count() == 1


async def test_set_stores_value(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.get("1") == {"text": "hello"}


async def test_set_default_overwrites_existing(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"})
    assert await store.count() == 1
    assert await store.get("1") == {"text": "updated"}


async def test_set_on_conflict_raise(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        await store.set("1", {"text": "updated"}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}


async def test_set_on_conflict_skip(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}


async def test_set_on_conflict_overwrite(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert await store.get("1") == {"text": "updated"}


async def test_set_on_conflict_merge(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"text": "original", "author": "Alice"})
    await store.set("1", {"text": "updated"}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


async def test_set_on_conflict_new_key_is_unaffected(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"text": "hello"}, on_conflict="raise")
    assert await store.get("1") == {"text": "hello"}


async def test_set_on_conflict_invalid_raises(store: AsyncInMemoryStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.set("1", {"text": "hello"}, on_conflict="bogus")


async def test_set_does_not_alias_input(store: AsyncInMemoryStore) -> None:
    value = {"text": "hello"}
    await store.set("1", value)
    value["text"] = "mutated"
    assert await store.get("1") == {"text": "hello"}


# --- set_many ---


async def test_set_many_increases_count(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


async def test_set_many_empty_is_no_op(store: AsyncInMemoryStore) -> None:
    await store.set_many({})
    assert await store.count() == 0


async def test_set_many_default_overwrites_existing(store: AsyncInMemoryStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}})
    assert await store.count() == 1
    assert await store.get("1") == {"text": "updated"}


async def test_set_many_on_conflict_raise(store: AsyncInMemoryStore) -> None:
    await store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        await store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    # nothing from the conflicting batch should have been written
    assert await store.get("1") == {"text": "original"}
    assert await store.get("3") is None


async def test_set_many_on_conflict_skip(store: AsyncInMemoryStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("2") == {"text": "new"}


async def test_set_many_on_conflict_overwrite(store: AsyncInMemoryStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert await store.get("1") == {"text": "updated"}
    assert await store.get("2") == {"text": "new"}


async def test_set_many_on_conflict_merge(store: AsyncInMemoryStore) -> None:
    await store.set_many({"1": {"text": "original", "author": "Alice"}})
    await store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


async def test_set_many_on_conflict_invalid_raises(store: AsyncInMemoryStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.set_many({"1": {"text": "hello"}}, on_conflict="bogus")


async def test_set_many_does_not_alias_input(store: AsyncInMemoryStore) -> None:
    value = {"text": "hello"}
    await store.set_many({"1": value})
    value["text"] = "mutated"
    assert await store.get("1") == {"text": "hello"}


# --- set_batches ---


async def test_set_batches_empty_is_no_op(store: AsyncInMemoryStore) -> None:
    await store.set_batches([])
    assert await store.count() == 0


async def test_set_batches_writes_all_pairs(store: AsyncInMemoryStore) -> None:
    await store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert await store.count() == 3
    assert await store.get("2") == {"v": 2}


async def test_set_batches_default_overwrites_existing(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set_batches([("1", {"text": "updated"})])
    assert await store.get("1") == {"text": "updated"}


async def test_set_batches_on_conflict_raise_stops_at_offending_batch(
    store: AsyncInMemoryStore,
) -> None:
    await store.set("2", {"text": "original"})
    with pytest.raises(KeyError, match=r"2"):
        await store.set_batches(
            [("1", {"text": "a"}), ("2", {"text": "b"}), ("3", {"text": "c"})],
            batch_size=2,
            on_conflict="raise",
        )
    assert await store.get("1") is None
    assert await store.get("2") == {"text": "original"}
    assert await store.get("3") is None


async def test_set_batches_on_conflict_skip(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set_batches(
        [("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip"
    )
    assert await store.get("1") == {"text": "original"}
    assert await store.get("2") == {"text": "new"}


# --- get ---


async def test_get_existing_value(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.get("1") == items["1"]


async def test_get_missing_key_returns_none(store: AsyncInMemoryStore) -> None:
    assert await store.get("nonexistent") is None


async def test_get_returns_a_copy(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"tags": ["a"]})
    value = await store.get("1")
    assert value is not None
    value["tags"].append("b")
    assert await store.get("1") == {"tags": ["a"]}


# --- get_many ---


async def test_get_many_returns_correct_length(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.get_many(["1", "2", "99"])) == 3


async def test_get_many_returns_none_for_missing(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["1", "99", "2"])
    assert result[1] is None


async def test_get_many_preserves_order(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


async def test_get_many_empty_list_returns_empty_list(store: AsyncInMemoryStore) -> None:
    assert await store.get_many([]) == []


# --- filter ---


async def test_filter_no_args_returns_all(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.filter()) == len(items)


async def test_filter_single_field(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


async def test_filter_multiple_fields(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice", category="Programming")
    assert len(result) == 2


async def test_filter_no_match_returns_empty(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.filter(author="Charlie") == []


async def test_filter_preserves_full_value(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Bob", category="History")
    expected = [v for v in items.values() if v["author"] == "Bob"]
    assert sorted(result, key=lambda v: v["title"]) == sorted(expected, key=lambda v: v["title"])


async def test_filter_empty_store_returns_empty(store: AsyncInMemoryStore) -> None:
    assert await store.filter(author="Alice") == []


async def test_filter_returns_copies(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"tags": ["a"]})
    result = await store.filter()
    result[0]["tags"].append("b")
    assert await store.get("1") == {"tags": ["a"]}


# --- delete ---


async def test_delete_removes_value(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete("1")
    assert await store.count() == len(items) - 1
    assert await store.get("1") is None


async def test_delete_nonexistent_is_silent(store: AsyncInMemoryStore) -> None:
    await store.delete("nonexistent")


# --- delete_many ---


async def test_delete_many_removes_values(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["1", "3"])
    assert await store.count() == len(items) - 2
    assert await store.get("1") is None
    assert await store.get("3") is None


async def test_delete_many_preserves_other_values(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["1", "3"])
    assert await store.get("2") is not None
    assert await store.get("4") is not None


async def test_delete_many_empty_list_is_no_op(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many([])
    assert await store.count() == len(items)


async def test_delete_many_nonexistent_keys_are_silent(store: AsyncInMemoryStore) -> None:
    await store.delete_many(["99", "100"])


async def test_delete_many_single_key(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["2"])
    assert await store.count() == len(items) - 1
    assert await store.get("2") is None


# --- contains ---


async def test_contains_true_when_key_present(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.contains("1")


async def test_contains_false_when_key_missing(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert not await store.contains("99")


async def test_contains_false_when_store_empty(store: AsyncInMemoryStore) -> None:
    assert not await store.contains("1")


# --- contains_many ---


async def test_contains_many_all_found(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["1", "2", "3", "4"])
    assert found == ["1", "2", "3", "4"]
    assert missing == []


async def test_contains_many_all_missing(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["99", "100"])
    assert found == []
    assert missing == ["99", "100"]


async def test_contains_many_mixed(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["1", "99", "3", "42"])
    assert found == ["1", "3"]
    assert missing == ["99", "42"]


async def test_contains_many_preserves_order(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["3", "99", "1", "42", "2"])
    assert found == ["3", "1", "2"]
    assert missing == ["99", "42"]


async def test_contains_many_empty_input_returns_empty_lists(store: AsyncInMemoryStore) -> None:
    found, missing = await store.contains_many([])
    assert found == []
    assert missing == []


async def test_contains_many_empty_store_returns_all_missing(store: AsyncInMemoryStore) -> None:
    found, missing = await store.contains_many(["1", "2"])
    assert found == []
    assert missing == ["1", "2"]


async def test_contains_many_returns_tuple_of_two_lists(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.contains_many(["1", "99"])
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


# --- keys ---


async def test_keys_empty_store_yields_nothing(store: AsyncInMemoryStore) -> None:
    assert [key async for key in store.keys()] == []  # noqa: SIM118


async def test_keys_returns_all_keys(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [key async for key in store.keys()]  # noqa: SIM118
    assert sorted(result) == sorted(items.keys())


# --- values ---


async def test_values_empty_store_yields_nothing(store: AsyncInMemoryStore) -> None:
    assert [value async for value in store.values()] == []


async def test_values_returns_all_values(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [value async for value in store.values()]
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


# --- iter_batches ---


async def test_iter_batches_empty_store_yields_nothing(store: AsyncInMemoryStore) -> None:
    assert [batch async for batch in store.iter_batches()] == []


async def test_iter_batches_default_batch_size(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches()]
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


async def test_iter_batches_yields_correct_batch_sizes(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=2)]
    assert [len(b) for b in batches] == [2, 2]


async def test_iter_batches_last_batch_may_be_smaller(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=3)]
    assert [len(b) for b in batches] == [3, 1]


async def test_iter_batches_returns_all_key_value_pairs(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    async for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


async def test_iter_batches_zero_batch_size_raises(store: AsyncInMemoryStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.iter_batches(batch_size=0):
            pass


async def test_iter_batches_negative_batch_size_raises(store: AsyncInMemoryStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.iter_batches(batch_size=-1):
            pass


async def test_iter_batches_does_not_mutate_store(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    async for _ in store.iter_batches(batch_size=2):
        pass
    assert await store.count() == len(items)


# --- count ---


async def test_count_empty_store(store: AsyncInMemoryStore) -> None:
    assert await store.count() == 0


async def test_count_after_set_many(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


# --- close ---


async def test_close_discards_values(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.close()
    assert await store.count() == 0


async def test_close_is_idempotent(store: AsyncInMemoryStore) -> None:
    await store.close()
    await store.close()  # should not raise


async def test_close_returns_none(store: AsyncInMemoryStore) -> None:
    assert await store.close() is None


# --- closed ---


async def test_closed_false_before_close(store: AsyncInMemoryStore) -> None:
    assert not store.closed


async def test_closed_true_after_close(store: AsyncInMemoryStore) -> None:
    await store.close()
    assert store.closed


# --- clear ---


async def test_clear_removes_all_values(
    store: AsyncInMemoryStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.clear()
    assert await store.count() == 0
    assert store.data == {}


async def test_clear_empty_store_is_no_op(store: AsyncInMemoryStore) -> None:
    await store.clear()
    assert await store.count() == 0


async def test_clear_returns_none(store: AsyncInMemoryStore) -> None:
    assert await store.clear() is None


async def test_clear_then_set_works(store: AsyncInMemoryStore) -> None:
    await store.set("1", {"text": "hello"})
    await store.clear()
    await store.set("2", {"text": "world"})
    assert await store.count() == 1
    assert await store.get("2") == {"text": "world"}


# --- context manager ---


async def test_context_manager_returns_self() -> None:
    async with AsyncInMemoryStore() as store:
        assert isinstance(store, AsyncInMemoryStore)


async def test_context_manager_closes_on_normal_exit() -> None:
    async with AsyncInMemoryStore() as store:
        await store.set("1", {"text": "hello"})
        assert await store.count() == 1

    # Closing an in-memory store discards its values.
    assert await store.count() == 0


async def test_context_manager_closes_on_exception() -> None:
    msg = "boom"
    store = AsyncInMemoryStore()
    with pytest.raises(ValueError, match="boom"):
        async with store:
            raise ValueError(msg)

    assert await store.count() == 0


async def test_context_manager_usable_for_reads_and_writes() -> None:
    async with AsyncInMemoryStore() as store:
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
