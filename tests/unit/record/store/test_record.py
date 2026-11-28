from __future__ import annotations

from collections.abc import AsyncIterator, Generator, Iterator
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from persista.record import Record
from persista.record.store import RecordStore
from persista.store import BaseStore, InMemoryStore, NullStore, PickleCodec, SQLiteStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from persista.store import OnConflict


def create_pickle_sqlite_store() -> SQLiteStore:
    r"""Return an in-memory SQLite store with the pickle codec."""
    return SQLiteStore(codec=PickleCodec())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> Generator[RecordStore, None, None]:
    with RecordStore(InMemoryStore()) as store:
        yield store


@pytest.fixture
def records() -> list[Record]:
    return [
        Record(id="1", metadata={"title": "Intro to Python", "author": "Alice"}),
        Record(id="2", metadata={"title": "Advanced Python", "author": "Alice"}),
        Record(id="3", metadata={"title": "History of Rome", "author": "Bob"}),
        Record(id="4", metadata={"title": "Cooking 101", "author": "Bob"}),
    ]


#################################
#     Tests for RecordStore     #
#################################


# --- store property ---


def test_store_property_returns_underlying_store(store: RecordStore) -> None:
    assert isinstance(store.store, BaseStore)


# --- repr/str ---


def test_repr(store: RecordStore) -> None:
    assert repr(store).startswith("RecordStore(")


def test_str(store: RecordStore) -> None:
    assert str(store).startswith("RecordStore(")


# --- set_many / get ---


def test_set_many_then_get_round_trip(store: RecordStore) -> None:
    store.set_many([Record(id="1", metadata={"author": "Alice"})])
    assert store.get("1") == Record(id="1", metadata={"author": "Alice"})


def test_set_many_overwrites_existing(store: RecordStore) -> None:
    store.set_many([Record(id="1", metadata={"author": "Alice"})])
    store.set_many([Record(id="1", metadata={"author": "Bob"})])
    assert store.get("1") == Record(id="1", metadata={"author": "Bob"})


def test_set_many_empty_is_no_op(store: RecordStore) -> None:
    store.set_many([])
    assert store.count() == 0


def test_get_missing_id_returns_none(store: RecordStore) -> None:
    assert store.get("nonexistent") is None


# --- get_many ---


