from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from persista.store import AsyncSQLiteStore
from persista.testing.fixtures import aiosqlite_available

if TYPE_CHECKING:
    from pathlib import Path

aiosqlite = pytest.importorskip("aiosqlite")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def store() -> AsyncSQLiteStore:
    return AsyncSQLiteStore(":memory:")


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


######################################
#     Tests for AsyncSQLiteStore     #
######################################


# --- constructor ---


@aiosqlite_available
async def test_init_defaults_to_in_memory() -> None:
    store = AsyncSQLiteStore()
    assert await store.count() == 0
    await store.close()


@aiosqlite_available
async def test_init_accepts_aiosqlite_connect_kwargs() -> None:
    store = AsyncSQLiteStore(":memory:", timeout=5.0)
    assert await store.count() == 0
    await store.close()


# --- from_path ---


@aiosqlite_available
async def test_from_path_creates_file_backed_store(tmp_path: Path) -> None:
    path = tmp_path / "from_path.sqlite"
    store = AsyncSQLiteStore.from_path(path)
    await store.set("1", {"text": "hello"})
    assert await store.count() == 1
    assert path.exists()
    await store.close()


@aiosqlite_available
async def test_from_path_memory_uses_shared_cache_uri() -> None:
    store = AsyncSQLiteStore.from_path(":memory:")
    assert await store.count() == 0
    await store.close()


@aiosqlite_available
async def test_from_path_read_only_can_read_existing_data(
    tmp_path: Path, items: dict[str, dict[str, Any]]
) -> None:
    path = tmp_path / "read_only.sqlite"
    store = AsyncSQLiteStore.from_path(path)
    await store.set_many(items)
    await store.close()

    ro_store = AsyncSQLiteStore.from_path(path, read_only=True)
    assert await ro_store.count() == 4
    await ro_store.close()


