from __future__ import annotations

from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import JsonFileStore, PickleFileStore

if TYPE_CHECKING:
    from pathlib import Path

    from persista.store import BaseFileStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=[JsonFileStore, PickleFileStore], ids=["json", "pickle"])
def store_cls(request: pytest.FixtureRequest) -> type[BaseFileStore]:
    return request.param


@pytest.fixture
def store(tmp_path: Path, store_cls: type[BaseFileStore]) -> Generator[BaseFileStore, None, None]:
    with store_cls(tmp_path / "db") as store:
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


###################################
#     Tests for file stores      #
###################################


# --- constructor ---


def test_init_defaults(store: BaseFileStore) -> None:
    assert store.count() == 0


def test_init_creates_missing_directory(tmp_path: Path, store_cls: type[BaseFileStore]) -> None:
    path = tmp_path / "nested" / "db"
    with store_cls(path) as store:
        assert store.count() == 0
    assert path.is_dir()


def test_init_existing_directory_is_reused(tmp_path: Path, store_cls: type[BaseFileStore]) -> None:
    path = tmp_path / "db"
    path.mkdir()
    with store_cls(path) as store:
        assert store.count() == 0


def test_init_path_that_is_a_file_raises(tmp_path: Path, store_cls: type[BaseFileStore]) -> None:
    path = tmp_path / "db"
    path.write_text("not a directory")
    with pytest.raises(NotADirectoryError, match="path must be a directory"):
        store_cls(path)


# --- path ---


def test_path_returns_the_store_directory(tmp_path: Path, store_cls: type[BaseFileStore]) -> None:
    path = tmp_path / "db"
    with store_cls(path) as store:
        assert store.path == path


# --- repr/str ---


def test_repr(store: BaseFileStore) -> None:
    assert repr(store).startswith(f"{type(store).__name__}(")


def test_str(store: BaseFileStore) -> None:
    assert str(store).startswith(f"{type(store).__name__}(")


def test_repr_after_close_does_not_raise(store: BaseFileStore) -> None:
    store.close()
    assert repr(store).startswith(f"{type(store).__name__}(")


# --- set ---


