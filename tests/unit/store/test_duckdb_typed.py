from __future__ import annotations

from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import TypedDuckDBStore
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
def store() -> Generator[TypedDuckDBStore, None, None]:
    """In-memory store with no schema."""
    with TypedDuckDBStore(":memory:") as store:
        yield store


@pytest.fixture
def typed_store() -> Generator[TypedDuckDBStore, None, None]:
    """In-memory store with a typed schema."""
    with TypedDuckDBStore(
        ":memory:",
        value_schema={"author": "VARCHAR", "year": "INTEGER", "category": "VARCHAR"},
    ) as store:
        yield store


@pytest.fixture(scope="module")
def store_read_only(
    store_path: Path, items: dict[str, dict[str, Any]]
) -> Generator[TypedDuckDBStore, None, None]:
    path = store_path / "data.duckdb"
    with TypedDuckDBStore(path) as store:
        store.set_many(items)
    with TypedDuckDBStore(path, read_only=True) as store:
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


######################################
#     Tests for TypedDuckDBStore     #
######################################


# --- constructor ---


@duckdb_available
def test_init_defaults_to_in_memory() -> None:
    with TypedDuckDBStore() as store:
        assert store.count() == 0


@duckdb_available
def test_init_accepts_duckdb_connect_kwargs() -> None:
    with TypedDuckDBStore(":memory:", read_only=False) as store:
        assert store.count() == 0


@duckdb_available
def test_init_no_schema_stores_everything_in_extra(store: TypedDuckDBStore) -> None:
    store.set("1", {"author": "Alice"})
    assert set(store.get_columns_info().keys()) == {"_KEY_", "extra"}


@duckdb_available
def test_init_with_schema_creates_typed_columns(typed_store: TypedDuckDBStore) -> None:
    columns = typed_store.get_columns_info()
    assert set(columns.keys()) == {"_KEY_", "author", "year", "category", "extra"}


@duckdb_available
def test_init_schema_with_reserved_key_column_raises() -> None:
    with pytest.raises(ValueError, match="reserved key column name"):
        TypedDuckDBStore(":memory:", value_schema={"_KEY_": "VARCHAR"})


@duckdb_available
def test_value_field_named_key_does_not_collide_with_primary_key(
    store: TypedDuckDBStore,
) -> None:
    """A value field literally named 'key' must not collide with the
    store's primary key column, and should be stored/retrieved via the
    extra JSON overflow column."""
    store.set("1", {"key": "not-the-primary-key"})
    assert store.get("1") == {"key": "not-the-primary-key"}
    assert store.filter(key="not-the-primary-key") == [{"key": "not-the-primary-key"}]


@duckdb_available
def test_init_creates_file_backed_store(store_path: Path) -> None:
    path = store_path / "init.duckdb"
    with TypedDuckDBStore(path) as store:
        store.set("1", {"text": "hello"})
        assert store.count() == 1
        assert path.exists()


@duckdb_available
def test_init_with_schema_file_backed(store_path: Path) -> None:
    path = store_path / "with_schema.duckdb"
    schema = {"author": "VARCHAR", "year": "INTEGER"}
    with TypedDuckDBStore(path, value_schema=schema) as store:
        store.set("1", {"author": "Alice", "year": 2022})
        assert store.get("1")["year"] == 2022


@duckdb_available
def test_init_read_only_can_read_existing_data(store_read_only: TypedDuckDBStore) -> None:
    assert store_read_only.count() == 4


@duckdb_available
def test_init_read_only_rejects_writes(store_read_only: TypedDuckDBStore) -> None:
    with pytest.raises(duckdb.Error, match=r"read-only"):
        store_read_only.set("99", {"text": "x"})


# --- repr/str ---


@duckdb_available
def test_repr(store: TypedDuckDBStore) -> None:
    assert repr(store).startswith("TypedDuckDBStore(")


@duckdb_available
def test_str(store: TypedDuckDBStore) -> None:
    assert str(store).startswith("TypedDuckDBStore(")


@duckdb_available
def test_repr_after_close_does_not_raise(store: TypedDuckDBStore) -> None:
    store.close()
    assert repr(store).startswith("TypedDuckDBStore(")


# --- set ---


