from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from persista.store import AsyncBaseSQLiteStore, AsyncSQLiteStore, AsyncTypedSQLiteStore
from persista.testing.fixtures import aiosqlite_available

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

aiosqlite = pytest.importorskip("aiosqlite")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def store_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("store")


@pytest.fixture(params=[AsyncSQLiteStore, AsyncTypedSQLiteStore], ids=["plain", "typed"])
def store_cls(request: pytest.FixtureRequest) -> type[AsyncBaseSQLiteStore]:
    return request.param


@pytest.fixture
async def store(store_cls: type[AsyncBaseSQLiteStore]) -> AsyncGenerator[AsyncBaseSQLiteStore]:
    async with store_cls(":memory:") as store:
        yield store


@pytest.fixture
async def typed_store_no_schema() -> AsyncGenerator[AsyncTypedSQLiteStore]:
    """In-memory AsyncTypedSQLiteStore with no schema (everything in
    `extra`)."""
    async with AsyncTypedSQLiteStore(":memory:") as store:
        yield store


@pytest.fixture
async def typed_store() -> AsyncGenerator[AsyncTypedSQLiteStore]:
    """In-memory store with a typed schema."""
    async with AsyncTypedSQLiteStore(
        ":memory:",
        value_schema={"author": "TEXT", "year": "INTEGER", "category": "TEXT"},
    ) as store:
        yield store


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


###############################################################
#     Tests for AsyncSQLiteStore/AsyncTypedSQLiteStore        #
###############################################################


# --- constructor ---


@aiosqlite_available
async def test_init_defaults_to_in_memory(store_cls: type[AsyncBaseSQLiteStore]) -> None:
    store = store_cls()
    assert await store.count() == 0
    await store.close()


@aiosqlite_available
async def test_init_accepts_aiosqlite_connect_kwargs(
    store_cls: type[AsyncBaseSQLiteStore],
) -> None:
    store = store_cls(":memory:", timeout=5.0)
    assert await store.count() == 0
    await store.close()


# --- from_path ---


@aiosqlite_available
async def test_from_path_creates_file_backed_store(
    store_path: Path, store_cls: type[AsyncBaseSQLiteStore]
) -> None:
    path = store_path / f"from_path_{store_cls.__name__}.sqlite"
    store = store_cls.from_path(path)
    await store.set("1", {"text": "hello"})
    assert await store.count() == 1
    assert path.exists()
    await store.close()


@aiosqlite_available
async def test_from_path_memory_uses_shared_cache_uri(
    store_cls: type[AsyncBaseSQLiteStore],
) -> None:
    store = store_cls.from_path(":memory:")
    assert await store.count() == 0
    await store.close()


@aiosqlite_available
async def test_from_path_read_only_can_read_existing_data(
    store_path: Path, store_cls: type[AsyncBaseSQLiteStore], items: dict[str, dict[str, Any]]
) -> None:
    path = store_path / f"read_only_{store_cls.__name__}.sqlite"
    store = store_cls.from_path(path)
    await store.set_many(items)
    await store.close()

    ro_store = store_cls.from_path(path, read_only=True)
    assert await ro_store.count() == 4
    await ro_store.close()


@aiosqlite_available
async def test_from_path_read_only_rejects_writes(
    store_path: Path, store_cls: type[AsyncBaseSQLiteStore]
) -> None:
    import sqlite3

    path = store_path / f"read_only_write_{store_cls.__name__}.sqlite"
    store = store_cls.from_path(path)
    await store.set("1", {"text": "hello"})
    await store.close()

    ro_store = store_cls.from_path(path, read_only=True)
    with pytest.raises(sqlite3.OperationalError, match=r"attempt to write a readonly database"):
        await ro_store.set("99", {"text": "x"})
    await ro_store.close()


@aiosqlite_available
async def test_from_path_forwards_kwargs(
    store_path: Path, store_cls: type[AsyncBaseSQLiteStore]
) -> None:
    path = store_path / f"from_path_kwargs_{store_cls.__name__}.sqlite"
    store = store_cls.from_path(path, timeout=1.0)
    assert await store.count() == 0
    await store.close()


