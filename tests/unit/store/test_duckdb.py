from __future__ import annotations

from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import DuckDBStore
from persista.testing.fixtures import duckdb_available
from persista.utils.imports import is_duckdb_available

if TYPE_CHECKING:
    from pathlib import Path

if is_duckdb_available():
    import duckdb

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def store_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("store")


@pytest.fixture
def store() -> Generator[DuckDBStore, None, None]:
    with DuckDBStore(":memory:") as store:
        yield store


@pytest.fixture(scope="module")
def store_read_only(
    store_path: Path, items: dict[str, dict[str, Any]]
) -> Generator[DuckDBStore, None, None]:
    path = store_path / "data.duckdb"
    with DuckDBStore(path) as store:
        store.set_many(items)
    with DuckDBStore(path, read_only=True) as store:
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


#################################
#     Tests for DuckDBStore     #
#################################


# --- constructor ---


@duckdb_available
def test_init_defaults_to_in_memory() -> None:
    with DuckDBStore() as store:
        assert store.count() == 0


@duckdb_available
def test_init_accepts_duckdb_connect_kwargs() -> None:
    with DuckDBStore(":memory:", read_only=False) as store:
        assert store.count() == 0


@duckdb_available
def test_init_creates_table() -> None:
    with DuckDBStore(":memory:") as store:
        assert store.count() == 0


@duckdb_available
def test_init_creates_file_backed_store(store_path: Path) -> None:
    path = store_path / "init.duckdb"
    with DuckDBStore(path) as store:
        store.set("1", {"text": "hello"})
        assert store.count() == 1
        assert path.exists()


@duckdb_available
def test_init_read_only_can_read_existing_data(store_read_only: DuckDBStore) -> None:
    assert store_read_only.count() == 4


@duckdb_available
def test_init_read_only_rejects_writes(store_read_only: DuckDBStore) -> None:
    with pytest.raises(duckdb.Error, match=r"read-only"):
        store_read_only.set("99", {"text": "x"})


# --- repr/str ---


@duckdb_available
def test_repr(store: DuckDBStore) -> None:
    assert repr(store).startswith("DuckDBStore(")


@duckdb_available
def test_str(store: DuckDBStore) -> None:
    assert str(store).startswith("DuckDBStore(")


@duckdb_available
def test_repr_after_close_does_not_raise(store: DuckDBStore) -> None:
    store.close()
    assert repr(store).startswith("DuckDBStore(")


# --- set ---