@duckdb_available
def test_set_increases_count(store: TypedDuckDBStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.count() == 1


@duckdb_available
def test_set_stores_value(store: TypedDuckDBStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.get("1") == {"text": "hello"}


@duckdb_available
def test_set_default_overwrites_existing(store: TypedDuckDBStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


@duckdb_available
def test_set_on_conflict_raise(store: TypedDuckDBStore) -> None:
    store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        store.set("1", {"text": "updated"}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}


@duckdb_available
def test_set_on_conflict_skip(store: TypedDuckDBStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}


@duckdb_available
def test_set_on_conflict_overwrite(store: TypedDuckDBStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}


@duckdb_available
def test_set_on_conflict_merge(store: TypedDuckDBStore) -> None:
    store.set("1", {"text": "original", "author": "Alice"})
    store.set("1", {"text": "updated"}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


@duckdb_available
def test_set_on_conflict_merge_with_typed_schema(typed_store: TypedDuckDBStore) -> None:
    typed_store.set("1", {"author": "Alice", "year": 2022})
    typed_store.set("1", {"category": "Programming"}, on_conflict="merge")
    assert typed_store.get("1") == {"author": "Alice", "year": 2022, "category": "Programming"}


@duckdb_available
def test_set_on_conflict_new_key_is_unaffected(store: TypedDuckDBStore) -> None:
    store.set("1", {"text": "hello"}, on_conflict="raise")
    assert store.get("1") == {"text": "hello"}


@duckdb_available
def test_set_on_conflict_invalid_raises(store: TypedDuckDBStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set("1", {"text": "hello"}, on_conflict="bogus")


# --- set_many ---


@duckdb_available
def test_set_many_increases_count(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.count() == len(items)


@duckdb_available
def test_set_many_empty_is_no_op(store: TypedDuckDBStore) -> None:
    store.set_many({})
    assert store.count() == 0


@duckdb_available
def test_set_many_default_overwrites_existing(store: TypedDuckDBStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


@duckdb_available
def test_set_many_on_conflict_raise(store: TypedDuckDBStore) -> None:
    store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    # nothing from the conflicting batch should have been written
    assert store.get("1") == {"text": "original"}
    assert store.get("3") is None


@duckdb_available
def test_set_many_on_conflict_skip(store: TypedDuckDBStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


@duckdb_available
def test_set_many_on_conflict_overwrite(store: TypedDuckDBStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}
    assert store.get("2") == {"text": "new"}


@duckdb_available
def test_set_many_on_conflict_merge(store: TypedDuckDBStore) -> None:
    store.set_many({"1": {"text": "original", "author": "Alice"}})
    store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


@duckdb_available
def test_set_many_on_conflict_invalid_raises(store: TypedDuckDBStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set_many({"1": {"text": "hello"}}, on_conflict="bogus")


# --- set_batches ---


@duckdb_available
def test_set_batches_empty_is_no_op(store: TypedDuckDBStore) -> None:
    store.set_batches([])
    assert store.count() == 0


@duckdb_available
def test_set_batches_writes_all_pairs(store: TypedDuckDBStore) -> None:
    store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert store.count() == 3
    assert store.get("2") == {"v": 2}


@duckdb_available
def test_set_batches_consumes_a_generator(store: TypedDuckDBStore) -> None:
    def gen() -> Iterator[tuple[str, dict[str, int]]]:
        for i in range(5):
            yield str(i), {"v": i}

    store.set_batches(gen(), batch_size=2)
    assert store.count() == 5


@duckdb_available
def test_set_batches_on_conflict_skip(store: TypedDuckDBStore) -> None:
    store.set("1", {"text": "original"})
    store.set_batches([("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


# --- count ---


@duckdb_available
def test_count_empty_store(store: TypedDuckDBStore) -> None:
    assert store.count() == 0


@duckdb_available
def test_count_after_set_many(store: TypedDuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


# --- get ---


@duckdb_available
def test_get_existing_value(store: TypedDuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.get("1") == items["1"]


@duckdb_available
def test_get_missing_key_returns_none(store: TypedDuckDBStore) -> None:
    assert store.get("nonexistent") is None


@duckdb_available
def test_get_round_trips_typed_schema_fields(
    typed_store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    assert typed_store.get("1") == items["1"]


@duckdb_available
def test_get_round_trips_extra_field(typed_store: TypedDuckDBStore) -> None:
    typed_store.set("1", {"author": "Alice", "publisher": "O'Reilly"})
    assert typed_store.get("1")["publisher"] == "O'Reilly"


# --- get_many ---


@duckdb_available
def test_get_many_returns_correct_length(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert len(store.get_many(["1", "2", "99"])) == 3


@duckdb_available
def test_get_many_returns_none_for_missing(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["1", "99", "2"])
    assert result[1] is None


@duckdb_available
def test_get_many_preserves_order(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


@duckdb_available
def test_get_many_empty_list_returns_empty_list(store: TypedDuckDBStore) -> None:
    assert store.get_many([]) == []


# --- filter ---


@duckdb_available
def test_filter_no_args_returns_all(
    typed_store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    assert len(typed_store.filter()) == len(items)


@duckdb_available
def test_filter_single_typed_field(
    typed_store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result = typed_store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


@duckdb_available
def test_filter_multiple_typed_fields(
    typed_store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result = typed_store.filter(author="Alice", category="Programming")
    assert len(result) == 2


@duckdb_available
def test_filter_no_match_returns_empty(
    typed_store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    assert typed_store.filter(author="Charlie") == []


@duckdb_available
def test_filter_rejects_malicious_field_name(
    typed_store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    """A non-schema field name is interpolated into the SQL (only the
    value is bound), so anything but a plain identifier must be rejected
    to prevent SQL injection."""
    typed_store.set_many(items)
    with pytest.raises(ValueError, match="Invalid filter field name"):
        typed_store.filter(**{"x') OR 1=1 OR ('": "nonmatching"})


@duckdb_available
def test_filter_extra_field(typed_store: TypedDuckDBStore) -> None:
    typed_store.set_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Bob", "publisher": "Manning"},
        }
    )
    result = typed_store.filter(publisher="O'Reilly")
    assert len(result) == 1
    assert result[0]["author"] == "Alice"


@duckdb_available
def test_filter_mixed_schema_and_extra_fields(typed_store: TypedDuckDBStore) -> None:
    typed_store.set_many(
        {
            "1": {"author": "Alice", "publisher": "O'Reilly"},
            "2": {"author": "Alice", "publisher": "Manning"},
        }
    )
    result = typed_store.filter(author="Alice", publisher="O'Reilly")
    assert len(result) == 1
    assert result[0]["publisher"] == "O'Reilly"


@duckdb_available
def test_filter_integer_typed_column(
    typed_store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result = typed_store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


@duckdb_available
def test_filter_integer_typed_column_no_match(
    typed_store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    assert typed_store.filter(year=9999) == []


@duckdb_available
def test_filter_empty_store_returns_empty(store: TypedDuckDBStore) -> None:
    assert store.filter(author="Alice") == []


# --- delete ---


@duckdb_available
def test_delete_removes_value(store: TypedDuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete("1")
    assert store.count() == len(items) - 1
    assert store.get("1") is None


@duckdb_available
def test_delete_nonexistent_is_silent(store: TypedDuckDBStore) -> None:
    store.delete("nonexistent")


# --- delete_many ---


@duckdb_available
def test_delete_many_removes_values(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.count() == len(items) - 2
    assert store.get("1") is None
    assert store.get("3") is None


@duckdb_available
def test_delete_many_preserves_other_values(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.get("2") is not None
    assert store.get("4") is not None


@duckdb_available
def test_delete_many_empty_list_is_no_op(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many([])
    assert store.count() == len(items)


@duckdb_available
def test_delete_many_nonexistent_keys_are_silent(store: TypedDuckDBStore) -> None:
    store.delete_many(["99", "100"])


@duckdb_available
def test_delete_many_single_key(store: TypedDuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["2"])
    assert store.count() == len(items) - 1
    assert store.get("2") is None


# --- contains_many ---


@duckdb_available
def test_contains_many_all_found(store: TypedDuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "2", "3", "4"])
    assert found == ["1", "2", "3", "4"]
    assert missing == []


@duckdb_available
def test_contains_many_all_missing(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["99", "100"])
    assert found == []
    assert missing == ["99", "100"]


@duckdb_available
def test_contains_many_mixed(store: TypedDuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "99", "3", "42"])
    assert found == ["1", "3"]
    assert missing == ["99", "42"]


@duckdb_available
def test_contains_many_empty_input_returns_empty_lists(store: TypedDuckDBStore) -> None:
    found, missing = store.contains_many([])
    assert found == []
    assert missing == []


@duckdb_available
def test_contains_many_empty_store_returns_all_missing(store: TypedDuckDBStore) -> None:
    found, missing = store.contains_many(["1", "2"])
    assert found == []
    assert missing == ["1", "2"]


@duckdb_available
def test_contains_many_returns_tuple_of_two_lists(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.contains_many(["1", "99"])
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


# --- columns_info ---


@duckdb_available
def test_get_columns_info_returns_dict(store: TypedDuckDBStore) -> None:
    result = store.get_columns_info()
    assert isinstance(result, dict)


@duckdb_available
def test_get_columns_info_typed_store_has_schema_columns(
    typed_store: TypedDuckDBStore,
) -> None:
    columns = typed_store.get_columns_info()
    assert "author" in columns
    assert "year" in columns
    assert "category" in columns


@duckdb_available
def test_get_columns_info_has_extra_column(typed_store: TypedDuckDBStore) -> None:
    assert "extra" in typed_store.get_columns_info()


@duckdb_available
def test_show_columns_info_returns_none(store: TypedDuckDBStore) -> None:
    assert store.show_columns_info() is None


# --- keys ---


@duckdb_available
def test_keys_empty_store_yields_nothing(store: TypedDuckDBStore) -> None:
    assert list(store.keys()) == []


@duckdb_available
def test_keys_returns_all_keys(store: TypedDuckDBStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert sorted(store.keys()) == sorted(items.keys())


# --- values ---


@duckdb_available
def test_values_empty_store_yields_nothing(store: TypedDuckDBStore) -> None:
    assert list(store.values()) == []


@duckdb_available
def test_values_returns_all_values(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = list(store.values())
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


@duckdb_available
def test_values_is_lazy_generator(store: TypedDuckDBStore) -> None:
    assert isinstance(store.values(), Iterator)


# --- iter_batches ---


@duckdb_available
def test_iter_batches_empty_store_yields_nothing(store: TypedDuckDBStore) -> None:
    assert list(store.iter_batches()) == []


@duckdb_available
def test_iter_batches_returns_generator(store: TypedDuckDBStore) -> None:
    result = store.iter_batches()
    assert isinstance(result, Iterator)


@duckdb_available
def test_iter_batches_default_batch_size(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches())
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


@duckdb_available
def test_iter_batches_yields_correct_batch_sizes(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert [len(b) for b in batches] == [2, 2]


@duckdb_available
def test_iter_batches_last_batch_may_be_smaller(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=3))
    assert [len(b) for b in batches] == [3, 1]


@duckdb_available
def test_iter_batches_batch_size_larger_than_store(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=100))
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


@duckdb_available
def test_iter_batches_batch_size_one(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=1))
    assert [len(b) for b in batches] == [1, 1, 1, 1]


@duckdb_available
def test_iter_batches_returns_all_key_value_pairs(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


@duckdb_available
def test_iter_batches_with_typed_schema(
    typed_store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    typed_store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in typed_store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


@duckdb_available
def test_iter_batches_batches_are_dicts(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert all(isinstance(batch, dict) for batch in batches)


@duckdb_available
def test_iter_batches_zero_batch_size_raises(store: TypedDuckDBStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=0))


@duckdb_available
def test_iter_batches_negative_batch_size_raises(store: TypedDuckDBStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=-1))


@duckdb_available
def test_iter_batches_error_raised_before_any_query(store: TypedDuckDBStore) -> None:
    gen = store.iter_batches(batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        next(gen)


@duckdb_available
def test_iter_batches_does_not_mutate_store(
    store: TypedDuckDBStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    list(store.iter_batches(batch_size=2))
    assert store.count() == len(items)


# --- close ---


@duckdb_available
def test_close_closes_underlying_connection(store: TypedDuckDBStore) -> None:
    store.close()
    with pytest.raises(duckdb.Error):
        store._conn.execute("SELECT 1")


@duckdb_available
def test_close_is_idempotent(store: TypedDuckDBStore) -> None:
    store.close()
    store.close()  # should not raise


@duckdb_available
def test_close_returns_none(store: TypedDuckDBStore) -> None:
    assert store.close() is None


# --- context manager ---


@duckdb_available
def test_context_manager_returns_self() -> None:
    with TypedDuckDBStore(":memory:") as store:
        assert isinstance(store, TypedDuckDBStore)


@duckdb_available
def test_context_manager_closes_on_normal_exit() -> None:
    with TypedDuckDBStore(":memory:") as store:
        store.set("1", {"text": "hello"})
        assert store.count() == 1

    with pytest.raises(duckdb.Error):
        store._conn.execute("SELECT 1")


@duckdb_available
def test_context_manager_closes_on_exception() -> None:
    msg = "boom"
    with pytest.raises(ValueError, match="boom"), TypedDuckDBStore(":memory:") as store:
        raise ValueError(msg)

    with pytest.raises(duckdb.Error):
        store._conn.execute("SELECT 1")


@duckdb_available
def test_context_manager_usable_for_reads_and_writes() -> None:
    with TypedDuckDBStore(":memory:") as store:
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
    typed_duckdb_store = TypedDuckDBStore(":memory:")
    for i in range(3):
        with typed_duckdb_store as store:
            assert store.count() == 0
            store.set(str(i), {"text": "hello"})
            assert store.count() == 1


@duckdb_available
def test_context_manager_multiple_open_close_persistent(tmp_path: Path) -> None:
    typed_duckdb_store = TypedDuckDBStore(tmp_path / "data.duckdb")
    for i in range(3):
        with typed_duckdb_store as store:
            store.set(str(i), {"text": "hello"})
            assert store.count() == i + 1
