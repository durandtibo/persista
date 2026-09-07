from __future__ import annotations

from collections.abc import AsyncIterator, Generator, Iterator

import pytest

from persista.record import Record
from persista.record.store import BaseRecordStore, RecordStore
from persista.store import BaseStore, InMemoryStore

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


################################
#     Tests for RecordStore     #
################################


# --- Inheritance ---


def test_record_store_is_base_record_store(store: RecordStore) -> None:
    assert isinstance(store, BaseRecordStore)


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