def test_get_many_returns_records_in_order(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    result = store.get_many(["3", "1"])
    assert result == [records[2], records[0]]


def test_get_many_returns_none_for_missing(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    result = store.get_many(["1", "nonexistent"])
    assert result[1] is None


# --- filter ---


def test_filter_no_args_returns_all(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    assert len(store.filter()) == len(records)


def test_filter_single_field(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    result = store.filter(author="Alice")
    assert {r.id for r in result} == {"1", "2"}


def test_filter_no_match_returns_empty(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    assert store.filter(author="Charlie") == []


def test_filter_delegates_to_store(store: RecordStore) -> None:
    with patch.object(store.store, "filter", return_value={"1": {"author": "Alice"}}) as method:
        assert store.filter(author="Alice") == [Record(id="1", metadata={"author": "Alice"})]
    method.assert_called_once_with(author="Alice")


@pytest.mark.parametrize("field", ["self", "user-id", "a b"])
def test_filter_any_field_name(store: RecordStore, field: str) -> None:
    store.set(Record(id="1", metadata={field: 1}))
    assert store.filter(**{field: 1}) == [Record(id="1", metadata={field: 1})]


def test_filter_compares_values_with_json_types(store: RecordStore) -> None:
    store.set_many([Record(id="1", metadata={"v": 1}), Record(id="2", metadata={"v": True})])
    assert store.filter(v=True) == [Record(id="2", metadata={"v": True})]


# --- afilter ---


async def test_afilter_no_args_returns_all(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    assert len(await store.afilter()) == len(records)


async def test_afilter_single_field(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    result = await store.afilter(author="Alice")
    assert {r.id for r in result} == {"1", "2"}


async def test_afilter_multiple_fields(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    result = await store.afilter(author="Bob", title="Cooking 101")
    assert {r.id for r in result} == {"4"}


async def test_afilter_no_match_returns_empty(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    assert await store.afilter(author="Charlie") == []


async def test_filter_and_afilter_agree(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    sync_result = {r.id for r in store.filter(author="Bob")}
    async_result = {r.id for r in await store.afilter(author="Bob")}
    assert sync_result == async_result


async def test_afilter_delegates_to_store(store: RecordStore) -> None:
    with patch.object(store.store, "afilter", return_value={"1": {"author": "Alice"}}) as method:
        assert await store.afilter(author="Alice") == [Record(id="1", metadata={"author": "Alice"})]
    method.assert_awaited_once_with(author="Alice")


@pytest.mark.parametrize("field", ["self", "user-id", "a b"])
async def test_afilter_any_field_name(store: RecordStore, field: str) -> None:
    await store.aset(Record(id="1", metadata={field: 1}))
    assert await store.afilter(**{field: 1}) == [Record(id="1", metadata={field: 1})]


# --- filter parity with the underlying store ---


@pytest.mark.parametrize("store_cls", [InMemoryStore, SQLiteStore, create_pickle_sqlite_store])
def test_filter_matches_store_filter(
    store_cls: Callable[[], BaseStore], records: list[Record]
) -> None:
    with RecordStore(store_cls()) as store:
        store.set_many(records)
        result = store.filter(author="Bob")
        assert {record.id: dict(record.metadata) for record in result} == store.store.filter(
            author="Bob"
        )


@pytest.mark.parametrize("store_cls", [InMemoryStore, SQLiteStore, create_pickle_sqlite_store])
async def test_afilter_matches_store_afilter(
    store_cls: Callable[[], BaseStore], records: list[Record]
) -> None:
    async with RecordStore(store_cls()) as store:
        await store.aset_many(records)
        result = await store.afilter(author="Bob")
        expected = await store.store.afilter(author="Bob")
        assert {record.id: dict(record.metadata) for record in result} == expected


def test_filter_pickle_sqlite_store_returns_matching_records(records: list[Record]) -> None:
    with RecordStore(create_pickle_sqlite_store()) as store:
        store.set_many(records)
        assert store.filter(author="Bob") == [records[2], records[3]]


async def test_afilter_pickle_sqlite_store_returns_matching_records(
    records: list[Record],
) -> None:
    async with RecordStore(create_pickle_sqlite_store()) as store:
        await store.aset_many(records)
        assert await store.afilter(author="Bob") == [records[2], records[3]]


def test_filter_null_store_returns_empty(records: list[Record]) -> None:
    with RecordStore(NullStore()) as store:
        store.set_many(records)
        assert store.filter() == []


@pytest.mark.parametrize(
    "store_cls", [InMemoryStore, SQLiteStore, create_pickle_sqlite_store, NullStore]
)
def test_filter_closed_store_raises(store_cls: Callable[[], BaseStore]) -> None:
    store = RecordStore(store_cls())
    with pytest.raises(RuntimeError, match=r"not open"):
        store.filter(author="Alice")


@pytest.mark.parametrize(
    "store_cls", [InMemoryStore, SQLiteStore, create_pickle_sqlite_store, NullStore]
)
async def test_afilter_closed_store_raises(store_cls: Callable[[], BaseStore]) -> None:
    store = RecordStore(store_cls())
    with pytest.raises(RuntimeError, match=r"not open"):
        await store.afilter(author="Alice")


# --- _to_value / _from_value ---


def test_to_value_returns_metadata_dict() -> None:
    record = Record(id="1", metadata={"author": "Alice"})
    assert RecordStore._to_value(record) == {"author": "Alice"}


def test_to_value_returns_new_dict() -> None:
    record = Record(id="1", metadata={"author": "Alice"})
    RecordStore._to_value(record)["author"] = "Bob"
    assert record.metadata == {"author": "Alice"}


def test_from_value_returns_record() -> None:
    assert RecordStore._from_value("1", {"author": "Alice"}) == Record(
        id="1", metadata={"author": "Alice"}
    )


def test_from_value_does_not_share_the_value() -> None:
    value = {"author": "Alice"}
    record = RecordStore._from_value("1", value)
    value["author"] = "Bob"
    assert record.metadata == {"author": "Alice"}


# --- _to_items ---


@pytest.fixture
def duplicates() -> list[Record]:
    return [
        Record(id="1", metadata={"a": 1, "b": 1}),
        Record(id="2", metadata={"a": 2}),
        Record(id="1", metadata={"a": 3, "c": 3}),
    ]


def test_to_items_distinct_ids(records: list[Record]) -> None:
    store = RecordStore(InMemoryStore())
    assert store._to_items(records[:2], "raise") == {
        "1": {"title": "Intro to Python", "author": "Alice"},
        "2": {"title": "Advanced Python", "author": "Alice"},
    }


@pytest.mark.parametrize("on_conflict", ["overwrite", "skip", "merge", "raise"])
def test_to_items_empty(on_conflict: OnConflict) -> None:
    assert RecordStore(InMemoryStore())._to_items([], on_conflict) == {}


def test_to_items_duplicates_overwrite_keeps_last(duplicates: list[Record]) -> None:
    store = RecordStore(InMemoryStore())
    assert store._to_items(duplicates, "overwrite") == {"1": {"a": 3, "c": 3}, "2": {"a": 2}}


def test_to_items_duplicates_skip_keeps_first(duplicates: list[Record]) -> None:
    store = RecordStore(InMemoryStore())
    assert store._to_items(duplicates, "skip") == {"1": {"a": 1, "b": 1}, "2": {"a": 2}}


def test_to_items_duplicates_merge(duplicates: list[Record]) -> None:
    store = RecordStore(InMemoryStore())
    assert store._to_items(duplicates, "merge") == {
        "1": {"a": 3, "b": 1, "c": 3},
        "2": {"a": 2},
    }


def test_to_items_preserves_order_of_first_appearance(duplicates: list[Record]) -> None:
    store = RecordStore(InMemoryStore())
    assert list(store._to_items(duplicates, "overwrite")) == ["1", "2"]


def test_to_items_duplicates_raise(duplicates: list[Record]) -> None:
    with (
        RecordStore(InMemoryStore()) as store,
        pytest.raises(KeyError, match=r"appear more than once: \['1'\]"),
    ):
        store._to_items(duplicates, "raise")


def test_to_items_duplicates_raise_closed_store(duplicates: list[Record]) -> None:
    store = RecordStore(InMemoryStore())
    with pytest.raises(RuntimeError, match=r"not open"):
        store._to_items(duplicates, "raise")


def test_to_items_does_not_modify_records(duplicates: list[Record]) -> None:
    RecordStore(InMemoryStore())._to_items(duplicates, "merge")
    assert duplicates[0] == Record(id="1", metadata={"a": 1, "b": 1})


# --- set ---


def test_set_adds_record(store: RecordStore) -> None:
    store.set(Record(id="1", metadata={"author": "Alice"}))
    assert store.get("1") == Record(id="1", metadata={"author": "Alice"})


def test_set_default_overwrites(store: RecordStore) -> None:
    store.set(Record(id="1", metadata={"author": "Alice"}))
    store.set(Record(id="1", metadata={"year": 2024}))
    assert store.get("1") == Record(id="1", metadata={"year": 2024})


def test_set_skip_keeps_existing(store: RecordStore) -> None:
    store.set(Record(id="1", metadata={"author": "Alice"}))
    store.set(Record(id="1", metadata={"author": "Bob"}), on_conflict="skip")
    assert store.get("1") == Record(id="1", metadata={"author": "Alice"})


def test_set_merge(store: RecordStore) -> None:
    store.set(Record(id="1", metadata={"author": "Alice", "year": 2023}))
    store.set(Record(id="1", metadata={"year": 2024}), on_conflict="merge")
    assert store.get("1") == Record(id="1", metadata={"author": "Alice", "year": 2024})


def test_set_raise_keeps_existing(store: RecordStore) -> None:
    store.set(Record(id="1", metadata={"author": "Alice"}))
    with pytest.raises(KeyError, match=r"already exist"):
        store.set(Record(id="1", metadata={"author": "Bob"}), on_conflict="raise")
    assert store.get("1") == Record(id="1", metadata={"author": "Alice"})


def test_set_invalid_on_conflict_raises(store: RecordStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set(Record(id="1"), on_conflict="bogus")


def test_set_on_conflict_is_keyword_only(store: RecordStore) -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        store.set(Record(id="1"), "skip")


def test_set_closed_store_raises() -> None:
    with pytest.raises(RuntimeError, match=r"not open"):
        RecordStore(InMemoryStore()).set(Record(id="1"))


async def test_aset_adds_record() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset(Record(id="1", metadata={"author": "Alice"}))
        assert await store.aget("1") == Record(id="1", metadata={"author": "Alice"})


async def test_aset_default_overwrites() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset(Record(id="1", metadata={"author": "Alice"}))
        await store.aset(Record(id="1", metadata={"year": 2024}))
        assert await store.aget("1") == Record(id="1", metadata={"year": 2024})


async def test_aset_skip_keeps_existing() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset(Record(id="1", metadata={"author": "Alice"}))
        await store.aset(Record(id="1", metadata={"author": "Bob"}), on_conflict="skip")
        assert await store.aget("1") == Record(id="1", metadata={"author": "Alice"})


async def test_aset_merge() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset(Record(id="1", metadata={"author": "Alice"}))
        await store.aset(Record(id="1", metadata={"year": 2024}), on_conflict="merge")
        assert await store.aget("1") == Record(id="1", metadata={"author": "Alice", "year": 2024})


async def test_aset_raise_keeps_existing() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset(Record(id="1", metadata={"author": "Alice"}))
        with pytest.raises(KeyError, match=r"already exist"):
            await store.aset(Record(id="1", metadata={"author": "Bob"}), on_conflict="raise")
        assert await store.aget("1") == Record(id="1", metadata={"author": "Alice"})


async def test_aset_invalid_on_conflict_raises() -> None:
    async with RecordStore(InMemoryStore()) as store:
        with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
            await store.aset(Record(id="1"), on_conflict="bogus")


async def test_aset_on_conflict_is_keyword_only() -> None:
    async with RecordStore(InMemoryStore()) as store:
        with pytest.raises(TypeError, match=r"positional argument"):
            await store.aset(Record(id="1"), "skip")


async def test_aset_closed_store_raises() -> None:
    with pytest.raises(RuntimeError, match=r"not open"):
        await RecordStore(InMemoryStore()).aset(Record(id="1"))


# --- set_many (on_conflict) ---


@pytest.fixture
def filled_store(store: RecordStore) -> RecordStore:
    store.set(Record(id="1", metadata={"a": 0, "z": 0}))
    return store


@pytest.mark.parametrize(
    ("on_conflict", "expected"),
    [
        ("overwrite", {"a": 3, "c": 3}),
        ("skip", {"a": 0, "z": 0}),
        ("merge", {"a": 3, "b": 1, "c": 3, "z": 0}),
    ],
)
def test_set_many_on_conflict_existing_and_duplicate_ids(
    filled_store: RecordStore,
    duplicates: list[Record],
    on_conflict: OnConflict,
    expected: dict[str, int],
) -> None:
    filled_store.set_many(duplicates, on_conflict=on_conflict)
    assert filled_store.get_many(["1", "2"]) == [
        Record(id="1", metadata=expected),
        Record(id="2", metadata={"a": 2}),
    ]


def test_set_many_raise_writes_nothing(filled_store: RecordStore) -> None:
    with pytest.raises(KeyError, match=r"already exist"):
        filled_store.set_many([Record(id="2"), Record(id="1")], on_conflict="raise")
    assert list(filled_store.values()) == [Record(id="1", metadata={"a": 0, "z": 0})]


def test_set_many_raise_duplicate_ids_writes_nothing(
    store: RecordStore, duplicates: list[Record]
) -> None:
    with pytest.raises(KeyError, match=r"appear more than once"):
        store.set_many(duplicates, on_conflict="raise")
    assert store.count() == 0


def test_set_many_normalizes_on_conflict(store: RecordStore, duplicates: list[Record]) -> None:
    store.set_many(duplicates, on_conflict=" Skip ")
    assert store.get("1") == Record(id="1", metadata={"a": 1, "b": 1})


@pytest.mark.parametrize("records", [[], [Record(id="1")]])
def test_set_many_invalid_on_conflict_raises(store: RecordStore, records: list[Record]) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set_many(records, on_conflict="bogus")


def test_set_many_on_conflict_is_keyword_only(store: RecordStore) -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        store.set_many([], "skip")


def test_set_many_closed_store_raises() -> None:
    with pytest.raises(RuntimeError, match=r"not open"):
        RecordStore(InMemoryStore()).set_many([Record(id="1")])


@pytest.mark.parametrize(
    ("on_conflict", "expected"),
    [
        ("overwrite", {"a": 3, "c": 3}),
        ("skip", {"a": 0, "z": 0}),
        ("merge", {"a": 3, "b": 1, "c": 3, "z": 0}),
    ],
)
async def test_aset_many_on_conflict_existing_and_duplicate_ids(
    filled_store: RecordStore,
    duplicates: list[Record],
    on_conflict: OnConflict,
    expected: dict[str, int],
) -> None:
    await filled_store.aset_many(duplicates, on_conflict=on_conflict)
    assert await filled_store.aget_many(["1", "2"]) == [
        Record(id="1", metadata=expected),
        Record(id="2", metadata={"a": 2}),
    ]


async def test_aset_many_raise_writes_nothing(filled_store: RecordStore) -> None:
    with pytest.raises(KeyError, match=r"already exist"):
        await filled_store.aset_many([Record(id="2"), Record(id="1")], on_conflict="raise")
    assert await filled_store.acount() == 1


async def test_aset_many_raise_duplicate_ids_writes_nothing(
    store: RecordStore, duplicates: list[Record]
) -> None:
    with pytest.raises(KeyError, match=r"appear more than once"):
        await store.aset_many(duplicates, on_conflict="raise")
    assert await store.acount() == 0


async def test_aset_many_normalizes_on_conflict(
    store: RecordStore, duplicates: list[Record]
) -> None:
    await store.aset_many(duplicates, on_conflict=" Skip ")
    assert await store.aget("1") == Record(id="1", metadata={"a": 1, "b": 1})


@pytest.mark.parametrize("records", [[], [Record(id="1")]])
async def test_aset_many_invalid_on_conflict_raises(
    store: RecordStore, records: list[Record]
) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.aset_many(records, on_conflict="bogus")


async def test_aset_many_on_conflict_is_keyword_only(store: RecordStore) -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        await store.aset_many([], "skip")


async def test_aset_many_closed_store_raises() -> None:
    with pytest.raises(RuntimeError, match=r"not open"):
        await RecordStore(InMemoryStore()).aset_many([Record(id="1")])


# --- set_batches ---


def test_set_batches_writes_all_records(store: RecordStore, records: list[Record]) -> None:
    store.set_batches(records, batch_size=3)
    assert list(store.values()) == records


def test_set_batches_consumes_generator(store: RecordStore, records: list[Record]) -> None:
    store.set_batches(record for record in records)
    assert list(store.values()) == records


def test_set_batches_writes_mini_batches(store: RecordStore, records: list[Record]) -> None:
    with patch.object(store.store, "set_many", wraps=store.store.set_many) as set_many:
        store.set_batches(records, batch_size=3)
    assert [len(call.args[0]) for call in set_many.call_args_list] == [3, 1]


def test_set_batches_empty_is_no_op(store: RecordStore) -> None:
    store.set_batches([])
    assert store.count() == 0


@pytest.mark.parametrize(
    ("on_conflict", "expected"),
    [
        ("overwrite", {"a": 3, "c": 3}),
        ("skip", {"a": 0, "z": 0}),
        ("merge", {"a": 3, "b": 1, "c": 3, "z": 0}),
    ],
)
@pytest.mark.parametrize("batch_size", [1, 3])
def test_set_batches_on_conflict(
    filled_store: RecordStore,
    duplicates: list[Record],
    on_conflict: OnConflict,
    expected: dict[str, int],
    batch_size: int,
) -> None:
    filled_store.set_batches(duplicates, batch_size, on_conflict=on_conflict)
    assert filled_store.get("1") == Record(id="1", metadata=expected)


def test_set_batches_raise_keeps_previous_batches(filled_store: RecordStore) -> None:
    with pytest.raises(KeyError, match=r"already exist"):
        filled_store.set_batches(
            [Record(id="2"), Record(id="1"), Record(id="3")], batch_size=1, on_conflict="raise"
        )
    assert filled_store.contains_many(["1", "2", "3"]) == [True, True, False]


@pytest.mark.parametrize("batch_size", [0, -1])
def test_set_batches_invalid_batch_size_raises(store: RecordStore, batch_size: int) -> None:
    with pytest.raises(ValueError, match=r"batch_size must be a positive integer"):
        store.set_batches([], batch_size=batch_size)


def test_set_batches_invalid_on_conflict_raises(store: RecordStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        store.set_batches([Record(id="1")], on_conflict="bogus")


def test_set_batches_on_conflict_is_keyword_only(store: RecordStore) -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        store.set_batches([], 32, "skip")


def test_set_batches_closed_store_raises() -> None:
    with pytest.raises(RuntimeError, match=r"not open"):
        RecordStore(InMemoryStore()).set_batches([Record(id="1")])


async def test_aset_batches_writes_all_records(store: RecordStore, records: list[Record]) -> None:
    await store.aset_batches(records, batch_size=3)
    assert list(store.values()) == records


async def test_aset_batches_consumes_generator(store: RecordStore, records: list[Record]) -> None:
    await store.aset_batches(record for record in records)
    assert list(store.values()) == records


async def test_aset_batches_writes_mini_batches(store: RecordStore, records: list[Record]) -> None:
    with patch.object(store.store, "aset_many", wraps=store.store.aset_many) as aset_many:
        await store.aset_batches(records, batch_size=3)
    assert [len(call.args[0]) for call in aset_many.call_args_list] == [3, 1]


async def test_aset_batches_empty_is_no_op(store: RecordStore) -> None:
    await store.aset_batches([])
    assert await store.acount() == 0


@pytest.mark.parametrize(
    ("on_conflict", "expected"),
    [
        ("overwrite", {"a": 3, "c": 3}),
        ("skip", {"a": 0, "z": 0}),
        ("merge", {"a": 3, "b": 1, "c": 3, "z": 0}),
    ],
)
@pytest.mark.parametrize("batch_size", [1, 3])
async def test_aset_batches_on_conflict(
    filled_store: RecordStore,
    duplicates: list[Record],
    on_conflict: OnConflict,
    expected: dict[str, int],
    batch_size: int,
) -> None:
    await filled_store.aset_batches(duplicates, batch_size, on_conflict=on_conflict)
    assert await filled_store.aget("1") == Record(id="1", metadata=expected)


async def test_aset_batches_raise_keeps_previous_batches(filled_store: RecordStore) -> None:
    with pytest.raises(KeyError, match=r"already exist"):
        await filled_store.aset_batches(
            [Record(id="2"), Record(id="1"), Record(id="3")], batch_size=1, on_conflict="raise"
        )
    assert await filled_store.acontains_many(["1", "2", "3"]) == [True, True, False]


@pytest.mark.parametrize("batch_size", [0, -1])
async def test_aset_batches_invalid_batch_size_raises(store: RecordStore, batch_size: int) -> None:
    with pytest.raises(ValueError, match=r"batch_size must be a positive integer"):
        await store.aset_batches([], batch_size=batch_size)


async def test_aset_batches_invalid_on_conflict_raises(store: RecordStore) -> None:
    with pytest.raises(ValueError, match=r"Invalid on_conflict value"):
        await store.aset_batches([Record(id="1")], on_conflict="bogus")


async def test_aset_batches_on_conflict_is_keyword_only(store: RecordStore) -> None:
    with pytest.raises(TypeError, match=r"positional argument"):
        await store.aset_batches([], 32, "skip")


async def test_aset_batches_closed_store_raises() -> None:
    with pytest.raises(RuntimeError, match=r"not open"):
        await RecordStore(InMemoryStore()).aset_batches([Record(id="1")])


# --- delete / delete_many ---


def test_delete_removes_record(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    store.delete("1")
    assert store.get("1") is None
    assert store.count() == len(records) - 1


def test_delete_nonexistent_is_silent(store: RecordStore) -> None:
    store.delete("nonexistent")


def test_delete_many_removes_records(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    store.delete_many(["1", "2"])
    assert store.count() == len(records) - 2


# --- clear ---


def test_clear_removes_all_records(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    store.clear()
    assert store.count() == 0


# --- contains / contains_many ---


def test_contains_true_when_present(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    assert store.contains("1")


def test_contains_false_when_missing(store: RecordStore) -> None:
    assert not store.contains("1")


def test_contains_many_mixed(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    assert store.contains_many(["1", "nonexistent"]) == [True, False]


# --- keys ---


def test_keys_returns_all_ids(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    assert sorted(store.keys()) == [r.id for r in records]


# --- values ---


def test_values_returns_all_records(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    result = list(store.values())
    assert sorted(result, key=lambda r: r.id) == records


def test_values_is_lazy_iterator(store: RecordStore) -> None:
    assert isinstance(store.values(), Iterator)


# --- iter_batches ---


def test_iter_batches_yields_records(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    batches = list(store.iter_batches(batch_size=2))
    assert [len(b) for b in batches] == [2, 2]
    flat = [record for batch in batches for record in batch]
    assert sorted(flat, key=lambda r: r.id) == records


# --- count ---


def test_count_empty_store(store: RecordStore) -> None:
    assert store.count() == 0


def test_count_after_set_many(store: RecordStore, records: list[Record]) -> None:
    store.set_many(records)
    assert store.count() == len(records)


# --- open/close ---


def test_closed_true_before_open() -> None:
    store = RecordStore(InMemoryStore())
    assert store.closed


def test_closed_false_after_open() -> None:
    store = RecordStore(InMemoryStore())
    store.open()
    assert not store.closed


def test_close_returns_none(store: RecordStore) -> None:
    assert store.close() is None


# --- context manager ---


def test_context_manager_returns_self() -> None:
    with RecordStore(InMemoryStore()) as store:
        assert isinstance(store, RecordStore)


def test_context_manager_closes_on_exit() -> None:
    store = RecordStore(InMemoryStore())
    with store:
        pass
    assert store.closed


# --- async ---


async def test_aset_many_and_aget_round_trip() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset_many([Record(id="1", metadata={"author": "Alice"})])
        assert await store.aget("1") == Record(id="1", metadata={"author": "Alice"})


async def test_aget_many() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset_many(
            [
                Record(id="1", metadata={"author": "Alice"}),
                Record(id="2", metadata={"author": "Bob"}),
            ]
        )
        result = await store.aget_many(["1", "nonexistent"])
        assert result[0] == Record(id="1", metadata={"author": "Alice"})
        assert result[1] is None


async def test_afilter() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset_many(
            [
                Record(id="1", metadata={"author": "Alice"}),
                Record(id="2", metadata={"author": "Bob"}),
            ]
        )
        result = await store.afilter(author="Alice")
        assert result == [Record(id="1", metadata={"author": "Alice"})]


async def test_adelete_and_adelete_many() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset_many(
            [
                Record(id="1", metadata={"a": 1}),
                Record(id="2", metadata={"a": 2}),
                Record(id="3", metadata={"a": 3}),
            ]
        )
        await store.adelete("1")
        await store.adelete_many(["2"])
        assert await store.acount() == 1


async def test_acontains_and_acontains_many() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset_many([Record(id="1", metadata={"a": 1})])
        assert await store.acontains("1")
        assert await store.acontains_many(["1", "nonexistent"]) == [True, False]


async def test_aclear() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset_many([Record(id="1", metadata={"a": 1})])
        await store.aclear()
        assert await store.acount() == 0


async def test_akeys() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset_many([Record(id="1", metadata={}), Record(id="2", metadata={})])
        assert sorted([key async for key in store.akeys()]) == ["1", "2"]


async def test_avalues() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset_many(
            [Record(id="1", metadata={"a": 1}), Record(id="2", metadata={"a": 2})]
        )
        values = [v async for v in store.avalues()]
        assert sorted(v.id for v in values) == ["1", "2"]


async def test_aiter_batches() -> None:
    async with RecordStore(InMemoryStore()) as store:
        await store.aset_many([Record(id=str(i), metadata={"a": i}) for i in range(5)])
        batches = [batch async for batch in store.aiter_batches(batch_size=2)]
        assert [len(batch) for batch in batches] == [2, 2, 1]


def test_aiter_batches_is_async_iterator(store: RecordStore) -> None:
    assert isinstance(store.aiter_batches(), AsyncIterator)


async def test_async_context_manager_closes_on_exception() -> None:
    msg = "boom"
    store = RecordStore(InMemoryStore())
    with pytest.raises(ValueError, match="boom"):
        async with store:
            raise ValueError(msg)
    assert store.closed


# --- _get_repr_kwargs ---


def test_get_repr_kwargs(store: RecordStore) -> None:
    kwargs = store._get_repr_kwargs()
    assert set(kwargs.keys()) == {"store"}
    assert isinstance(kwargs["store"], BaseStore)