def test_set_increases_count(store: BaseFileStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.count() == 1


def test_set_stores_value(store: BaseFileStore) -> None:
    store.set("1", {"text": "hello"})
    assert store.get("1") == {"text": "hello"}


def test_set_default_overwrites_existing(store: BaseFileStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


def test_set_on_conflict_raise(store: BaseFileStore) -> None:
    store.set("1", {"text": "original"})
    with pytest.raises(KeyError, match=r"1"):
        store.set("1", {"text": "updated"}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}


def test_set_on_conflict_skip(store: BaseFileStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}


def test_set_on_conflict_overwrite(store: BaseFileStore) -> None:
    store.set("1", {"text": "original"})
    store.set("1", {"text": "updated"}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}


def test_set_on_conflict_merge(store: BaseFileStore) -> None:
    store.set("1", {"text": "original", "author": "Alice"})
    store.set("1", {"text": "updated"}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


def test_set_on_conflict_new_key_is_unaffected(store: BaseFileStore) -> None:
    store.set("1", {"text": "hello"}, on_conflict="raise")
    assert store.get("1") == {"text": "hello"}


def test_set_on_conflict_invalid_raises(store: BaseFileStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set("1", {"text": "hello"}, on_conflict="bogus")


def test_set_key_with_special_characters(store: BaseFileStore) -> None:
    key = "weird/key with spaces?and&stuff"
    store.set(key, {"text": "hello"})
    assert store.get(key) == {"text": "hello"}
    assert list(store.keys()) == [key]


# --- set_many ---


def test_set_many_increases_count(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


def test_set_many_empty_is_no_op(store: BaseFileStore) -> None:
    store.set_many({})
    assert store.count() == 0


def test_set_many_default_overwrites_existing(store: BaseFileStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}})
    assert store.count() == 1
    assert store.get("1") == {"text": "updated"}


def test_set_many_on_conflict_raise(store: BaseFileStore) -> None:
    store.set_many({"1": {"text": "original"}, "2": {"text": "other"}})
    with pytest.raises(KeyError, match=r"1"):
        store.set_many({"1": {"text": "updated"}, "3": {"text": "new"}}, on_conflict="raise")
    assert store.get("1") == {"text": "original"}
    assert store.get("3") is None


def test_set_many_on_conflict_skip(store: BaseFileStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


def test_set_many_on_conflict_overwrite(store: BaseFileStore) -> None:
    store.set_many({"1": {"text": "original"}})
    store.set_many({"1": {"text": "updated"}, "2": {"text": "new"}}, on_conflict="overwrite")
    assert store.get("1") == {"text": "updated"}
    assert store.get("2") == {"text": "new"}


def test_set_many_on_conflict_merge(store: BaseFileStore) -> None:
    store.set_many({"1": {"text": "original", "author": "Alice"}})
    store.set_many({"1": {"text": "updated"}}, on_conflict="merge")
    assert store.get("1") == {"text": "updated", "author": "Alice"}


def test_set_many_on_conflict_invalid_raises(store: BaseFileStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set_many({"1": {"text": "hello"}}, on_conflict="bogus")


# --- set_batches ---


def test_set_batches_empty_is_no_op(store: BaseFileStore) -> None:
    store.set_batches([])
    assert store.count() == 0


def test_set_batches_writes_all_pairs(store: BaseFileStore) -> None:
    store.set_batches([("1", {"v": 1}), ("2", {"v": 2}), ("3", {"v": 3})], batch_size=2)
    assert store.count() == 3
    assert store.get("2") == {"v": 2}


def test_set_batches_consumes_a_generator(store: BaseFileStore) -> None:
    def gen() -> Iterator[tuple[str, dict[str, int]]]:
        for i in range(5):
            yield str(i), {"v": i}

    store.set_batches(gen(), batch_size=2)
    assert store.count() == 5


def test_set_batches_on_conflict_skip(store: BaseFileStore) -> None:
    store.set("1", {"text": "original"})
    store.set_batches([("1", {"text": "updated"}), ("2", {"text": "new"})], on_conflict="skip")
    assert store.get("1") == {"text": "original"}
    assert store.get("2") == {"text": "new"}


# --- count ---


def test_count_empty_store(store: BaseFileStore) -> None:
    assert store.count() == 0


def test_count_after_set_many(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.count() == len(items)


# --- get ---


def test_get_existing_value(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.get("1") == items["1"]


def test_get_missing_key_returns_none(store: BaseFileStore) -> None:
    assert store.get("nonexistent") is None


# --- get_many ---


def test_get_many_returns_correct_length(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert len(store.get_many(["1", "2", "99"])) == 3


def test_get_many_returns_none_for_missing(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.get_many(["1", "99", "2"])
    assert result[1] is None


def test_get_many_preserves_order(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.get_many(["3", "1", "2"])
    assert result == [items["3"], items["1"], items["2"]]


def test_get_many_empty_list_returns_empty_list(store: BaseFileStore) -> None:
    assert store.get_many([]) == []


# --- filter ---


def test_filter_no_args_returns_all(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert len(store.filter()) == len(items)


def test_filter_single_field(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice")
    assert all(r["author"] == "Alice" for r in result)
    assert len(result) == 2


def test_filter_multiple_fields(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(author="Alice", category="Programming")
    assert len(result) == 2


def test_filter_no_match_returns_empty(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.filter(author="Charlie") == []


def test_filter_preserves_full_value(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.filter(author="Bob", category="History")
    expected = [v for v in items.values() if v["author"] == "Bob"]
    assert sorted(result, key=lambda v: v["title"]) == sorted(expected, key=lambda v: v["title"])


def test_filter_empty_store_returns_empty(store: BaseFileStore) -> None:
    assert store.filter(author="Alice") == []


def test_filter_integer_field_value(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = store.filter(year=2022)
    assert len(result) == 1
    assert result[0]["title"] == "Intro to Python"


def test_filter_integer_value_no_match_returns_empty(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.filter(year=9999) == []


# --- delete ---


def test_delete_removes_value(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete("1")
    assert store.count() == len(items) - 1
    assert store.get("1") is None


def test_delete_nonexistent_is_silent(store: BaseFileStore) -> None:
    store.delete("nonexistent")


# --- delete_many ---


def test_delete_many_removes_values(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.count() == len(items) - 2
    assert store.get("1") is None
    assert store.get("3") is None


def test_delete_many_preserves_other_values(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many(["1", "3"])
    assert store.get("2") is not None
    assert store.get("4") is not None


def test_delete_many_empty_list_is_no_op(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many([])
    assert store.count() == len(items)


def test_delete_many_nonexistent_keys_are_silent(store: BaseFileStore) -> None:
    store.delete_many(["99", "100"])


def test_delete_many_single_key(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["2"])
    assert store.count() == len(items) - 1
    assert store.get("2") is None


# --- clear ---


def test_clear_removes_all_values(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.clear()
    assert store.count() == 0
    assert list(store.keys()) == []


def test_clear_empty_store_is_no_op(store: BaseFileStore) -> None:
    store.clear()
    assert store.count() == 0


def test_clear_returns_none(store: BaseFileStore) -> None:
    assert store.clear() is None


def test_clear_then_set_works(store: BaseFileStore) -> None:
    store.set("1", {"text": "hello"})
    store.clear()
    store.set("2", {"text": "world"})
    assert store.count() == 1
    assert store.get("2") == {"text": "world"}


# --- contains ---


def test_contains_true_when_key_present(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.contains("1") is True


def test_contains_false_when_key_missing(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    assert store.contains("99") is False


def test_contains_false_when_store_empty(store: BaseFileStore) -> None:
    assert store.contains("1") is False


# --- contains_many ---


def test_contains_many_all_found(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "2", "3", "4"])
    assert sorted(found) == ["1", "2", "3", "4"]
    assert missing == []


def test_contains_many_all_missing(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["99", "100"])
    assert found == []
    assert sorted(missing) == ["100", "99"]


def test_contains_many_mixed(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "99", "3", "42"])
    assert sorted(found) == ["1", "3"]
    assert sorted(missing) == ["42", "99"]


def test_contains_many_empty_input_returns_empty_lists(store: BaseFileStore) -> None:
    found, missing = store.contains_many([])
    assert found == []
    assert missing == []


def test_contains_many_empty_store_returns_all_missing(store: BaseFileStore) -> None:
    found, missing = store.contains_many(["1", "2"])
    assert found == []
    assert sorted(missing) == ["1", "2"]


def test_contains_many_returns_tuple_of_two_lists(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result = store.contains_many(["1", "99"])
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], list)
    assert isinstance(result[1], list)


# --- keys ---


def test_keys_empty_store_yields_nothing(store: BaseFileStore) -> None:
    assert list(store.keys()) == []


def test_keys_returns_all_keys(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert sorted(store.keys()) == sorted(items.keys())


# --- values ---


def test_values_empty_store_yields_nothing(store: BaseFileStore) -> None:
    assert list(store.values()) == []


def test_values_returns_all_values(store: BaseFileStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    result = list(store.values())
    assert len(result) == len(items)
    assert {v["title"] for v in result} == {v["title"] for v in items.values()}


def test_values_is_lazy_generator(store: BaseFileStore) -> None:
    assert isinstance(store.values(), Iterator)


# --- iter_batches ---


def test_iter_batches_empty_store_yields_nothing(store: BaseFileStore) -> None:
    assert list(store.iter_batches()) == []


def test_iter_batches_returns_generator(store: BaseFileStore) -> None:
    result = store.iter_batches()
    assert isinstance(result, Iterator)


def test_iter_batches_default_batch_size(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches())
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


def test_iter_batches_yields_correct_batch_sizes(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert sorted(len(b) for b in batches) == [2, 2]


def test_iter_batches_batch_size_larger_than_store(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=100))
    assert len(batches) == 1
    assert len(batches[0]) == len(items)


def test_iter_batches_returns_all_key_value_pairs(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    result: dict[str, dict[str, Any]] = {}
    for batch in store.iter_batches(batch_size=2):
        result.update(batch)
    assert result == items


def test_iter_batches_batches_are_dicts(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    assert all(isinstance(batch, dict) for batch in batches)


def test_iter_batches_zero_batch_size_raises(store: BaseFileStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=0))


def test_iter_batches_negative_batch_size_raises(store: BaseFileStore) -> None:
    with pytest.raises(ValueError, match="batch_size must be a positive integer"):
        list(store.iter_batches(batch_size=-1))


def test_iter_batches_error_raised_before_any_query(store: BaseFileStore) -> None:
    gen = store.iter_batches(batch_size=0)
    with pytest.raises(ValueError, match="batch_size"):
        next(gen)


def test_iter_batches_does_not_mutate_store(
    store: BaseFileStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    list(store.iter_batches(batch_size=2))
    assert store.count() == len(items)


# --- close ---


def test_close_is_idempotent(store: BaseFileStore) -> None:
    store.close()
    store.close()  # should not raise


def test_close_returns_none(store: BaseFileStore) -> None:
    assert store.close() is None


def test_close_does_not_delete_files(store: BaseFileStore) -> None:
    store.set("1", {"text": "hello"})
    store.close()
    assert store.count() == 1


# --- closed ---


def test_closed_false_before_close(store: BaseFileStore) -> None:
    assert not store.closed


def test_closed_true_after_close(store: BaseFileStore) -> None:
    store.close()
    assert store.closed


# --- context manager ---


def test_context_manager_returns_self(store: BaseFileStore, store_cls: type[BaseFileStore]) -> None:
    assert isinstance(store, store_cls)


def test_context_manager_closes_on_normal_exit(
    tmp_path: Path, store_cls: type[BaseFileStore]
) -> None:
    with store_cls(tmp_path / "db") as store:
        store.set("1", {"text": "hello"})
        assert store.count() == 1
    assert store.closed


def test_context_manager_closes_on_exception(
    tmp_path: Path, store_cls: type[BaseFileStore]
) -> None:
    msg = "boom"
    with pytest.raises(ValueError, match="boom"), store_cls(tmp_path / "db") as store:
        raise ValueError(msg)
    assert store.closed


def test_context_manager_usable_for_reads_and_writes(store: BaseFileStore) -> None:
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


def test_context_manager_multiple_open_close_same_path(
    tmp_path: Path, store_cls: type[BaseFileStore]
) -> None:
    """Reopening after close reuses the same directory on disk, so
    previously written data is still there."""
    file_store = store_cls(tmp_path / "db")
    for i in range(3):
        with file_store as store:
            store.set(str(i), {"text": "hello"})
            assert store.count() == i + 1


#########################################################
#     PickleFileStore-specific serialization behavior     #
#########################################################

# The JSON and pickle variants share the exact same behavior for
# JSON-compatible values (covered by every test above, run against
# both `store_cls` params). They differ only in what they can encode:
# PickleFileStore round-trips arbitrary Python objects, JsonFileStore
# silently normalizes them to their closest JSON equivalent.


def test_pickle_store_round_trips_tuples_and_sets(tmp_path: Path) -> None:
    with PickleFileStore(tmp_path / "db") as store:
        store.set("1", {"coordinates": (1, 2, 3), "tags": {"python", "file"}})
        assert store.get("1") == {"coordinates": (1, 2, 3), "tags": {"python", "file"}}


def test_json_store_normalizes_tuples_and_sets_are_unsupported(tmp_path: Path) -> None:
    with JsonFileStore(tmp_path / "db") as store:
        store.set("1", {"coordinates": (1, 2, 3)})
        # JSON has no tuple type, so it comes back as a list.
        assert store.get("1") == {"coordinates": [1, 2, 3]}
        with pytest.raises(TypeError, match="not JSON serializable"):
            store.set("2", {"tags": {"python", "file"}})


def test_json_store_files_are_readable(tmp_path: Path) -> None:
    with JsonFileStore(tmp_path / "db") as store:
        store.set("1", {"text": "hello"})
    files = list((tmp_path / "db").iterdir())
    assert len(files) == 1
    assert files[0].suffix == ".json"
