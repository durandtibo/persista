from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import pytest

from persista.store import PickleSQLiteStore

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path


@pytest.fixture
def store() -> Generator[PickleSQLiteStore, None, None]:
    with PickleSQLiteStore(":memory:") as store:
        yield store


@pytest.fixture
def items() -> dict[str, dict[str, Any]]:
    return {
        "1": {"title": "Intro to Python", "author": "Alice", "category": "Programming"},
        "2": {"title": "Advanced Python", "author": "Alice", "category": "Programming"},
        "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
    }


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------


def test_init_defaults_to_in_memory() -> None:
    with PickleSQLiteStore() as store:
        assert store.count() == 0


def test_from_path(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite"
    with PickleSQLiteStore.from_path(path) as store:
        store.set("1", {"a": 1})
    with PickleSQLiteStore.from_path(path, read_only=True) as store:
        assert store.get("1") == {"a": 1}


def test_from_path_creates_missing_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dirs" / "data.sqlite"
    assert not path.parent.exists()

    with PickleSQLiteStore.from_path(path) as store:
        store.set("1", {"a": 1})
        assert path.exists()


def test_set_and_get(store: PickleSQLiteStore) -> None:
    store.set("1", {"title": "Intro to Python"})
    assert store.get("1") == {"title": "Intro to Python"}


def test_get_missing_key(store: PickleSQLiteStore) -> None:
    assert store.get("missing") is None


def test_set_many_and_get_many(store: PickleSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.get_many(["1", "3", "missing"]) == [items["1"], items["3"], None]


def test_set_overwrite(store: PickleSQLiteStore) -> None:
    store.set("1", {"a": 1})
    store.set("1", {"a": 2}, on_conflict="overwrite")
    assert store.get("1") == {"a": 2}


def test_set_raise_on_conflict(store: PickleSQLiteStore) -> None:
    store.set("1", {"a": 1})
    with pytest.raises(KeyError, match="already exist"):
        store.set("1", {"a": 2}, on_conflict="raise")
    assert store.get("1") == {"a": 1}


def test_set_skip_on_conflict(store: PickleSQLiteStore) -> None:
    store.set("1", {"a": 1})
    store.set("1", {"a": 2}, on_conflict="skip")
    assert store.get("1") == {"a": 1}


def test_set_merge_on_conflict(store: PickleSQLiteStore) -> None:
    store.set("1", {"a": 1, "tags": {"x"}})
    store.set("1", {"b": 2}, on_conflict="merge")
    assert store.get("1") == {"a": 1, "tags": {"x"}, "b": 2}


def test_count(store: PickleSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    assert store.count() == 0
    store.set_many(items)
    assert store.count() == len(items)


def test_delete(store: PickleSQLiteStore) -> None:
    store.set("1", {"a": 1})
    store.delete("1")
    assert store.get("1") is None


def test_delete_many(store: PickleSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.delete_many(["1", "2"])
    assert list(store.keys()) == ["3"]


def test_clear(store: PickleSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    store.clear()
    assert store.count() == 0


def test_contains(store: PickleSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert store.contains("1")
    assert not store.contains("missing")


def test_contains_many(store: PickleSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    found, missing = store.contains_many(["1", "missing"])
    assert found == ["1"]
    assert missing == ["missing"]


def test_keys(store: PickleSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert sorted(store.keys()) == ["1", "2", "3"]


def test_iter_batches(store: PickleSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    batches = list(store.iter_batches(batch_size=2))
    merged: dict[str, dict[str, Any]] = {}
    for batch in batches:
        merged.update(batch)
    assert merged == items


def test_close_and_closed(store: PickleSQLiteStore) -> None:
    assert not store.closed
    store.close()
    assert store.closed


# ---------------------------------------------------------------------------
# filter
# ---------------------------------------------------------------------------


def test_filter_no_filters(store: PickleSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert len(store.filter()) == len(items)


def test_filter_single_field(store: PickleSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert len(store.filter(author="Alice")) == 2


def test_filter_multiple_fields(store: PickleSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert len(store.filter(author="Alice", category="Programming")) == 2
    assert store.filter(author="Bob", category="Programming") == []


def test_filter_matches_non_json_field(store: PickleSQLiteStore) -> None:
    store.set("1", {"tags": {"python", "sqlite"}})
    store.set("2", {"tags": {"other"}})
    assert store.filter(tags={"python", "sqlite"}) == [{"tags": {"python", "sqlite"}}]


# ---------------------------------------------------------------------------
# Pickle-specific serialization behavior
# ---------------------------------------------------------------------------

# PickleSQLiteStore round-trips arbitrary Python objects that SQLiteStore
# cannot represent as JSON (tuples stay tuples, sets are supported, etc.).


def test_round_trips_tuples_and_sets(store: PickleSQLiteStore) -> None:
    store.set("1", {"coordinates": (1, 2, 3), "tags": {"python", "sqlite"}})
    assert store.get("1") == {"coordinates": (1, 2, 3), "tags": {"python", "sqlite"}}


def test_round_trips_custom_objects(store: PickleSQLiteStore) -> None:
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    store.set("1", {"created_at": now})
    assert store.get("1") == {"created_at": now}


# ---------------------------------------------------------------------------
# Empty-input edge cases
# ---------------------------------------------------------------------------


def test_set_many_empty_is_no_op(store: PickleSQLiteStore) -> None:
    store.set_many({})
    assert store.count() == 0


def test_get_many_empty_list_returns_empty_list(store: PickleSQLiteStore) -> None:
    assert store.get_many([]) == []


def test_delete_many_empty_list_is_no_op(
    store: PickleSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_many(items)
    store.delete_many([])
    assert store.count() == len(items)


def test_contains_many_empty_list_returns_empty_lists(store: PickleSQLiteStore) -> None:
    assert store.contains_many([]) == ([], [])


def test_filter_empty_store_returns_empty(store: PickleSQLiteStore) -> None:
    assert store.filter() == []
    assert store.filter(author="Alice") == []


def test_clear_empty_store_is_no_op(store: PickleSQLiteStore) -> None:
    store.clear()
    assert store.count() == 0


def test_keys_empty_store_yields_nothing(store: PickleSQLiteStore) -> None:
    assert list(store.keys()) == []


def test_iter_batches_empty_store_yields_nothing(store: PickleSQLiteStore) -> None:
    assert list(store.iter_batches()) == []


# ---------------------------------------------------------------------------
# set_batches / values (default BaseStore implementations)
# ---------------------------------------------------------------------------


def test_set_batches_writes_all_pairs(
    store: PickleSQLiteStore, items: dict[str, dict[str, Any]]
) -> None:
    store.set_batches(list(items.items()), batch_size=2)
    assert store.count() == len(items)
    assert store.get("2") == items["2"]


def test_set_batches_consumes_a_generator(store: PickleSQLiteStore) -> None:
    def gen() -> Iterator[tuple[str, dict[str, int]]]:
        for i in range(5):
            yield str(i), {"v": i}

    store.set_batches(gen(), batch_size=2)
    assert store.count() == 5


def test_values(store: PickleSQLiteStore, items: dict[str, dict[str, Any]]) -> None:
    store.set_many(items)
    assert sorted(store.values(), key=lambda v: v["title"]) == sorted(
        items.values(), key=lambda v: v["title"]
    )


# ---------------------------------------------------------------------------
# on_conflict validation
# ---------------------------------------------------------------------------


def test_set_on_conflict_invalid_raises(store: PickleSQLiteStore) -> None:
    with pytest.raises(ValueError, match="Invalid on_conflict value"):
        store.set("1", {"a": 1}, on_conflict="bogus")


# ---------------------------------------------------------------------------
# columns info
# ---------------------------------------------------------------------------


def test_get_columns_info(store: PickleSQLiteStore) -> None:
    assert store.get_columns_info() == {"key": "TEXT", "value": "BLOB"}


def test_show_columns_info_does_not_raise(store: PickleSQLiteStore) -> None:
    store.show_columns_info()


# ---------------------------------------------------------------------------
# repr/str
# ---------------------------------------------------------------------------


def test_repr(store: PickleSQLiteStore) -> None:
    assert repr(store).startswith("PickleSQLiteStore(")


def test_str(store: PickleSQLiteStore) -> None:
    assert str(store).startswith("PickleSQLiteStore(")


def test_repr_after_close_does_not_raise(store: PickleSQLiteStore) -> None:
    store.close()
    assert repr(store).startswith("PickleSQLiteStore(")


# ---------------------------------------------------------------------------
# context manager
# ---------------------------------------------------------------------------


def test_context_manager_closes_on_normal_exit() -> None:
    with PickleSQLiteStore(":memory:") as store:
        store.set("1", {"a": 1})
        assert store.count() == 1
    assert store.closed
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        store._conn.execute("SELECT 1")


def test_context_manager_closes_on_exception() -> None:
    msg = "boom"
    with pytest.raises(ValueError, match="boom"), PickleSQLiteStore(":memory:") as store:
        raise ValueError(msg)
    assert store.closed


def test_reenter_after_close_resets_in_memory_store(store: PickleSQLiteStore) -> None:
    store.set("1", {"a": 1})
    store.close()
    with store:
        assert not store.closed
        assert store.count() == 0
        store.set("1", {"a": 2})
        assert store.get("1") == {"a": 2}


def test_reenter_after_close_reopens_file_backed_store(tmp_path: Path) -> None:
    path = tmp_path / "reopen.sqlite"
    store = PickleSQLiteStore.from_path(path)
    store.set("1", {"a": 1})
    store.close()
    with store:
        assert not store.closed
        assert store.get("1") == {"a": 1}
    store.close()


# ---------------------------------------------------------------------------
# _build_filter_condition
# ---------------------------------------------------------------------------


def test_build_filter_condition_raises_not_implemented(store: PickleSQLiteStore) -> None:
    with pytest.raises(NotImplementedError, match="opaque pickled blobs"):
        store._build_filter_condition("author")


# ---------------------------------------------------------------------------
# to_uri / from_uri
# ---------------------------------------------------------------------------


def test_to_uri_from_uri_round_trips_file_data(
    tmp_path: Path, items: dict[str, dict[str, Any]]
) -> None:
    path = tmp_path / "to_uri.sqlite"
    with PickleSQLiteStore.from_path(path) as store:
        store.set_many(items)
        uri = store.to_uri()
    with PickleSQLiteStore.from_uri(uri) as reloaded:
        assert reloaded.count() == len(items)


def test_from_uri_read_only_rejects_writes(
    tmp_path: Path, items: dict[str, dict[str, Any]]
) -> None:
    path = tmp_path / "to_uri_ro.sqlite"
    with PickleSQLiteStore.from_path(path) as store:
        store.set_many(items)
        uri = store.to_uri()
    with PickleSQLiteStore.from_uri(uri, read_only=True) as reloaded:
        assert reloaded.count() == len(items)
        with pytest.raises(sqlite3.OperationalError):
            reloaded.set("new", {"a": 1})


# ---------------------------------------------------------------------------
# async
# ---------------------------------------------------------------------------


# --- async methods without aiosqlite ---


async def test_async_methods_work_without_aiosqlite(
    monkeypatch: pytest.MonkeyPatch, items: dict[str, dict[str, Any]]
) -> None:
    from persista.store import sqlite as sqlite_module

    monkeypatch.setattr(sqlite_module, "is_aiosqlite_available", lambda: False)
    with PickleSQLiteStore(":memory:") as store:
        await store.aset_many(items)
        assert await store.acount() == len(items)
        result = await store.afilter(author="Alice")
        assert len(result) == 2


# --- async context manager ---


async def test_async_context_manager_reopens_after_close() -> None:
    store = PickleSQLiteStore(":memory:")
    store.close()
    async with store:
        assert not store.closed
        await store.aset("1", {"a": 1})
        assert await store.aget("1") == {"a": 1}
    assert store.closed


async def test_async_context_manager_entering_already_open_store_is_a_noop() -> None:
    store = PickleSQLiteStore(":memory:")
    async with store:
        assert not store.closed
        await store.aset("1", {"a": 1})
        assert await store.aget("1") == {"a": 1}
    assert store.closed


# --- afilter ---


async def test_afilter_with_real_aiosqlite(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    assert len(await store.afilter()) == len(items)
    result = await store.afilter(author="Alice")
    assert len(result) == 2
    await store.aclose()


# --- aset_many ---


async def test_aset_many_internal_with_empty_items_is_a_noop() -> None:
    store = PickleSQLiteStore(":memory:")
    await store._aset_many({})
    assert await store.acount() == 0
    await store.aclose()


# ---------------------------------------------------------------------------
# async CRUD
# ---------------------------------------------------------------------------


async def test_aset_and_aget() -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset("1", {"title": "Intro to Python"})
    assert await store.aget("1") == {"title": "Intro to Python"}
    await store.aclose()


async def test_aget_missing_key() -> None:
    store = PickleSQLiteStore(":memory:")
    assert await store.aget("missing") is None
    await store.aclose()


async def test_aset_many_and_aget_many(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    assert await store.aget_many(["1", "3", "missing"]) == [items["1"], items["3"], None]
    await store.aclose()


async def test_aset_overwrite() -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset("1", {"a": 1})
    await store.aset("1", {"a": 2}, on_conflict="overwrite")
    assert await store.aget("1") == {"a": 2}
    await store.aclose()


async def test_aset_raise_on_conflict() -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset("1", {"a": 1})
    with pytest.raises(KeyError, match="already exist"):
        await store.aset("1", {"a": 2}, on_conflict="raise")
    assert await store.aget("1") == {"a": 1}
    await store.aclose()


async def test_aset_skip_on_conflict() -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset("1", {"a": 1})
    await store.aset("1", {"a": 2}, on_conflict="skip")
    assert await store.aget("1") == {"a": 1}
    await store.aclose()


async def test_aset_merge_on_conflict() -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset("1", {"a": 1, "tags": {"x"}})
    await store.aset("1", {"b": 2}, on_conflict="merge")
    assert await store.aget("1") == {"a": 1, "tags": {"x"}, "b": 2}
    await store.aclose()


async def test_acount(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    assert await store.acount() == 0
    await store.aset_many(items)
    assert await store.acount() == len(items)
    await store.aclose()


async def test_adelete() -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset("1", {"a": 1})
    await store.adelete("1")
    assert await store.aget("1") is None
    await store.aclose()


async def test_adelete_many(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    await store.adelete_many(["1", "2"])
    assert sorted([key async for key in store.akeys()]) == ["3"]
    await store.aclose()


async def test_aclear(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    await store.aclear()
    assert await store.acount() == 0
    await store.aclose()


async def test_acontains(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    assert await store.acontains("1")
    assert not await store.acontains("missing")
    await store.aclose()


async def test_acontains_many(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    found, missing = await store.acontains_many(["1", "missing"])
    assert found == ["1"]
    assert missing == ["missing"]
    await store.aclose()


async def test_akeys(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    assert sorted([key async for key in store.akeys()]) == ["1", "2", "3"]
    await store.aclose()


async def test_aiter_batches(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    merged: dict[str, dict[str, Any]] = {}
    async for batch in store.aiter_batches(batch_size=2):
        merged.update(batch)
    assert merged == items
    await store.aclose()


# ---------------------------------------------------------------------------
# async filter
# ---------------------------------------------------------------------------


async def test_afilter_no_filters(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    assert len(await store.afilter()) == len(items)
    await store.aclose()


async def test_afilter_single_field(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    assert len(await store.afilter(author="Alice")) == 2
    await store.aclose()


async def test_afilter_multiple_fields(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    assert len(await store.afilter(author="Alice", category="Programming")) == 2
    assert await store.afilter(author="Bob", category="Programming") == []
    await store.aclose()


async def test_afilter_matches_non_json_field() -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset("1", {"tags": {"python", "sqlite"}})
    await store.aset("2", {"tags": {"other"}})
    assert await store.afilter(tags={"python", "sqlite"}) == [{"tags": {"python", "sqlite"}}]
    await store.aclose()


# ---------------------------------------------------------------------------
# async pickle-specific serialization behavior
# ---------------------------------------------------------------------------


async def test_around_trips_tuples_and_sets() -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset("1", {"coordinates": (1, 2, 3), "tags": {"python", "sqlite"}})
    assert await store.aget("1") == {"coordinates": (1, 2, 3), "tags": {"python", "sqlite"}}
    await store.aclose()


async def test_around_trips_custom_objects() -> None:
    store = PickleSQLiteStore(":memory:")
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    await store.aset("1", {"created_at": now})
    assert await store.aget("1") == {"created_at": now}
    await store.aclose()


# ---------------------------------------------------------------------------
# async empty-input edge cases
# ---------------------------------------------------------------------------


async def test_aset_many_empty_is_no_op() -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many({})
    assert await store.acount() == 0
    await store.aclose()


async def test_aget_many_empty_list_returns_empty_list() -> None:
    store = PickleSQLiteStore(":memory:")
    assert await store.aget_many([]) == []
    await store.aclose()


async def test_adelete_many_empty_list_is_no_op(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    await store.adelete_many([])
    assert await store.acount() == len(items)
    await store.aclose()


async def test_acontains_many_empty_list_returns_empty_lists() -> None:
    store = PickleSQLiteStore(":memory:")
    assert await store.acontains_many([]) == ([], [])
    await store.aclose()


async def test_afilter_empty_store_returns_empty() -> None:
    store = PickleSQLiteStore(":memory:")
    assert await store.afilter() == []
    assert await store.afilter(author="Alice") == []
    await store.aclose()


async def test_aclear_empty_store_is_no_op() -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aclear()
    assert await store.acount() == 0
    await store.aclose()


async def test_akeys_empty_store_yields_nothing() -> None:
    store = PickleSQLiteStore(":memory:")
    assert [key async for key in store.akeys()] == []
    await store.aclose()


async def test_aiter_batches_empty_store_yields_nothing() -> None:
    store = PickleSQLiteStore(":memory:")
    assert [batch async for batch in store.aiter_batches()] == []
    await store.aclose()


# ---------------------------------------------------------------------------
# async set_batches / values (default BaseStore implementations)
# ---------------------------------------------------------------------------


async def test_aset_batches_writes_all_pairs(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_batches(list(items.items()), batch_size=2)
    assert await store.acount() == len(items)
    assert await store.aget("2") == items["2"]
    await store.aclose()


async def test_aset_batches_consumes_a_generator() -> None:
    store = PickleSQLiteStore(":memory:")

    def gen() -> Iterator[tuple[str, dict[str, int]]]:
        for i in range(5):
            yield str(i), {"v": i}

    await store.aset_batches(gen(), batch_size=2)
    assert await store.acount() == 5
    await store.aclose()


async def test_avalues(items: dict[str, dict[str, Any]]) -> None:
    store = PickleSQLiteStore(":memory:")
    await store.aset_many(items)
    values = [v async for v in store.avalues()]
    assert sorted(values, key=lambda v: v["title"]) == sorted(
        items.values(), key=lambda v: v["title"]
    )
    await store.aclose()


async def test_avalues_empty_store_yields_nothing() -> None:
    store = PickleSQLiteStore(":memory:")
    assert [v async for v in store.avalues()] == []
    await store.aclose()


# ---------------------------------------------------------------------------
# async on_conflict validation
# ---------------------------------------------------------------------------


async def test_aset_on_conflict_invalid_raises() -> None:
    store = PickleSQLiteStore(":memory:")
    with pytest.raises(ValueError, match="Invalid on_conflict value"):
        await store.aset("1", {"a": 1}, on_conflict="bogus")
    await store.aclose()


# ---------------------------------------------------------------------------
# async to_uri / from_uri
# ---------------------------------------------------------------------------


async def test_ato_uri_from_uri_round_trips_file_data(
    tmp_path: Path, items: dict[str, dict[str, Any]]
) -> None:
    path = tmp_path / "async_to_uri.sqlite"
    store = PickleSQLiteStore.from_path(path)
    await store.aset_many(items)
    uri = store.to_uri()
    await store.aclose()

    reloaded = PickleSQLiteStore.from_uri(uri)
    assert await reloaded.acount() == len(items)
    await reloaded.aclose()