@duckdb_available
def test_set_increases_count(store: DuckDBStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.count() == 1


@duckdb_available
def test_set_stores_value(store: DuckDBStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.get("1") == {"text": "hello"}


@duckdb_available
def test_set_default_overwrites_existing(store: DuckDBStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


@duckdb_available
def test_set_on_conflict_raise(store: DuckDBStore) -> None:
    store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        store.set("1", {"text": "updated"}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}


@duckdb_available
def test_set_on_conflict_skip(store: DuckDBStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}


@duckdb_available
def test_set_on_conflict_overwrite(store: DuckDBStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}


@duckdb_available
def test_set_on_conflict_merge(store: DuckDBStore) -> None:
    store.set("1", {"text": "original", "author": "Alice"})
    store.set("1", {"text": "updated"}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


@duckdb_available
def test_set_on_conflict_new_key_is_unaffected(store: DuckDBStore) -> None:
    store.set("1", {"text": "hello"}, on_conflict="raise")
    assert store.get("1") == {"text": "hello"}


@duckdb_available
def test_set_on_conflict_invalid_raises(store: DuckDBStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- set_many ---


@duckdb_available
def test_set_many_increases_count(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


@duckdb_available
def test_set_many_empty_is_no_op(store: DuckDBStore) -> None:
    store.set_many({})
    assert store.count() == 0


@duckdb_available
def test_set_many_default_overwrites_existing(store: DuckDBStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


@duckdb_available
def test_set_many_on_conflict_raise(store: DuckDBStore) -> None:
    store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    # nothing from the conflicting batch should have been written
    assert store.get("1") == {"text": "original"}
    assert store.get("3") is None


@duckdb_available
def test_set_many_on_conflict_skip(store: DuckDBStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


@duckdb_available
def test_set_many_on_conflict_overwrite(store: DuckDBStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}
    assert store.get("2") == {"text": "new"}


@duckdb_available
def test_set_many_on_conflict_merge(store: DuckDBStore) -> None:
    store.set_many({"1": {"text": "original", "author": "Alice"}})
    store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


@duckdb_available
def test_set_many_on_conflict_invalid_raises(store: DuckDBStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set_many({"1": {"text": "hello"}}, on_conflict="bogus")


# --- set_batches ---


@duckdb_available
def test_set_batches_empty_is_no_op(store: DuckDBStore) -> None:
    store.set_batches([])
    assert store.count() == 0


@duckdb_available
def test_set_batches_writes_all_pairs(store: DuckDBStore) -> None:
    store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert store.count() == 3
    assert store.get("2") == {"v": 2}


@duckdb_available
def test_set_batches_consumes_a_generator(store: DuckDBStore) -> None:
    def gen() -> Iterator[tuple[str, dict[str, int]]]:
        for i in range(5):
            yield str(i), {"v": i}

    store.set_batches(gen(), batch_size=2)
    assert store.count() == 5


@duckdb_available
def test_set_batches_on_conflict_skip(store: DuckDBStore) -> None:
    store.set("1", {"text": "original"})
    store.set_batches([("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


# --- count ---


@duckdb_available
def test_count_empty_store(store: DuckDBStore) -> None:
    assert store.count() == 0


@duckdb_available
def test_count_after_set_many(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


# --- get ---


@duckdb_available
def test_get_existing_value(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.get("1") == items["1"]


@duckdb_available
def test_get_missing_key_returns_none(store: DuckDBStore) -> None:
    assert store.get("nonexistent") is None


# --- get_many ---


@duckdb_available
def test_get_many_returns_correct_length(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert len(store.get_many(["1", "2", "99"])) == 3


@duckdb_available
def test_get_many_returns_none_for_missing(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["1", "99", "2"])
    assert result[1] is None


@duckdb_available
def test_get_many_preserves_order(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


@duckdb_available
def test_get_many_empty_list_returns_empty_list(store: DuckDBStore) -> None:
    assert store.get_many([]) == []


# --- filter ---


@duckdb_available
def test_filter_no_args_returns_all(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert len(store.filter()) == len(items)


@duckdb_available
def test_filter_single_field(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


@duckdb_available
def test_filter_multiple_fields(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice", category="Programming")
    assert len(result) == 2


@duckdb_available
def test_filter_no_match_returns_empty(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.filter(author="Charlie") == []


@duckdb_available
def test_filter_preserves_full_value(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Bob", category="History")
    expected = [v for v in items.values() if v["author"] == "Bob"]
    assert sorted(result, key=lambda v: v["title"]) == sorted(expected, key=lambda v: v["title"])


@duckdb_available
def test_filter_empty_store_returns_empty(store: DuckDBStore) -> None:
    assert store.filter(author="Alice") == []


@duckdb_available
def test_filter_integer_field_value(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


@duckdb_available
def test_filter_integer_value_no_match_returns_empty(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.filter(year=9999) == []


# --- delete ---


@duckdb_available
def test_delete_removes_value(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete("1")
    assert store.count() == len(items) - 1
    assert store.get("1") is None


@duckdb_available
def test_delete_nonexistent_is_silent(store: DuckDBStore) -> None:
    store.delete("nonexistent")


# --- delete_many ---


@duckdb_available
def test_delete_many_removes_values(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.count() == len(items) - 2
    assert store.get("1") is None
    assert store.get("3") is None


@duckdb_available
def test_delete_many_preserves_other_values(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.get("2") is not None
    assert store.get("4") is not None


@duckdb_available
def test_delete_many_empty_list_is_no_op(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many([])
    assert store.count() == len(items)


@duckdb_available
def test_delete_many_nonexistent_keys_are_silent(store: DuckDBStore) -> None:
    store.delete_many(["99", "100"])


@duckdb_available
def test_delete_many_single_key(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["2"])
    assert store.count() == len(items) - 1
    assert store.get("2") is None


# --- contains_many ---


@duckdb_available
def test_contains_many_all_found(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "2", "3", "4"])
    assert found == ["1", "2", "3", "4"]
    assert missing == []


@duckdb_available
def test_contains_many_all_missing(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["99", "100"])
    assert found == []
    assert missing == ["99", "100"]


@duckdb_available
def test_contains_many_mixed(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "99", "3", "42"])
    assert found == ["1", "3"]
    assert missing == ["99", "42"]


@duckdb_available
def test_contains_many_empty_input_returns_empty_lists(store: DuckDBStore) -> None:
    found, missing = store.contains_many([])
    assert found == []
    assert missing == []


@duckdb_available
def test_contains_many_empty_store_returns_all_missing(store: DuckDBStore) -> None:
    found, missing = store.contains_many(["1", "2"])
    assert found == []
    assert missing == ["1", "2"]


@duckdb_available
def test_contains_many_returns_tuple_of_two_lists(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.contains_many(["1", "99"])
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


# --- columns_info ---


@duckdb_available
def test_get_columns_info_returns_dict(store: DuckDBStore) -> None:
    result = store.get_columns_info()
    assert isinstance(result, dict)


@duckdb_available
def test_get_columns_info_keys_are_column_names(store: DuckDBStore) -> None:
    result = store.get_columns_info()
    assert set(result.keys()) == {"key", "value"}


@duckdb_available
def test_get_columns_info_values_are_strings(store: DuckDBStore) -> None:
    result = store.get_columns_info()
    assert all(isinstance(v, str) for v in result.values())


@duckdb_available
def test_get_columns_info_non_empty_for_created_table(store: DuckDBStore) -> None:
    result = store.get_columns_info()
    assert len(result) > 0


@duckdb_available
def test_show_columns_info_returns_none(store: DuckDBStore) -> None:
    assert store.show_columns_info() is None


# --- keys ---


@duckdb_available
def test_keys_empty_store_yields_nothing(store: DuckDBStore) -> None:
    assert list(store.keys()) == []


@duckdb_available
def test_keys_returns_all_keys(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert sorted(store.keys()) == sorted(items.keys())


# --- values ---


@duckdb_available
def test_values_empty_store_yields_nothing(store: DuckDBStore) -> None:
    assert list(store.values()) == []


@duckdb_available
def test_values_returns_all_values(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = list(store.values())
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


@duckdb_available
def test_values_is_lazy_generator(store: DuckDBStore) -> None:
    assert isinstance(store.values(), Iterator)


# --- iter_batches ---


@duckdb_available
def test_iter_batches_empty_store_yields_nothing(store: DuckDBStore) -> None:
    assert list(store.iter_batches()) == []


@duckdb_available
def test_iter_batches_returns_generator(store: DuckDBStore) -> None:
    result = store.iter_batches()
    assert isinstance(result, Iterator)


@duckdb_available
def test_iter_batches_default_batch_size(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches())
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


@duckdb_available
def test_iter_batches_yields_correct_batch_sizes(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert [len(b) for b in batches] == [2, 2]


@duckdb_available
def test_iter_batches_last_batch_may_be_smaller(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=3))
    assert [len(b) for b in batches] == [3, 1]


@duckdb_available
def test_iter_batches_batch_size_larger_than_store(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=100))
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


@duckdb_available
def test_iter_batches_batch_size_one(store: DuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=1))
    assert [len(b) for b in batches] == [1, 1, 1, 1]


@duckdb_available
def test_iter_batches_returns_all_key_value_pairs(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


@duckdb_available
def test_iter_batches_batches_are_dicts(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert all(isinstance(batch, dict) for batch in batches)


@duckdb_available
def test_iter_batches_zero_batch_size_raises(store: DuckDBStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=0))


@duckdb_available
def test_iter_batches_negative_batch_size_raises(store: DuckDBStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=-1))


@duckdb_available
def test_iter_batches_error_raised_before_any_query(store: DuckDBStore) -> None:
    gen = store.iter_batches(batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        next(gen)


@duckdb_available
def test_iter_batches_does_not_mutate_store(
    store: DuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    list(store.iter_batches(batch_size=2))
    assert store.count() == len(items)


# --- close ---


@duckdb_available
def test_close_closes_underlying_connection(store: DuckDBStore) -> None:
    store.close()
    with pytest.raises(duckdb.Error):
        store._conn.execute("SELECT 1")


@duckdb_available
def test_close_is_idempotent(store: DuckDBStore) -> None:
    store.close()
    store.close()  # should not raise


@duckdb_available
def test_close_returns_none(store: DuckDBStore) -> None:
    assert store.close() is None


# --- context manager ---


@duckdb_available
def test_context_manager_returns_self() -> None:
    with DuckDBStore(":memory:") as store:
        assert isinstance(store, DuckDBStore)


@duckdb_available
def test_context_manager_closes_on_normal_exit() -> None:
    with DuckDBStore(":memory:") as store:
        store.set("1", {"text": "hello"})
        assert store.count() == 1

    with pytest.raises(duckdb.Error):
        store._conn.execute("SELECT 1")


@duckdb_available
def test_context_manager_closes_on_exception() -> None:
    msg = "boom"
    with pytest.raises(ValueError, match="boom"), DuckDBStore(":memory:") as store:
        raise ValueError(msg)

    with pytest.raises(duckdb.Error):
        store._conn.execute("SELECT 1")


@duckdb_available
def test_context_manager_usable_for_reads_and_writes() -> None:
    with DuckDBStore(":memory:") as store:
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


@duckdb_available
def test_context_manager_multiple_open_close_in_memory() -> None:
    duckdb_store = DuckDBStore(":memory:")
    for i in range(3):
        with duckdb_store as store:
            assert store.count() == 0
            store.set(str(i), {"text": "hello"})
            assert store.count() == 1


@duckdb_available
def test_context_manager_multiple_open_close_persistent(tmp_path: Path) -> None:
    duckdb_store = DuckDBStore(tmp_path / "data.duckdb")
    for i in range(3):
        with duckdb_store as store:
            store.set(str(i), {"text": "hello"})
            assert store.count() == i + 1