@aiosqlite_available
async def test_from_path_read_only_rejects_writes(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "read_only_write.sqlite"
    store = AsyncSQLiteStore.from_path(path)
    await store.set("1", {"text": "hello"})
    await store.close()

    ro_store = AsyncSQLiteStore.from_path(path, read_only=True)
    with pytest.raises(sqlite3.OperationalError, match=r"attempt to write a readonly database"):
        await ro_store.set("99", {"text": "x"})
    await ro_store.close()


@aiosqlite_available
async def test_from_path_forwards_kwargs(tmp_path: Path) -> None:
    path = tmp_path / "from_path_kwargs.sqlite"
    store = AsyncSQLiteStore.from_path(path, timeout=1.0)
    assert await store.count() == 0
    await store.close()


@aiosqlite_available
async def test_init_read_only_connection_without_existing_table_swallows_operational_error(
    tmp_path: Path,
) -> None:
    """When the store table does NOT already exist, CREATE TABLE IF NOT
    EXISTS must attempt an actual write.

    Against a read-only connection this raises sqlite3.OperationalError,
    which schema creation must swallow rather than propagate.
    """
    import sqlite3

    path = tmp_path / "no_table_yet.sqlite"
    raw_conn = sqlite3.connect(path)
    raw_conn.execute("CREATE TABLE unrelated (x INTEGER)")
    raw_conn.commit()
    raw_conn.close()

    store = AsyncSQLiteStore.from_path(path, read_only=True)
    with pytest.raises(sqlite3.OperationalError, match=r"no such table"):
        await store.count()
    await store.close()


# --- repr/str ---


@aiosqlite_available
async def test_repr(store: AsyncSQLiteStore) -> None:
    assert repr(store).startswith("AsyncSQLiteStore(")


@aiosqlite_available
async def test_str(store: AsyncSQLiteStore) -> None:
    assert str(store).startswith("AsyncSQLiteStore(")


@aiosqlite_available
async def test_repr_after_close_does_not_raise(store: AsyncSQLiteStore) -> None:
    await store.close()
    assert repr(store).startswith("AsyncSQLiteStore(")


# --- set ---


@aiosqlite_available
async def test_set_increases_count(store: AsyncSQLiteStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.count() == 1


@aiosqlite_available
async def test_set_stores_value(store: AsyncSQLiteStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.get("1") == {"text": "hello"}


@aiosqlite_available
async def test_set_default_overwrites_existing(store: AsyncSQLiteStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"})
    assert await store.count() == 1
    assert await store.get("1") == {"text": "updated"}


@aiosqlite_available
async def test_set_on_conflict_raise(store: AsyncSQLiteStore) -> None:
    await store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        await store.set("1", {"text": "updated"}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}


@aiosqlite_available
async def test_set_on_conflict_skip(store: AsyncSQLiteStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}


@aiosqlite_available
async def test_set_on_conflict_overwrite(store: AsyncSQLiteStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert await store.get("1") == {"text": "updated"}


@aiosqlite_available
async def test_set_on_conflict_merge(store: AsyncSQLiteStore) -> None:
    await store.set("1", {"text": "original", "author": "Alice"})
    await store.set("1", {"text": "updated"}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


@aiosqlite_available
async def test_set_on_conflict_new_key_is_unaffected(store: AsyncSQLiteStore) -> None:
    await store.set("1", {"text": "hello"}, on_conflict="raise")
    assert await store.get("1") == {"text": "hello"}


@aiosqlite_available
async def test_set_on_conflict_invalid_raises(store: AsyncSQLiteStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.set("1", {"text": "hello"}, on_conflict="bogus")  # type: ignore[arg-type]


# --- set_many ---


@aiosqlite_available
async def test_set_many_increases_count(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


@aiosqlite_available
async def test_set_many_empty_is_no_op(store: AsyncSQLiteStore) -> None:
    await store.set_many({})
    assert await store.count() == 0


@aiosqlite_available
async def test_set_many_default_overwrites_existing(store: AsyncSQLiteStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}})
    assert await store.count() == 1
    assert await store.get("1") == {"text": "updated"}


@aiosqlite_available
async def test_set_many_on_conflict_raise(store: AsyncSQLiteStore) -> None:
    await store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        await store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("3") is None


@aiosqlite_available
async def test_set_many_on_conflict_skip(store: AsyncSQLiteStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("2") == {"text": "new"}


@aiosqlite_available
async def test_set_many_on_conflict_overwrite(store: AsyncSQLiteStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert await store.get("1") == {"text": "updated"}
    assert await store.get("2") == {"text": "new"}


@aiosqlite_available
async def test_set_many_on_conflict_merge(store: AsyncSQLiteStore) -> None:
    await store.set_many({"1": {"text": "original", "author": "Alice"}})
    await store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


@aiosqlite_available
async def test_set_many_on_conflict_invalid_raises(store: AsyncSQLiteStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.set_many({"1": {"text": "hello"}}, on_conflict="bogus")  # type: ignore[arg-type]


# --- set_batches ---


@aiosqlite_available
async def test_set_batches_empty_is_no_op(store: AsyncSQLiteStore) -> None:
    await store.set_batches([])
    assert await store.count() == 0


@aiosqlite_available
async def test_set_batches_writes_all_pairs(store: AsyncSQLiteStore) -> None:
    await store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert await store.count() == 3
    assert await store.get("2") == {"v": 2}


@aiosqlite_available
async def test_set_batches_on_conflict_skip(store: AsyncSQLiteStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set_batches(
        [("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip"
    )
    assert await store.get("1") == {"text": "original"}
    assert await store.get("2") == {"text": "new"}


# --- count ---


@aiosqlite_available
async def test_count_empty_store(store: AsyncSQLiteStore) -> None:
    assert await store.count() == 0


@aiosqlite_available
async def test_count_after_set_many(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


# --- get ---


@aiosqlite_available
async def test_get_existing_value(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.get("1") == items["1"]


@aiosqlite_available
async def test_get_missing_key_returns_none(store: AsyncSQLiteStore) -> None:
    assert await store.get("nonexistent") is None


# --- get_many ---


@aiosqlite_available
async def test_get_many_returns_correct_length(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.get_many(["1", "2", "99"])) == 3


@aiosqlite_available
async def test_get_many_returns_none_for_missing(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["1", "99", "2"])
    assert result[1] is None


@aiosqlite_available
async def test_get_many_preserves_order(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


@aiosqlite_available
async def test_get_many_empty_list_returns_empty_list(store: AsyncSQLiteStore) -> None:
    assert await store.get_many([]) == []


# --- filter ---


@aiosqlite_available
async def test_filter_no_args_returns_all(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.filter()) == len(items)


@aiosqlite_available
async def test_filter_single_field(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


@aiosqlite_available
async def test_filter_multiple_fields(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice", category="Programming")
    assert len(result) == 2


@aiosqlite_available
async def test_filter_no_match_returns_empty(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.filter(author="Charlie") == []


@aiosqlite_available
async def test_filter_rejects_malicious_field_name(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    """A field name is interpolated into the SQL (only the value is
    bound), so anything but a plain identifier must be rejected to
    prevent SQL injection."""
    await store.set_many(items)
    with pytest.raises(ValueError, match="Invalid filter field name"):
        await store.filter(**{"x') OR 1=1 OR ('": "nonmatching"})


@aiosqlite_available
async def test_filter_preserves_full_value(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Bob", category="History")
    expected = [v for v in items.values() if v["author"] == "Bob"]
    assert sorted(result, key=lambda v: v["title"]) == sorted(expected, key=lambda v: v["title"])


@aiosqlite_available
async def test_filter_empty_store_returns_empty(store: AsyncSQLiteStore) -> None:
    assert await store.filter(author="Alice") == []


@aiosqlite_available
async def test_filter_integer_field_value(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


@aiosqlite_available
async def test_filter_integer_value_no_match_returns_empty(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.filter(year=9999) == []


# --- delete ---


@aiosqlite_available
async def test_delete_removes_value(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete("1")
    assert await store.count() == len(items) - 1
    assert await store.get("1") is None


@aiosqlite_available
async def test_delete_nonexistent_is_silent(store: AsyncSQLiteStore) -> None:
    await store.delete("nonexistent")


# --- delete_many ---


@aiosqlite_available
async def test_delete_many_removes_values(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["1", "3"])
    assert await store.count() == len(items) - 2
    assert await store.get("1") is None
    assert await store.get("3") is None


@aiosqlite_available
async def test_delete_many_preserves_other_values(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["1", "3"])
    assert await store.get("2") is not None
    assert await store.get("4") is not None


@aiosqlite_available
async def test_delete_many_empty_list_is_no_op(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many([])
    assert await store.count() == len(items)


@aiosqlite_available
async def test_delete_many_nonexistent_keys_are_silent(store: AsyncSQLiteStore) -> None:
    await store.delete_many(["99", "100"])


@aiosqlite_available
async def test_delete_many_single_key(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["2"])
    assert await store.count() == len(items) - 1
    assert await store.get("2") is None


# --- contains_many ---


@aiosqlite_available
async def test_contains_many_all_found(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["1", "2", "3", "4"])
    assert found == ["1", "2", "3", "4"]
    assert missing == []


@aiosqlite_available
async def test_contains_many_all_missing(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["99", "100"])
    assert found == []
    assert missing == ["99", "100"]


@aiosqlite_available
async def test_contains_many_mixed(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["1", "99", "3", "42"])
    assert found == ["1", "3"]
    assert missing == ["99", "42"]


@aiosqlite_available
async def test_contains_many_empty_input_returns_empty_lists(store: AsyncSQLiteStore) -> None:
    found, missing = await store.contains_many([])
    assert found == []
    assert missing == []


@aiosqlite_available
async def test_contains_many_empty_store_returns_all_missing(store: AsyncSQLiteStore) -> None:
    found, missing = await store.contains_many(["1", "2"])
    assert found == []
    assert missing == ["1", "2"]


@aiosqlite_available
async def test_contains_many_returns_tuple_of_two_lists(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.contains_many(["1", "99"])
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


# --- columns_info ---


@aiosqlite_available
async def test_get_columns_info_returns_dict(store: AsyncSQLiteStore) -> None:
    result = await store.get_columns_info()
    assert isinstance(result, dict)


@aiosqlite_available
async def test_get_columns_info_values_are_strings(store: AsyncSQLiteStore) -> None:
    result = await store.get_columns_info()
    assert all(isinstance(v, str) for v in result.values())


@aiosqlite_available
async def test_get_columns_info_non_empty_for_created_table(store: AsyncSQLiteStore) -> None:
    result = await store.get_columns_info()
    assert len(result) > 0


@aiosqlite_available
async def test_show_columns_info_does_not_raise(
    store: AsyncSQLiteStore, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO"):
        await store.show_columns_info()
    assert caplog.text != ""


@aiosqlite_available
async def test_show_columns_info_output_contains_column_names(
    store: AsyncSQLiteStore, caplog: pytest.LogCaptureFixture
) -> None:
    expected_columns = (await store.get_columns_info()).keys()
    with caplog.at_level("INFO"):
        await store.show_columns_info()
    for col in expected_columns:
        assert col in caplog.text


@aiosqlite_available
async def test_show_columns_info_returns_none(store: AsyncSQLiteStore) -> None:
    assert await store.show_columns_info() is None


# --- keys ---


@aiosqlite_available
async def test_keys_empty_store_yields_nothing(store: AsyncSQLiteStore) -> None:
    assert [key async for key in store.keys()] == []  # noqa: SIM118


@aiosqlite_available
async def test_keys_returns_all_keys(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [key async for key in store.keys()]  # noqa: SIM118
    assert sorted(result) == sorted(items.keys())


# --- values ---


@aiosqlite_available
async def test_values_empty_store_yields_nothing(store: AsyncSQLiteStore) -> None:
    assert [value async for value in store.values()] == []


@aiosqlite_available
async def test_values_returns_all_values(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [value async for value in store.values()]
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


# --- iter_batches ---


@aiosqlite_available
async def test_iter_batches_empty_store_yields_nothing(store: AsyncSQLiteStore) -> None:
    assert [batch async for batch in store.iter_batches()] == []


@aiosqlite_available
async def test_iter_batches_default_batch_size(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches()]
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


@aiosqlite_available
async def test_iter_batches_yields_correct_batch_sizes(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=2)]
    assert [len(b) for b in batches] == [2, 2]


@aiosqlite_available
async def test_iter_batches_last_batch_may_be_smaller(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=3)]
    assert [len(b) for b in batches] == [3, 1]


@aiosqlite_available
async def test_iter_batches_batch_size_one(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=1)]
    assert [len(b) for b in batches] == [1, 1, 1, 1]


@aiosqlite_available
async def test_iter_batches_returns_all_key_value_pairs(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    async for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


@aiosqlite_available
async def test_iter_batches_zero_batch_size_raises(store: AsyncSQLiteStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.iter_batches(batch_size=0):
            pass


@aiosqlite_available
async def test_iter_batches_negative_batch_size_raises(store: AsyncSQLiteStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.iter_batches(batch_size=-1):
            pass


@aiosqlite_available
async def test_iter_batches_does_not_mutate_store(
    store: AsyncSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    async for _ in store.iter_batches(batch_size=2):
        pass
    assert await store.count() == len(items)


# --- close ---


@aiosqlite_available
async def test_close_closes_underlying_connection(store: AsyncSQLiteStore) -> None:
    await store.set("1", {"a": 1})
    await store.close()
    with pytest.raises(ValueError, match=r"no active connection"):
        await store._conn.execute("SELECT 1")


@aiosqlite_available
async def test_close_is_idempotent(store: AsyncSQLiteStore) -> None:
    await store.close()
    await store.close()  # should not raise


@aiosqlite_available
async def test_close_returns_none(store: AsyncSQLiteStore) -> None:
    assert await store.close() is None


# --- closed ---


@aiosqlite_available
async def test_closed_false_before_close(store: AsyncSQLiteStore) -> None:
    assert not store.closed


@aiosqlite_available
async def test_closed_true_after_close(store: AsyncSQLiteStore) -> None:
    await store.close()
    assert store.closed


# --- context manager ---


@aiosqlite_available
async def test_context_manager_returns_self() -> None:
    async with AsyncSQLiteStore(":memory:") as store:
        assert isinstance(store, AsyncSQLiteStore)


@aiosqlite_available
async def test_context_manager_closes_on_normal_exit() -> None:
    async with AsyncSQLiteStore(":memory:") as store:
        await store.set("1", {"text": "hello"})
        assert await store.count() == 1

    with pytest.raises(ValueError, match=r"no active connection"):
        await store._conn.execute("SELECT 1")


@aiosqlite_available
async def test_context_manager_closes_on_exception() -> None:
    msg = "boom"
    store = AsyncSQLiteStore(":memory:")
    with pytest.raises(ValueError, match="boom"):
        async with store:
            raise ValueError(msg)

    with pytest.raises(ValueError, match=r"no active connection"):
        await store._conn.execute("SELECT 1")


@aiosqlite_available
async def test_context_manager_usable_for_reads_and_writes() -> None:
    async with AsyncSQLiteStore(":memory:") as store:
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


@aiosqlite_available
async def test_context_manager_multiple_open_close_in_memory() -> None:
    sqlite_store = AsyncSQLiteStore(":memory:")
    for i in range(3):
        async with sqlite_store as store:
            assert await store.count() == 0
            await store.set(str(i), {"text": "hello"})
            assert await store.count() == 1


@aiosqlite_available
async def test_context_manager_multiple_open_close_persistent(tmp_path: Path) -> None:
    sqlite_store = AsyncSQLiteStore(tmp_path / "data.db")
    for i in range(3):
        async with sqlite_store as store:
            await store.set(str(i), {"text": "hello"})
            assert await store.count() == i + 1