@aiosqlite_available
async def test_init_read_only_connection_without_existing_table_swallows_operational_error(
    store_path: Path, store_cls: type[AsyncBaseSQLiteStore]
) -> None:
    """When the store table does NOT already exist, CREATE TABLE IF NOT
    EXISTS must attempt an actual write.

    Against a read-only connection this raises sqlite3.OperationalError,
    which schema creation must swallow rather than propagate.
    """
    import sqlite3

    path = store_path / f"no_table_yet_{store_cls.__name__}.sqlite"
    raw_conn = sqlite3.connect(path)
    raw_conn.execute("CREATE TABLE unrelated (x INTEGER)")
    raw_conn.commit()
    raw_conn.close()

    store = store_cls.from_path(path, read_only=True)
    with pytest.raises(sqlite3.OperationalError, match=r"no such table"):
        await store.count()
    await store.close()


# --- repr/str ---


@aiosqlite_available
async def test_repr(store: AsyncBaseSQLiteStore) -> None:
    assert repr(store).startswith(f"{type(store).__name__}(")


@aiosqlite_available
async def test_str(store: AsyncBaseSQLiteStore) -> None:
    assert str(store).startswith(f"{type(store).__name__}(")


@aiosqlite_available
async def test_repr_after_close_does_not_raise(store: AsyncBaseSQLiteStore) -> None:
    await store.close()
    assert repr(store).startswith(f"{type(store).__name__}(")


# --- set ---


