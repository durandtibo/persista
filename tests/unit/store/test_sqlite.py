from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import BaseSQLiteStore, SQLiteStore, TypedSQLiteStore
from persista.store import sqlite as sqlite_module
from persista.testing.fixtures import aiosqlite_available

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def store_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("store")


@pytest.fixture(scope="module", params=[SQLiteStore, TypedSQLiteStore], ids=["plain", "typed"])
def store_cls(request: pytest.FixtureRequest) -> type[BaseSQLiteStore]:
    return request.param


@pytest.fixture
def store(store_cls: type[BaseSQLiteStore]) -> Generator[BaseSQLiteStore, None, None]:
    with store_cls(":memory:") as store:
        yield store


@pytest.fixture
def typed_store_no_schema() -> Generator[TypedSQLiteStore, None, None]:
    """In-memory TypedSQLiteStore with no schema (everything in
    `extra`)."""
    with TypedSQLiteStore(":memory:") as store:
        yield store


@pytest.fixture
def typed_store() -> Generator[TypedSQLiteStore, None, None]:
    """In-memory store with a typed schema."""
    with TypedSQLiteStore(
        ":memory:",
        value_schema={"author": "TEXT", "year": "INTEGER", "category": "TEXT"},
    ) as store:
        yield store


@pytest.fixture(scope="module")
def store_read_only(
    store_path: Path, store_cls: type[BaseSQLiteStore], items: dict[str, dict[str, Any]]
) -> Generator[BaseSQLiteStore, None, None]:
    path = store_path / f"data_{store_cls.__name__}.sqlite"
    with store_cls.from_path(path) as store:
        store.set_many(items)
    with store_cls.from_path(path, read_only=True) as store:
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


#############################################
#     Tests for SQLiteStore/TypedSQLiteStore #
#############################################


# --- constructor ---


def test_init_defaults_to_in_memory(store_cls: type[BaseSQLiteStore]) -> None:
    with store_cls() as store:
        assert store.count() == 0


def test_init_accepts_sqlite_connect_kwargs(store_cls: type[BaseSQLiteStore]) -> None:
    with store_cls(":memory:", timeout=5.0) as store:
        assert store.count() == 0


def test_init_creates_table(store_cls: type[BaseSQLiteStore]) -> None:
    with store_cls(":memory:") as store:
        assert store.count() == 0


# --- from_path ---


def test_from_path_creates_file_backed_store(
    store_path: Path, store_cls: type[BaseSQLiteStore]
) -> None:
    path = store_path / f"from_path_{store_cls.__name__}.sqlite"
    with store_cls.from_path(path) as store:
        store.set("1", {"text": "hello"})
        assert store.count() == 1
        assert path.exists()


def test_from_path_creates_missing_parent_directories(
    store_path: Path, store_cls: type[BaseSQLiteStore]
) -> None:
    path = store_path / "nested" / store_cls.__name__ / "dirs" / "from_path.sqlite"
    assert not path.parent.exists()

    with store_cls.from_path(path) as store:
        store.set("1", {"text": "hello"})
        assert store.count() == 1
        assert path.exists()


def test_from_path_memory_uses_shared_cache_uri(store_cls: type[BaseSQLiteStore]) -> None:
    with store_cls.from_path(":memory:") as store:
        assert store.count() == 0


def test_from_path_read_only_can_read_existing_data(store_read_only: BaseSQLiteStore) -> None:
    assert store_read_only.count() == 4


def test_from_path_read_only_rejects_writes(store_read_only: BaseSQLiteStore) -> None:
    with pytest.raises(sqlite3.OperationalError, match=r"attempt to write a readonly database"):
        store_read_only.set("99", {"text": "x"})


def test_from_path_forwards_kwargs(store_path: Path, store_cls: type[BaseSQLiteStore]) -> None:
    path = store_path / f"from_path_kwargs_{store_cls.__name__}.sqlite"
    with store_cls.from_path(path, timeout=1.0) as store:
        assert store.count() == 0


def test_init_read_only_connection_without_existing_table_swallows_operational_error(
    store_path: Path, store_cls: type[BaseSQLiteStore]
) -> None:
    """When the store table does NOT already exist, CREATE TABLE IF NOT
    EXISTS must attempt an actual write.

    Against a read-only connection this raises sqlite3.OperationalError,
    which __init__ must swallow rather than propagate.
    """
    path = store_path / f"no_table_yet_{store_cls.__name__}.sqlite"
    raw_conn = sqlite3.connect(path)
    raw_conn.execute("CREATE TABLE unrelated (x INTEGER)")
    raw_conn.commit()
    raw_conn.close()

    with (
        store_cls.from_path(path, read_only=True) as store,
        pytest.raises(sqlite3.OperationalError, match=r"no such table"),
    ):
        store.count()
    store.close()


# --- repr/str ---


def test_repr(store: BaseSQLiteStore) -> None:
    assert repr(store).startswith(f"{type(store).__name__}(")


