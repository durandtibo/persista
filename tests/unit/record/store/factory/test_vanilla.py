from __future__ import annotations

from coola.equality import objects_are_equal

from persista.record.store import BaseRecordStore, InMemoryRecordStore
from persista.record.store.factory import BaseRecordStoreFactory, RecordStoreFactory


def _make_store() -> InMemoryRecordStore:
    """Return an opened InMemoryRecordStore instance for testing."""
    store = InMemoryRecordStore()
    store.open()
    return store


########################################
#     Tests for RecordStoreFactory     #
########################################


# --- Inheritance ---


def test_record_store_factory_is_base_record_store_factory() -> None:
    assert isinstance(RecordStoreFactory(_make_store()), BaseRecordStoreFactory)


# --- make_record_store ---


def test_record_store_factory_make_record_store_returns_base_record_store() -> None:
    factory = RecordStoreFactory(_make_store())
    assert isinstance(factory.make_record_store(), BaseRecordStore)


def test_record_store_factory_make_record_store_returns_same_instance() -> None:
    store = _make_store()
    factory = RecordStoreFactory(store)
    assert factory.make_record_store() is store


def test_record_store_factory_make_record_store_returns_same_instance_across_calls() -> None:
    store = _make_store()
    factory = RecordStoreFactory(store)
    assert factory.make_record_store() is factory.make_record_store()


# --- _get_repr_kwargs ---


def test_record_store_factory_get_repr_kwargs() -> None:
    store = _make_store()
    factory = RecordStoreFactory(store)
    assert objects_are_equal(factory._get_repr_kwargs(), {"record_store": store})


# --- __repr__ and __str__ ---


def test_record_store_factory_repr_starts_with_class_name() -> None:
    factory = RecordStoreFactory(_make_store())
    assert repr(factory).startswith("RecordStoreFactory(")


def test_record_store_factory_str_starts_with_class_name() -> None:
    factory = RecordStoreFactory(_make_store())
    assert str(factory).startswith("RecordStoreFactory(")


def test_record_store_factory_repr_contains_record_store() -> None:
    factory = RecordStoreFactory(_make_store())
    assert "record_store" in repr(factory)


def test_record_store_factory_str_contains_record_store() -> None:
    factory = RecordStoreFactory(_make_store())
    assert "record_store" in str(factory)