@aiosqlite_available
async def test_set_increases_count(store: AsyncBaseSQLiteStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.count() == 1


@aiosqlite_available
async def test_set_stores_value(store: AsyncBaseSQLiteStore) -> None:
    await store.set("1", {"text": "hello"})
    assert await store.get("1") == {"text": "hello"}


@aiosqlite_available
async def test_set_default_overwrites_existing(store: AsyncBaseSQLiteStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"})
    assert await store.count() == 1
    assert await store.get("1") == {"text": "updated"}


@aiosqlite_available
async def test_set_on_conflict_raise(store: AsyncBaseSQLiteStore) -> None:
    await store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        await store.set("1", {"text": "updated"}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}


@aiosqlite_available
async def test_set_on_conflict_skip(store: AsyncBaseSQLiteStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}


@aiosqlite_available
async def test_set_on_conflict_overwrite(store: AsyncBaseSQLiteStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert await store.get("1") == {"text": "updated"}


@aiosqlite_available
async def test_set_on_conflict_merge(store: AsyncBaseSQLiteStore) -> None:
    await store.set("1", {"text": "original", "author": "Alice"})
    await store.set("1", {"text": "updated"}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


@aiosqlite_available
async def test_set_on_conflict_new_key_is_unaffected(store: AsyncBaseSQLiteStore) -> None:
    await store.set("1", {"text": "hello"}, on_conflict="raise")
    assert await store.get("1") == {"text": "hello"}


@aiosqlite_available
async def test_set_on_conflict_invalid_raises(store: AsyncBaseSQLiteStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.set("1", {"text": "hello"}, on_conflict="bogus")  # type: ignore[arg-type]


# --- set_many ---


@aiosqlite_available
async def test_set_many_increases_count(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


@aiosqlite_available
async def test_set_many_empty_is_no_op(store: AsyncBaseSQLiteStore) -> None:
    await store.set_many({})
    assert await store.count() == 0


@aiosqlite_available
async def test_set_many_default_overwrites_existing(store: AsyncBaseSQLiteStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}})
    assert await store.count() == 1
    assert await store.get("1") == {"text": "updated"}


@aiosqlite_available
async def test_set_many_on_conflict_raise(store: AsyncBaseSQLiteStore) -> None:
    await store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        await store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("3") is None


@aiosqlite_available
async def test_set_many_on_conflict_skip(store: AsyncBaseSQLiteStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert await store.get("1") == {"text": "original"}
    assert await store.get("2") == {"text": "new"}


@aiosqlite_available
async def test_set_many_on_conflict_overwrite(store: AsyncBaseSQLiteStore) -> None:
    await store.set_many({"1": {"text": "original"}})
    await store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert await store.get("1") == {"text": "updated"}
    assert await store.get("2") == {"text": "new"}


@aiosqlite_available
async def test_set_many_on_conflict_merge(store: AsyncBaseSQLiteStore) -> None:
    await store.set_many({"1": {"text": "original", "author": "Alice"}})
    await store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert await store.get("1") == {"text": "updated", "author": "Alice"}


@aiosqlite_available
async def test_set_many_on_conflict_invalid_raises(store: AsyncBaseSQLiteStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.set_many({"1": {"text": "hello"}}, on_conflict="bogus")  # type: ignore[arg-type]


# --- set_batches ---


@aiosqlite_available
async def test_set_batches_empty_is_no_op(store: AsyncBaseSQLiteStore) -> None:
    await store.set_batches([])
    assert await store.count() == 0


@aiosqlite_available
async def test_set_batches_writes_all_pairs(store: AsyncBaseSQLiteStore) -> None:
    await store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert await store.count() == 3
    assert await store.get("2") == {"v": 2}


@aiosqlite_available
async def test_set_batches_on_conflict_skip(store: AsyncBaseSQLiteStore) -> None:
    await store.set("1", {"text": "original"})
    await store.set_batches(
        [("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip"
    )
    assert await store.get("1") == {"text": "original"}
    assert await store.get("2") == {"text": "new"}


# --- count ---


@aiosqlite_available
async def test_count_empty_store(store: AsyncBaseSQLiteStore) -> None:
    assert await store.count() == 0


@aiosqlite_available
async def test_count_after_set_many(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.count() == len(items)


# --- get ---


@aiosqlite_available
async def test_get_existing_value(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.get("1") == items["1"]


@aiosqlite_available
async def test_get_missing_key_returns_none(store: AsyncBaseSQLiteStore) -> None:
    assert await store.get("nonexistent") is None


# --- get_many ---


@aiosqlite_available
async def test_get_many_returns_correct_length(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.get_many(["1", "2", "99"])) == 3


@aiosqlite_available
async def test_get_many_returns_none_for_missing(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["1", "99", "2"])
    assert result[1] is None


@aiosqlite_available
async def test_get_many_preserves_order(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


@aiosqlite_available
async def test_get_many_empty_list_returns_empty_list(store: AsyncBaseSQLiteStore) -> None:
    assert await store.get_many([]) == []


# --- filter ---


@aiosqlite_available
async def test_filter_no_args_returns_all(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert len(await store.filter()) == len(items)


@aiosqlite_available
async def test_filter_single_field(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


@aiosqlite_available
async def test_filter_multiple_fields(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Alice", category="Programming")
    assert len(result) == 2


@aiosqlite_available
async def test_filter_no_match_returns_empty(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.filter(author="Charlie") == []


@aiosqlite_available
async def test_filter_rejects_malicious_field_name(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    """A field name is interpolated into the SQL (only the value is
    bound), so anything but a plain identifier must be rejected to
    prevent SQL injection."""
    await store.set_many(items)
    with pytest.raises(ValueError, match="Invalid filter field name"):
        await store.filter(**{"x') OR 1=1 OR ('": "nonmatching"})


@aiosqlite_available
async def test_filter_preserves_full_value(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(author="Bob", category="History")
    expected = [v for v in items.values() if v["author"] == "Bob"]
    assert sorted(result, key=lambda v: v["title"]) == sorted(expected, key=lambda v: v["title"])


@aiosqlite_available
async def test_filter_empty_store_returns_empty(store: AsyncBaseSQLiteStore) -> None:
    assert await store.filter(author="Alice") == []


@aiosqlite_available
async def test_filter_integer_field_value(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


@aiosqlite_available
async def test_filter_integer_value_no_match_returns_empty(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    assert await store.filter(year=9999) == []


# --- delete ---


@aiosqlite_available
async def test_delete_removes_value(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete("1")
    assert await store.count() == len(items) - 1
    assert await store.get("1") is None


@aiosqlite_available
async def test_delete_nonexistent_is_silent(store: AsyncBaseSQLiteStore) -> None:
    await store.delete("nonexistent")


# --- delete_many ---


@aiosqlite_available
async def test_delete_many_removes_values(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["1", "3"])
    assert await store.count() == len(items) - 2
    assert await store.get("1") is None
    assert await store.get("3") is None


@aiosqlite_available
async def test_delete_many_preserves_other_values(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["1", "3"])
    assert await store.get("2") is not None
    assert await store.get("4") is not None


@aiosqlite_available
async def test_delete_many_empty_list_is_no_op(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many([])
    assert await store.count() == len(items)


@aiosqlite_available
async def test_delete_many_nonexistent_keys_are_silent(store: AsyncBaseSQLiteStore) -> None:
    await store.delete_many(["99", "100"])


@aiosqlite_available
async def test_delete_many_single_key(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    await store.delete_many(["2"])
    assert await store.count() == len(items) - 1
    assert await store.get("2") is None


# --- contains_many ---


@aiosqlite_available
async def test_contains_many_all_found(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["1", "2", "3", "4"])
    assert found == ["1", "2", "3", "4"]
    assert missing == []


@aiosqlite_available
async def test_contains_many_all_missing(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["99", "100"])
    assert found == []
    assert missing == ["99", "100"]


@aiosqlite_available
async def test_contains_many_mixed(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    found, missing = await store.contains_many(["1", "99", "3", "42"])
    assert found == ["1", "3"]
    assert missing == ["99", "42"]


@aiosqlite_available
async def test_contains_many_empty_input_returns_empty_lists(store: AsyncBaseSQLiteStore) -> None:
    found, missing = await store.contains_many([])
    assert found == []
    assert missing == []


@aiosqlite_available
async def test_contains_many_empty_store_returns_all_missing(
    store: AsyncBaseSQLiteStore,
) -> None:
    found, missing = await store.contains_many(["1", "2"])
    assert found == []
    assert missing == ["1", "2"]


@aiosqlite_available
async def test_contains_many_returns_tuple_of_two_lists(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = await store.contains_many(["1", "99"])
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


# --- columns_info ---


@aiosqlite_available
async def test_get_columns_info_returns_dict(store: AsyncBaseSQLiteStore) -> None:
    result = await store.get_columns_info()
    assert isinstance(result, dict)


@aiosqlite_available
async def test_get_columns_info_values_are_strings(store: AsyncBaseSQLiteStore) -> None:
    result = await store.get_columns_info()
    assert all(isinstance(v, str) for v in result.values())


@aiosqlite_available
async def test_get_columns_info_non_empty_for_created_table(store: AsyncBaseSQLiteStore) -> None:
    result = await store.get_columns_info()
    assert len(result) > 0


@aiosqlite_available
async def test_show_columns_info_does_not_raise(
    store: AsyncBaseSQLiteStore, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO"):
        await store.show_columns_info()
    assert caplog.text != ""


@aiosqlite_available
async def test_show_columns_info_output_contains_column_names(
    store: AsyncBaseSQLiteStore, caplog: pytest.LogCaptureFixture
) -> None:
    expected_columns = (await store.get_columns_info()).keys()
    with caplog.at_level("INFO"):
        await store.show_columns_info()
    for col in expected_columns:
        assert col in caplog.text


@aiosqlite_available
async def test_show_columns_info_returns_none(store: AsyncBaseSQLiteStore) -> None:
    assert await store.show_columns_info() is None


# --- keys ---


@aiosqlite_available
async def test_keys_empty_store_yields_nothing(store: AsyncBaseSQLiteStore) -> None:
    assert [key async for key in store.keys()] == []  # noqa: SIM118


@aiosqlite_available
async def test_keys_returns_all_keys(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [key async for key in store.keys()]  # noqa: SIM118
    assert sorted(result) == sorted(items.keys())


# --- values ---


@aiosqlite_available
async def test_values_empty_store_yields_nothing(store: AsyncBaseSQLiteStore) -> None:
    assert [value async for value in store.values()] == []


@aiosqlite_available
async def test_values_returns_all_values(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result = [value async for value in store.values()]
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


# --- iter_batches ---


@aiosqlite_available
async def test_iter_batches_empty_store_yields_nothing(store: AsyncBaseSQLiteStore) -> None:
    assert [batch async for batch in store.iter_batches()] == []


@aiosqlite_available
async def test_iter_batches_default_batch_size(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches()]
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


@aiosqlite_available
async def test_iter_batches_yields_correct_batch_sizes(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=2)]
    assert [len(b) for b in batches] == [2, 2]


@aiosqlite_available
async def test_iter_batches_last_batch_may_be_smaller(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=3)]
    assert [len(b) for b in batches] == [3, 1]


@aiosqlite_available
async def test_iter_batches_batch_size_one(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    batches = [batch async for batch in store.iter_batches(batch_size=1)]
    assert [len(b) for b in batches] == [1, 1, 1, 1]


@aiosqlite_available
async def test_iter_batches_returns_all_key_value_pairs(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    async for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


@aiosqlite_available
async def test_iter_batches_zero_batch_size_raises(store: AsyncBaseSQLiteStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.iter_batches(batch_size=0):
            pass


@aiosqlite_available
async def test_iter_batches_negative_batch_size_raises(store: AsyncBaseSQLiteStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        async for _ in store.iter_batches(batch_size=-1):
            pass


@aiosqlite_available
async def test_iter_batches_does_not_mutate_store(
    store: AsyncBaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.set_many(items)
    async for _ in store.iter_batches(batch_size=2):
        pass
    assert await store.count() == len(items)


# --- close ---


@aiosqlite_available
async def test_close_closes_underlying_connection(store: AsyncBaseSQLiteStore) -> None:
    await store.set("1", {"a": 1})
    await store.close()
    with pytest.raises(ValueError, match=r"no active connection"):
        await store._conn.execute("SELECT 1")


@aiosqlite_available
async def test_close_is_idempotent(store: AsyncBaseSQLiteStore) -> None:
    await store.close()
    await store.close()  # should not raise


@aiosqlite_available
async def test_close_returns_none(store: AsyncBaseSQLiteStore) -> None:
    assert await store.close() is None


# --- closed ---


@aiosqlite_available
async def test_closed_false_before_close(store: AsyncBaseSQLiteStore) -> None:
    assert not store.closed


@aiosqlite_available
async def test_closed_true_after_close(store: AsyncBaseSQLiteStore) -> None:
    await store.close()
    assert store.closed


# --- context manager ---


@aiosqlite_available
async def test_context_manager_returns_self(
    store: AsyncBaseSQLiteStore, store_cls: type[AsyncBaseSQLiteStore]
) -> None:
    assert isinstance(store, store_cls)


@aiosqlite_available
async def test_context_manager_closes_on_normal_exit(
    store_cls: type[AsyncBaseSQLiteStore],
) -> None:
    async with store_cls(":memory:") as store:
        await store.set("1", {"text": "hello"})
        assert await store.count() == 1

    with pytest.raises(ValueError, match=r"no active connection"):
        await store._conn.execute("SELECT 1")


@aiosqlite_available
async def test_context_manager_closes_on_exception(store_cls: type[AsyncBaseSQLiteStore]) -> None:
    msg = "boom"
    store = store_cls(":memory:")
    with pytest.raises(ValueError, match="boom"):
        async with store:
            raise ValueError(msg)

    with pytest.raises(ValueError, match=r"no active connection"):
        await store._conn.execute("SELECT 1")


@aiosqlite_available
async def test_context_manager_usable_for_reads_and_writes(
    store_cls: type[AsyncBaseSQLiteStore],
) -> None:
    async with store_cls(":memory:") as store:
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
async def test_context_manager_multiple_open_close_in_memory(
    store_cls: type[AsyncBaseSQLiteStore],
) -> None:
    sqlite_store = store_cls(":memory:")
    for i in range(3):
        async with sqlite_store as store:
            assert await store.count() == 0
            await store.set(str(i), {"text": "hello"})
            assert await store.count() == 1


@aiosqlite_available
async def test_context_manager_multiple_open_close_persistent(
    tmp_path: Path, store_cls: type[AsyncBaseSQLiteStore]
) -> None:
    sqlite_store = store_cls(tmp_path / "data.db")
    for i in range(3):
        async with sqlite_store as store:
            await store.set(str(i), {"text": "hello"})
            assert await store.count() == i + 1


###################################################################
#     AsyncTypedSQLiteStore-specific schema behavior             #
###################################################################

# AsyncSQLiteStore and AsyncTypedSQLiteStore share the exact same behavior
# when no schema is involved (covered by every test above, run against both
# `store_cls` params). AsyncTypedSQLiteStore additionally supports declaring typed
# columns via `value_schema`, covered here.


@aiosqlite_available
async def test_init_no_schema_stores_everything_in_extra(
    typed_store_no_schema: AsyncTypedSQLiteStore,
) -> None:
    await typed_store_no_schema.set("1", {"author": "Alice"})
    assert set((await typed_store_no_schema.get_columns_info()).keys()) == {"_KEY_", "extra"}


@aiosqlite_available
async def test_init_with_schema_creates_typed_columns(
    typed_store: AsyncTypedSQLiteStore,
) -> None:
    columns = await typed_store.get_columns_info()
    assert set(columns.keys()) == {"_KEY_", "author", "year", "category", "extra"}


@aiosqlite_available
async def test_init_schema_with_reserved_key_column_raises() -> None:
    with pytest.raises(ValueError, match="reserved key column name"):
        AsyncTypedSQLiteStore(":memory:", value_schema={"_KEY_": "TEXT"})


@aiosqlite_available
async def test_value_field_named_key_does_not_collide_with_primary_key(
    typed_store_no_schema: AsyncTypedSQLiteStore,
) -> None:
    """A value field literally named 'key' must not collide with the
    store's primary key column, and should be stored/retrieved via the
    extra JSON overflow column."""
    await typed_store_no_schema.set("1", {"key": "not-the-primary-key"})
    assert await typed_store_no_schema.get("1") == {"key": "not-the-primary-key"}
    assert await typed_store_no_schema.filter(key="not-the-primary-key") == [
        {"key": "not-the-primary-key"}
    ]


@aiosqlite_available
async def test_from_path_with_schema(store_path: Path) -> None:
    path = store_path / "with_schema.sqlite"
    schema = {"author": "TEXT", "year": "INTEGER"}
    store = AsyncTypedSQLiteStore.from_path(path, value_schema=schema)
    await store.set("1", {"author": "Alice", "year": 2022})
    value = await store.get("1")
    assert value["year"] == 2022
    await store.close()


@aiosqlite_available
async def test_init_read_only_connection_with_existing_table_does_not_raise(
    store_path: Path, items: dict[str, dict[str, Any]]
) -> None:
    path = store_path / "typed_read_only.sqlite"
    store = AsyncTypedSQLiteStore.from_path(path)
    await store.set_many(items)
    await store.close()

    ro_store = AsyncTypedSQLiteStore.from_path(path, read_only=True)
    assert await ro_store.count() == len(items)
    await ro_store.close()


@aiosqlite_available
async def test_set_on_conflict_merge_with_typed_schema(typed_store: AsyncTypedSQLiteStore) -> None:
    await typed_store.set("1", {"author": "Alice", "year": 2022})
    await typed_store.set("1", {"category": "Programming"}, on_conflict="merge")
    value = await typed_store.get("1")
    assert value == {"author": "Alice", "year": 2022, "category": "Programming"}


@aiosqlite_available
async def test_get_round_trips_typed_schema_fields(
    typed_store: AsyncTypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.set_many(items)
    assert await typed_store.get("1") == items["1"]


@aiosqlite_available
async def test_get_round_trips_extra_field(typed_store: AsyncTypedSQLiteStore) -> None:
    await typed_store.set("1", {"author": "Alice", "publisher": "O'Reilly"})
    value = await typed_store.get("1")
    assert value["publisher"] == "O'Reilly"


@aiosqlite_available
async def test_filter_single_typed_field(
    typed_store: AsyncTypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.set_many(items)
    result = await typed_store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


@aiosqlite_available
async def test_filter_multiple_typed_fields(
    typed_store: AsyncTypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.set_many(items)
    result = await typed_store.filter(author="Alice", category="Programming")
    assert len(result) == 2


@aiosqlite_available
async def test_filter_extra_field(typed_store: AsyncTypedSQLiteStore) -> None:
    await typed_store.set_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Bob", "publisher": "Manning"},
        }
    )
    result = await typed_store.filter(publisher="O'Reilly")
    assert len(result) == 1
    assert result[0]["author"] == "Alice"


@aiosqlite_available
async def test_filter_mixed_schema_and_extra_fields(typed_store: AsyncTypedSQLiteStore) -> None:
    await typed_store.set_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Alice", "publisher": "Manning"},
        }
    )
    result = await typed_store.filter(author="Alice", publisher="O'Reilly")
    assert len(result) == 1
    assert result[0]["publisher"] == "O'Reilly"


@aiosqlite_available
async def test_filter_integer_typed_column(
    typed_store: AsyncTypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.set_many(items)
    result = await typed_store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


@aiosqlite_available
async def test_filter_integer_typed_column_no_match(
    typed_store: AsyncTypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.set_many(items)
    assert await typed_store.filter(year=9999) == []


@aiosqlite_available
async def test_get_columns_info_typed_store_has_schema_columns(
    typed_store: AsyncTypedSQLiteStore,
) -> None:
    columns = await typed_store.get_columns_info()
    assert "author" in columns
    assert "year" in columns
    assert "category" in columns


@aiosqlite_available
async def test_get_columns_info_has_extra_column(typed_store: AsyncTypedSQLiteStore) -> None:
    assert "extra" in await typed_store.get_columns_info()


@aiosqlite_available
async def test_iter_batches_with_typed_schema(
    typed_store: AsyncTypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    async for batch in typed_store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items