def test_str(store: BaseSQLiteStore) -> None:
    assert str(store).startswith(f"{type(store).__name__}(")


def test_repr_after_close_does_not_raise(store: BaseSQLiteStore) -> None:
    store.close()
    assert repr(store).startswith(f"{type(store).__name__}(")


# --- set ---


def test_set_increases_count(store: BaseSQLiteStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.count() == 1


def test_set_stores_value(store: BaseSQLiteStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.get("1") == {"text": "hello"}


def test_set_default_overwrites_existing(store: BaseSQLiteStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


def test_set_on_conflict_raise(store: BaseSQLiteStore) -> None:
    store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        store.set("1", {"text": "updated"}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}


def test_set_on_conflict_skip(store: BaseSQLiteStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}


def test_set_on_conflict_overwrite(store: BaseSQLiteStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}


def test_set_on_conflict_merge(store: BaseSQLiteStore) -> None:
    store.set("1", {"text": "original", "author": "Alice"})
    store.set("1", {"text": "updated"}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


def test_set_on_conflict_new_key_is_unaffected(store: BaseSQLiteStore) -> None:
    store.set("1", {"text": "hello"}, on_conflict="raise")
    assert store.get("1") == {"text": "hello"}


def test_set_on_conflict_invalid_raises(store: BaseSQLiteStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- set_many ---


def test_set_many_increases_count(store: BaseSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


def test_set_many_empty_is_no_op(store: BaseSQLiteStore) -> None:
    store.set_many({})
    assert store.count() == 0


def test_set_many_default_overwrites_existing(store: BaseSQLiteStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


def test_set_many_on_conflict_raise(store: BaseSQLiteStore) -> None:
    store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    # nothing from the conflicting batch should have been written
    assert store.get("1") == {"text": "original"}
    assert store.get("3") is None


def test_set_many_on_conflict_skip(store: BaseSQLiteStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


def test_set_many_on_conflict_overwrite(store: BaseSQLiteStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}
    assert store.get("2") == {"text": "new"}


def test_set_many_on_conflict_merge(store: BaseSQLiteStore) -> None:
    store.set_many({"1": {"text": "original", "author": "Alice"}})
    store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


def test_set_many_on_conflict_invalid_raises(store: BaseSQLiteStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set_many({"1": {"text": "hello"}}, on_conflict="bogus")


# --- set_batches ---


def test_set_batches_empty_is_no_op(store: BaseSQLiteStore) -> None:
    store.set_batches([])
    assert store.count() == 0


def test_set_batches_writes_all_pairs(store: BaseSQLiteStore) -> None:
    store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert store.count() == 3
    assert store.get("2") == {"v": 2}


def test_set_batches_consumes_a_generator(store: BaseSQLiteStore) -> None:
    def gen() -> Iterator[tuple[str, dict[str, int]]]:
        for i in range(5):
            yield str(i), {"v": i}

    store.set_batches(gen(), batch_size=2)
    assert store.count() == 5


def test_set_batches_on_conflict_skip(store: BaseSQLiteStore) -> None:
    store.set("1", {"text": "original"})
    store.set_batches([("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


# --- count ---


def test_count_empty_store(store: BaseSQLiteStore) -> None:
    assert store.count() == 0


def test_count_after_set_many(store: BaseSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


# --- get ---


def test_get_existing_value(store: BaseSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.get("1") == items["1"]


def test_get_missing_key_returns_none(store: BaseSQLiteStore) -> None:
    assert store.get("nonexistent") is None


# --- get_many ---


def test_get_many_returns_correct_length(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert len(store.get_many(["1", "2", "99"])) == 3


def test_get_many_returns_none_for_missing(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["1", "99", "2"])
    assert result[1] is None


def test_get_many_preserves_order(store: BaseSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


def test_get_many_empty_list_returns_empty_list(store: BaseSQLiteStore) -> None:
    assert store.get_many([]) == []


# --- filter ---


def test_filter_no_args_returns_all(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert len(store.filter()) == len(items)


def test_filter_single_field(store: BaseSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


def test_filter_multiple_fields(store: BaseSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice", category="Programming")
    assert len(result) == 2


def test_filter_no_match_returns_empty(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.filter(author="Charlie") == []


def test_filter_rejects_malicious_field_name(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    """A field name is interpolated into the SQL (only the value is
    bound), so anything but a plain identifier must be rejected to
    prevent SQL injection."""
    store.set_many(items)
    with pytest.raises(ValueError, match="Invalid filter field name"):
        store.filter(**{"x') OR 1=1 OR ('": "nonmatching"})


def test_filter_preserves_full_value(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.filter(author="Bob", category="History")
    expected = [v for v in items.values() if v["author"] == "Bob"]
    assert sorted(result, key=lambda v: v["title"]) == sorted(expected, key=lambda v: v["title"])


def test_filter_empty_store_returns_empty(store: BaseSQLiteStore) -> None:
    assert store.filter(author="Alice") == []


def test_filter_integer_field_value(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


def test_filter_integer_value_no_match_returns_empty(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.filter(year=9999) == []


# --- delete ---


def test_delete_removes_value(store: BaseSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete("1")
    assert store.count() == len(items) - 1
    assert store.get("1") is None


def test_delete_nonexistent_is_silent(store: BaseSQLiteStore) -> None:
    store.delete("nonexistent")


# --- delete_many ---


def test_delete_many_removes_values(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.count() == len(items) - 2
    assert store.get("1") is None
    assert store.get("3") is None


def test_delete_many_preserves_other_values(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.get("2") is not None
    assert store.get("4") is not None


def test_delete_many_empty_list_is_no_op(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many([])
    assert store.count() == len(items)


def test_delete_many_nonexistent_keys_are_silent(store: BaseSQLiteStore) -> None:
    store.delete_many(["99", "100"])


def test_delete_many_single_key(store: BaseSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["2"])
    assert store.count() == len(items) - 1
    assert store.get("2") is None


# --- clear ---


def test_clear_removes_all_values(store: BaseSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.clear()
    assert store.count() == 0
    assert list(store.keys()) == []


def test_clear_empty_store_is_no_op(store: BaseSQLiteStore) -> None:
    store.clear()
    assert store.count() == 0


def test_clear_returns_none(store: BaseSQLiteStore) -> None:
    assert store.clear() is None


def test_clear_then_set_works(store: BaseSQLiteStore) -> None:
    store.set("1", {"text": "hello"})
    store.clear()
    store.set("2", {"text": "world"})
    assert store.count() == 1
    assert store.get("2") == {"text": "world"}


# --- contains ---


def test_contains_true_when_key_present(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.contains("1")


def test_contains_false_when_key_missing(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert not store.contains("99")


def test_contains_false_when_store_empty(store: BaseSQLiteStore) -> None:
    assert not store.contains("1")


# --- contains_many ---


def test_contains_many_all_found(store: BaseSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "2", "3", "4"])
    assert found == ["1", "2", "3", "4"]
    assert missing == []


def test_contains_many_all_missing(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["99", "100"])
    assert found == []
    assert missing == ["99", "100"]


def test_contains_many_mixed(store: BaseSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "99", "3", "42"])
    assert found == ["1", "3"]
    assert missing == ["99", "42"]


def test_contains_many_empty_input_returns_empty_lists(store: BaseSQLiteStore) -> None:
    found, missing = store.contains_many([])
    assert found == []
    assert missing == []


def test_contains_many_empty_store_returns_all_missing(store: BaseSQLiteStore) -> None:
    found, missing = store.contains_many(["1", "2"])
    assert found == []
    assert missing == ["1", "2"]


def test_contains_many_returns_tuple_of_two_lists(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.contains_many(["1", "99"])
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


# --- columns_info ---


def test_get_columns_info_returns_dict(store: BaseSQLiteStore) -> None:
    result = store.get_columns_info()
    assert isinstance(result, dict)


def test_get_columns_info_values_are_strings(store: BaseSQLiteStore) -> None:
    result = store.get_columns_info()
    assert all(isinstance(v, str) for v in result.values())


def test_get_columns_info_non_empty_for_created_table(store: BaseSQLiteStore) -> None:
    result = store.get_columns_info()
    assert len(result) > 0


def test_show_columns_info_does_not_raise(
    store: BaseSQLiteStore, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("INFO"):
        store.show_columns_info()
    assert caplog.text != ""


def test_show_columns_info_output_contains_column_names(
    store: BaseSQLiteStore, caplog: pytest.LogCaptureFixture
) -> None:
    expected_columns = store.get_columns_info().keys()
    with caplog.at_level("INFO"):
        store.show_columns_info()
    for col in expected_columns:
        assert col in caplog.text


def test_show_columns_info_returns_none(store: BaseSQLiteStore) -> None:
    assert store.show_columns_info() is None


# --- keys ---


def test_keys_empty_store_yields_nothing(store: BaseSQLiteStore) -> None:
    assert list(store.keys()) == []


def test_keys_returns_all_keys(store: BaseSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert sorted(store.keys()) == sorted(items.keys())


# --- values ---


def test_values_empty_store_yields_nothing(store: BaseSQLiteStore) -> None:
    assert list(store.values()) == []


def test_values_returns_all_values(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = list(store.values())
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


def test_values_is_lazy_generator(store: BaseSQLiteStore) -> None:
    assert isinstance(store.values(), Iterator)


# --- iter_batches ---


def test_iter_batches_empty_store_yields_nothing(store: BaseSQLiteStore) -> None:
    assert list(store.iter_batches()) == []


def test_iter_batches_returns_generator(store: BaseSQLiteStore) -> None:
    result = store.iter_batches()
    assert isinstance(result, Iterator)


def test_iter_batches_default_batch_size(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches())
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


def test_iter_batches_yields_correct_batch_sizes(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert [len(b) for b in batches] == [2, 2]


def test_iter_batches_last_batch_may_be_smaller(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=3))
    assert [len(b) for b in batches] == [3, 1]


def test_iter_batches_batch_size_larger_than_store(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=100))
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


def test_iter_batches_batch_size_one(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=1))
    assert [len(b) for b in batches] == [1, 1, 1, 1]


def test_iter_batches_returns_all_key_value_pairs(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


def test_iter_batches_batches_are_dicts(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert all(isinstance(batch, dict) for batch in batches)


def test_iter_batches_zero_batch_size_raises(store: BaseSQLiteStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=0))


def test_iter_batches_negative_batch_size_raises(store: BaseSQLiteStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=-1))


def test_iter_batches_error_raised_before_any_query(store: BaseSQLiteStore) -> None:
    gen = store.iter_batches(batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        next(gen)


def test_iter_batches_does_not_mutate_store(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    list(store.iter_batches(batch_size=2))
    assert store.count() == len(items)


# --- close ---


def test_close_closes_underlying_connection(store: BaseSQLiteStore) -> None:
    store.close()
    with pytest.raises(sqlite3.ProgrammingError, match=r"closed database"):
        store._conn.execute("SELECT 1")


def test_close_is_idempotent(store: BaseSQLiteStore) -> None:
    store.close()
    store.close()  # should not raise


def test_close_returns_none(store: BaseSQLiteStore) -> None:
    assert store.close() is None


@aiosqlite_available
async def test_close_from_running_event_loop_raises(store: BaseSQLiteStore) -> None:
    await store._ensure_aconn()
    with pytest.raises(RuntimeError, match="inside a running event loop"):
        store.close()


# --- closed ---


def test_closed_false_before_close(store: BaseSQLiteStore) -> None:
    assert not store.closed


def test_closed_true_after_close(store: BaseSQLiteStore) -> None:
    store.close()
    assert store.closed


# --- context manager ---


def test_context_manager_returns_self(
    store: BaseSQLiteStore, store_cls: type[BaseSQLiteStore]
) -> None:
    assert isinstance(store, store_cls)


def test_context_manager_closes_on_normal_exit(store_cls: type[BaseSQLiteStore]) -> None:
    with store_cls(":memory:") as store:
        store.set("1", {"text": "hello"})
        assert store.count() == 1

    with pytest.raises(sqlite3.ProgrammingError, match=r"closed database"):
        store._conn.execute("SELECT 1")


def test_context_manager_closes_on_exception(store_cls: type[BaseSQLiteStore]) -> None:
    msg = "boom"
    with pytest.raises(ValueError, match="boom"), store_cls(":memory:") as store:
        raise ValueError(msg)

    with pytest.raises(sqlite3.ProgrammingError, match=r"closed database"):
        store._conn.execute("SELECT 1")


def test_context_manager_usable_for_reads_and_writes(store_cls: type[BaseSQLiteStore]) -> None:
    with store_cls(":memory:") as store:
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


def test_context_manager_multiple_open_close_in_memory(store_cls: type[BaseSQLiteStore]) -> None:
    sqlite_store = store_cls(":memory:")
    for i in range(3):
        with sqlite_store as store:
            assert store.count() == 0
            store.set(str(i), {"text": "hello"})
            assert store.count() == 1


def test_context_manager_multiple_open_close_persistent(
    tmp_path: Path, store_cls: type[BaseSQLiteStore]
) -> None:
    sqlite_store = store_cls(tmp_path / "data.db")
    for i in range(3):
        with sqlite_store as store:
            store.set(str(i), {"text": "hello"})
            assert store.count() == i + 1


##########################################################
#     TypedSQLiteStore-specific schema behavior          #
##########################################################

# SQLiteStore and TypedSQLiteStore share the exact same behavior when no
# schema is involved (covered by every test above, run against both
# `store_cls` params). TypedSQLiteStore additionally supports declaring typed
# columns via `value_schema`, covered here.


def test_init_no_schema_stores_everything_in_extra(typed_store_no_schema: TypedSQLiteStore) -> None:
    typed_store_no_schema.set("1", {"author": "Alice"})
    assert set(typed_store_no_schema.get_columns_info().keys()) == {"_KEY_", "extra"}


def test_init_with_schema_creates_typed_columns(typed_store: TypedSQLiteStore) -> None:
    columns = typed_store.get_columns_info()
    assert set(columns.keys()) == {"_KEY_", "author", "year", "category", "extra"}


def test_init_schema_with_reserved_key_column_raises() -> None:
    with pytest.raises(ValueError, match="reserved key column name"):
        TypedSQLiteStore(":memory:", value_schema={"_KEY_": "TEXT"})


def test_value_field_named_key_does_not_collide_with_primary_key(
    typed_store_no_schema: TypedSQLiteStore,
) -> None:
    """A value field literally named 'key' must not collide with the
    store's primary key column, and should be stored/retrieved via the
    extra JSON overflow column."""
    typed_store_no_schema.set("1", {"key": "not-the-primary-key"})
    assert typed_store_no_schema.get("1") == {"key": "not-the-primary-key"}
    assert typed_store_no_schema.filter(key="not-the-primary-key") == [
        {"key": "not-the-primary-key"}
    ]


def test_from_path_with_schema(store_path: Path) -> None:
    path = store_path / "with_schema.sqlite"
    schema = {"author": "TEXT", "year": "INTEGER"}
    with TypedSQLiteStore.from_path(path, value_schema=schema) as store:
        store.set("1", {"author": "Alice", "year": 2022})
        assert store.get("1")["year"] == 2022


def test_init_read_only_connection_with_existing_table_does_not_raise(
    store_path: Path, items: dict[str, dict[str, Any]]
) -> None:
    path = store_path / "typed_read_only.sqlite"
    with TypedSQLiteStore.from_path(path) as store:
        store.set_many(items)
    with TypedSQLiteStore.from_path(path, read_only=True) as store:
        assert store.count() == len(items)


def test_set_on_conflict_merge_with_typed_schema(typed_store: TypedSQLiteStore) -> None:
    typed_store.set("1", {"author": "Alice", "year": 2022})
    typed_store.set("1", {"category": "Programming"}, on_conflict="merge")
    assert typed_store.get("1") == {"author": "Alice", "year": 2022, "category": "Programming"}


def test_get_round_trips_typed_schema_fields(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    assert typed_store.get("1") == items["1"]


def test_get_round_trips_extra_field(typed_store: TypedSQLiteStore) -> None:
    typed_store.set("1", {"author": "Alice", "publisher": "O'Reilly"})
    assert typed_store.get("1")["publisher"] == "O'Reilly"


def test_filter_single_typed_field(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result = typed_store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


def test_filter_multiple_typed_fields(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result = typed_store.filter(author="Alice", category="Programming")
    assert len(result) == 2


def test_filter_extra_field(typed_store: TypedSQLiteStore) -> None:
    typed_store.set_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Bob", "publisher": "Manning"},
        }
    )
    result = typed_store.filter(publisher="O'Reilly")
    assert len(result) == 1
    assert result[0]["author"] == "Alice"


def test_filter_mixed_schema_and_extra_fields(typed_store: TypedSQLiteStore) -> None:
    typed_store.set_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Alice", "publisher": "Manning"},
        }
    )
    result = typed_store.filter(author="Alice", publisher="O'Reilly")
    assert len(result) == 1
    assert result[0]["publisher"] == "O'Reilly"


def test_filter_integer_typed_column(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result = typed_store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


def test_filter_integer_typed_column_no_match(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    assert typed_store.filter(year=9999) == []


def test_get_columns_info_typed_store_has_schema_columns(
    typed_store: TypedSQLiteStore,
) -> None:
    columns = typed_store.get_columns_info()
    assert "author" in columns
    assert "year" in columns
    assert "category" in columns


def test_get_columns_info_has_extra_column(typed_store: TypedSQLiteStore) -> None:
    assert "extra" in typed_store.get_columns_info()


def test_iter_batches_with_typed_schema(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in typed_store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


# ---------------------------------------------------------------------------
# to_uri / from_uri
# ---------------------------------------------------------------------------


def test_to_uri_from_uri_round_trips_in_memory_data(
    store_cls: type[BaseSQLiteStore], items: dict[str, dict[str, Any]]
) -> None:
    with store_cls(":memory:") as store:
        store.set_many(items)
        # :memory: never round-trips data -- each connection is a fresh DB.
        with store_cls.from_uri(store.to_uri()) as reloaded:
            assert reloaded.count() == 0


def test_to_uri_from_uri_round_trips_file_data(
    store_path: Path, store_cls: type[BaseSQLiteStore], items: dict[str, dict[str, Any]]
) -> None:
    path = store_path / f"to_uri_{store_cls.__name__}.sqlite"
    with store_cls.from_path(path) as store:
        store.set_many(items)
        uri = store.to_uri()
    with store_cls.from_uri(uri) as reloaded:
        assert reloaded.count() == len(items)


def test_from_uri_read_only_rejects_writes(
    store_path: Path, store_cls: type[BaseSQLiteStore], items: dict[str, dict[str, Any]]
) -> None:
    path = store_path / f"to_uri_ro_{store_cls.__name__}.sqlite"
    with store_cls.from_path(path) as store:
        store.set_many(items)
        uri = store.to_uri()
    with store_cls.from_uri(uri, read_only=True) as reloaded:
        assert reloaded.count() == len(items)
        with pytest.raises(sqlite3.OperationalError):
            reloaded.set("new", {"a": 1})


# ---------------------------------------------------------------------------
# Async methods
# ---------------------------------------------------------------------------


async def test_sqlite_store_aget_aset_round_trip(store: BaseSQLiteStore) -> None:
    await store.aset("1", {"title": "Intro to Python"})
    assert await store.aget("1") == {"title": "Intro to Python"}
    assert await store.aget("missing") is None


async def test_sqlite_store_aset_many_and_afilter(store: BaseSQLiteStore) -> None:
    await store.aset_many(
        {
            "1": {"author": "Alice", "category": "Programming"},
            "2": {"author": "Bob", "category": "History"},
        }
    )
    assert len(await store.afilter(author="Alice")) == 1
    assert len(await store.afilter(category="History")) == 1


async def test_sqlite_store_aensure_aconn_read_only_swallows_operational_error(
    store_path: Path, store_cls: type[BaseSQLiteStore]
) -> None:
    """Mirrors ``test_init_read_only_connection_without_existing_table_s
    wallows_operational_error`` for the lazily-opened async
    ``aiosqlite`` connection."""
    path = store_path / f"async_no_table_yet_{store_cls.__name__}.sqlite"
    raw_conn = sqlite3.connect(path)
    raw_conn.execute("CREATE TABLE unrelated (x INTEGER)")
    raw_conn.commit()
    raw_conn.close()

    store = store_cls.from_path(path, read_only=True)
    with pytest.raises(sqlite3.OperationalError, match=r"no such table"):
        await store.acount()
    await store.aclose()
    store.close()


async def test_sqlite_store_acontains(store: BaseSQLiteStore) -> None:
    await store.aset("1", {"a": 1})
    assert await store.acontains("1") is True
    assert await store.acontains("9") is False


async def test_sqlite_store_acontains_many(store: BaseSQLiteStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    found, missing = await store.acontains_many(["1", "3"])
    assert found == ["1"]
    assert missing == ["3"]


async def test_sqlite_store_adelete_acount(store: BaseSQLiteStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    await store.adelete("1")
    assert await store.acount() == 1


async def test_sqlite_store_akeys_and_aiter_batches(store: BaseSQLiteStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    assert sorted([key async for key in store.akeys()]) == ["1", "2", "3"]
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert sum(len(b) for b in batches) == 3


async def test_sqlite_store_aclose_is_idempotent(store_cls: type[BaseSQLiteStore]) -> None:
    store = store_cls(":memory:")
    await store.aget("1")  # forces the lazy async connection open
    await store.aclose()
    await store.aclose()
    assert store.closed


@aiosqlite_available
async def test_init_accepts_aiosqlite_connect_kwargs(store_cls: type[BaseSQLiteStore]) -> None:
    store = store_cls(":memory:", timeout=5.0)
    assert await store.acount() == 0
    await store.aclose()


def test_sqlite_store_async_methods_work_without_aiosqlite(
    store_cls: type[BaseSQLiteStore], monkeypatch: pytest.MonkeyPatch
) -> None:

    monkeypatch.setattr(sqlite_module, "is_aiosqlite_available", lambda: False)
    with store_cls(":memory:") as store:

        async def _run() -> dict[str, object] | None:
            await store.aset("1", {"a": 1})
            return await store.aget("1")

        assert asyncio.run(_run()) == {"a": 1}


def test_sqlite_store_all_async_methods_work_without_aiosqlite(
    store_cls: type[BaseSQLiteStore], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sqlite_module, "is_aiosqlite_available", lambda: False)
    with store_cls(":memory:") as store:

        async def _run() -> None:
            await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
            assert await store.aget_many(["1", "2", "9"]) == [{"a": 1}, {"a": 2}, None]
            assert len(await store.afilter()) == 3
            assert await store.acontains("1") is True
            found, missing = await store.acontains_many(["1", "9"])
            assert found == ["1"]
            assert missing == ["9"]
            assert sorted([key async for key in store.akeys()]) == ["1", "2", "3"]
            batches = [batch async for batch in store.aiter_batches(batch_size=2)]
            assert sum(len(b) for b in batches) == 3
            assert await store.acount() == 3
            await store.adelete("1")
            assert await store.acount() == 2
            await store.adelete_many(["2", "3"])
            assert await store.acount() == 0
            await store.aset_many({"1": {"a": 1}})
            await store.aclear()
            assert await store.acount() == 0

        asyncio.run(_run())


async def test_sqlite_store_async_context_manager_reopens_after_close(
    store_cls: type[BaseSQLiteStore],
) -> None:
    store = store_cls(":memory:")
    store.close()
    async with store:
        assert not store.closed
        await store.aset("1", {"a": 1})
        assert await store.aget("1") == {"a": 1}
    assert store.closed


# ---------------------------------------------------------------------------
# Additional coverage: async methods on the real (available) aiosqlite path
# that aren't exercised by the round-trip tests above.
# ---------------------------------------------------------------------------


async def test_sqlite_store_aget_many_empty(store: BaseSQLiteStore) -> None:
    assert await store.aget_many([]) == []


async def test_sqlite_store_aget_many(store: BaseSQLiteStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    result = await store.aget_many(["1", "missing", "2"])
    assert result == [{"a": 1}, None, {"a": 2}]


async def test_sqlite_store_aset_many_empty_items(store: BaseSQLiteStore) -> None:
    assert await store.aset_many({}) is None


async def test_sqlite_store_aset_on_conflict_raise(store: BaseSQLiteStore) -> None:
    await store.aset("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        await store.aset("1", {"text": "updated"}, on_conflict="raise")
    assert await store.aget("1") == {"text": "original"}


async def test_sqlite_store_aset_on_conflict_skip(store: BaseSQLiteStore) -> None:
    await store.aset("1", {"text": "original"})
    await store.aset_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert await store.aget("1") == {"text": "original"}
    assert await store.aget("2") == {"text": "new"}


async def test_sqlite_store_aset_on_conflict_overwrite(store: BaseSQLiteStore) -> None:
    await store.aset("1", {"text": "original"})
    await store.aset("1", {"text": "updated"}, on_conflict="overwrite")
    assert await store.aget("1") == {"text": "updated"}


async def test_sqlite_store_aset_on_conflict_merge(store: BaseSQLiteStore) -> None:
    await store.aset("1", {"text": "original", "author": "Alice"})
    await store.aset("1", {"text": "updated"}, on_conflict="merge")
    assert await store.aget("1") == {"text": "updated", "author": "Alice"}


async def test_sqlite_store_aset_many_merge_with_new_key(store: BaseSQLiteStore) -> None:
    """Exercises the non-conflicting-key branch of ``aset_many`` when
    ``on_conflict != 'overwrite'`` (a key not already present is written
    directly, without going through ``aget``)."""
    await store.aset("1", {"text": "original", "author": "Alice"})
    await store.aset_many(
        {"1": {"text": "updated"}, "2": {"text": "brand new"}}, on_conflict="merge"
    )
    assert await store.aget("1") == {"text": "updated", "author": "Alice"}
    assert await store.aget("2") == {"text": "brand new"}


async def test_sqlite_store_aset_many_skip_all_writes_nothing(store: BaseSQLiteStore) -> None:
    """When every key conflicts and ``on_conflict='skip'``, ``to_write``
    ends up empty, exercising the ``if items:`` false branch of
    ``_aset_many``."""
    await store.aset("1", {"text": "original"})
    await store.aset_many({"1": {"text": "updated"}}, on_conflict="skip")
    assert await store.aget("1") == {"text": "original"}


async def test_sqlite_store_afilter_no_filters(store: BaseSQLiteStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    result = await store.afilter()
    assert len(result) == 2


async def test_sqlite_store_afilter_multiple_fields(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    result = await store.afilter(author="Alice", category="Programming")
    assert len(result) == 2


async def test_sqlite_store_afilter_rejects_malicious_field_name(
    store: BaseSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await store.aset_many(items)
    with pytest.raises(ValueError, match="Invalid filter field name"):
        await store.afilter(**{"x') OR 1=1 OR ('": "nonmatching"})


async def test_sqlite_store_adelete_many_empty(store: BaseSQLiteStore) -> None:
    assert await store.adelete_many([]) is None


async def test_sqlite_store_adelete_many(store: BaseSQLiteStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    await store.adelete_many(["1", "3"])
    assert await store.acount() == 1
    assert await store.aget("2") is not None


async def test_sqlite_store_aclear(store: BaseSQLiteStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    await store.aclear()
    assert await store.acount() == 0


async def test_sqlite_store_acontains_many_empty(store: BaseSQLiteStore) -> None:
    assert await store.acontains_many([]) == ([], [])


async def test_sqlite_store_aiter_batches_exact_multiple(store: BaseSQLiteStore) -> None:
    """When the item count is an exact multiple of ``batch_size``, the
    trailing ``if batch:`` check at the end of ``aiter_batches`` is
    false, exercising that branch."""
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}})
    batches = [batch async for batch in store.aiter_batches(batch_size=2)]
    assert sum(len(b) for b in batches) == 2


async def test_sqlite_store_avalues(store: BaseSQLiteStore) -> None:
    await store.aset_many({"1": {"a": 1}, "2": {"a": 2}, "3": {"a": 3}})
    values = [v async for v in store.avalues(batch_size=2)]
    assert sorted(v["a"] for v in values) == [1, 2, 3]


async def test_sqlite_store_aset_batches(store: BaseSQLiteStore) -> None:
    await store.aset_batches([("1", {"a": 1}), ("2", {"a": 2})], batch_size=1)
    assert await store.acount() == 2


# ---------------------------------------------------------------------------
# async + typed schema
# ---------------------------------------------------------------------------


async def test_typed_sqlite_store_aget_round_trips_typed_schema_fields(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    assert await typed_store.aget("1") == items["1"]


async def test_typed_sqlite_store_aset_on_conflict_merge_with_typed_schema(
    typed_store: TypedSQLiteStore,
) -> None:
    await typed_store.aset("1", {"author": "Alice", "year": 2022})
    await typed_store.aset("1", {"category": "Programming"}, on_conflict="merge")
    assert await typed_store.aget("1") == {
        "author": "Alice",
        "year": 2022,
        "category": "Programming",
    }


async def test_typed_sqlite_store_afilter_single_typed_field(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    result = await typed_store.afilter(author="Alice")
    assert {item["title"] for item in result} == {"Intro to Python", "Advanced Python"}


async def test_typed_sqlite_store_afilter_integer_typed_column(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    result = await typed_store.afilter(year=2022)
    assert {item["title"] for item in result} == {"Intro to Python"}


async def test_typed_sqlite_store_aiter_batches_with_typed_schema(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    result: dict[str, dict[str, Any]] = {}
    async for batch in typed_store.aiter_batches(batch_size=2):
        result.update(batch)
    assert result == items


async def test_typed_sqlite_store_avalues_with_typed_schema(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    values = [v async for v in typed_store.avalues(batch_size=2)]
    assert sorted(v["title"] for v in values) == sorted(item["title"] for item in items.values())


async def test_typed_sqlite_store_aset_on_conflict_raise_with_typed_schema(
    typed_store: TypedSQLiteStore,
) -> None:
    await typed_store.aset("1", {"author": "Alice"})
    with pytest.raises(KeyError, match=r"1"):
        await typed_store.aset("1", {"author": "Bob"}, on_conflict="raise")
    assert await typed_store.aget("1") == {"author": "Alice"}


async def test_typed_sqlite_store_aset_on_conflict_skip_with_typed_schema(
    typed_store: TypedSQLiteStore,
) -> None:
    await typed_store.aset("1", {"author": "Alice"})
    await typed_store.aset("1", {"author": "Bob"}, on_conflict="skip")
    assert await typed_store.aget("1") == {"author": "Alice"}


async def test_typed_sqlite_store_aset_on_conflict_overwrite_with_typed_schema(
    typed_store: TypedSQLiteStore,
) -> None:
    await typed_store.aset("1", {"author": "Alice"})
    await typed_store.aset("1", {"author": "Bob"}, on_conflict="overwrite")
    assert await typed_store.aget("1") == {"author": "Bob"}


async def test_typed_sqlite_store_afilter_multiple_typed_fields(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    result = await typed_store.afilter(author="Alice", category="Programming")
    assert sorted(r["title"] for r in result) == ["Advanced Python", "Intro to Python"]


async def test_typed_sqlite_store_afilter_extra_field(typed_store: TypedSQLiteStore) -> None:
    await typed_store.aset_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Bob", "publisher": "Packt"},
        }
    )
    result = await typed_store.afilter(publisher="O'Reilly")
    assert result == [{"author": "Alice", "publisher": "O'Reilly"}]


async def test_typed_sqlite_store_afilter_mixed_schema_and_extra_fields(
    typed_store: TypedSQLiteStore,
) -> None:
    await typed_store.aset_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Alice", "publisher": "Packt"},
        }
    )
    result = await typed_store.afilter(author="Alice", publisher="O'Reilly")
    assert result == [{"author": "Alice", "publisher": "O'Reilly"}]


async def test_typed_sqlite_store_afilter_integer_typed_column_no_match(
    typed_store: TypedSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    await typed_store.aset_many(items)
    assert await typed_store.afilter(year=9999) == []


async def test_typed_sqlite_store_aget_columns_info_has_schema_columns(
    typed_store: TypedSQLiteStore,
) -> None:
    columns = typed_store.get_columns_info()
    assert "author" in columns
    assert "year" in columns


async def test_typed_sqlite_store_to_uri_from_uri_async_round_trip(
    store_path: Path, items: dict[str, dict[str, Any]]
) -> None:
    path = store_path / "to_uri_async_typed.sqlite"
    with TypedSQLiteStore.from_path(path) as store:
        store.set_many(items)
        uri = store.to_uri()
    async with TypedSQLiteStore.from_uri(uri) as reloaded:
        assert await reloaded.acount() == len(items)


async def test_typed_sqlite_store_afrom_uri_read_only_rejects_writes(
    store_path: Path, items: dict[str, dict[str, Any]]
) -> None:
    path = store_path / "to_uri_ro_async_typed.sqlite"
    with TypedSQLiteStore.from_path(path) as store:
        store.set_many(items)
        uri = store.to_uri()
    async with TypedSQLiteStore.from_uri(uri, read_only=True) as reloaded:
        assert await reloaded.acount() == len(items)
        with pytest.raises(sqlite3.OperationalError):
            await reloaded.aset("new", {"author": "x"})
