from __future__ import annotations

from coola.equality import objects_are_equal

from persista.record.store import RecordStore
from persista.record.store.factory import (
    BaseRecordStoreFactory,
    StoreRecordStoreFactory,
)
from persista.store.factory import InMemoryStoreFactory

#############################################
#     Tests for StoreRecordStoreFactory     #
#############################################


# --- Inheritance ---


def test_store_record_store_factory_is_base_record_store_factory() -> None:
    assert isinstance(StoreRecordStoreFactory(InMemoryStoreFactory()), BaseRecordStoreFactory)


# --- make_record_store ---


def test_store_record_store_factory_make_record_store_returns_record_store() -> None:
    factory = StoreRecordStoreFactory(InMemoryStoreFactory())
    assert isinstance(factory.make_record_store(), RecordStore)


def test_store_record_store_factory_make_record_store_returns_new_instance_each_call() -> None:
    factory = StoreRecordStoreFactory(InMemoryStoreFactory())
    assert factory.make_record_store() is not factory.make_record_store()


def test_store_record_store_factory_make_record_store_is_usable() -> None:
    factory = StoreRecordStoreFactory(InMemoryStoreFactory())
    store = factory.make_record_store()
    store.open()
    assert store.count() == 0
    store.close()


# --- _get_repr_kwargs ---


def test_store_record_store_factory_get_repr_kwargs() -> None:
    store_factory = InMemoryStoreFactory()
    factory = StoreRecordStoreFactory(store_factory)
    assert objects_are_equal(factory._get_repr_kwargs(), {"store_factory": store_factory})


# --- __repr__ and __str__ ---


def test_store_record_store_factory_repr_starts_with_class_name() -> None:
    factory = StoreRecordStoreFactory(InMemoryStoreFactory())
    assert repr(factory).startswith("StoreRecordStoreFactory(")


def test_store_record_store_factory_str_starts_with_class_name() -> None:
    factory = StoreRecordStoreFactory(InMemoryStoreFactory())
    assert str(factory).startswith("StoreRecordStoreFactory(")
