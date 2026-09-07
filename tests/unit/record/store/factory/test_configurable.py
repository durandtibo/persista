from __future__ import annotations

from coola.equality import objects_are_equal

from persista.record.store import BaseRecordStore, InMemoryRecordStore
from persista.record.store.factory import (
    BaseRecordStoreFactory,
    ConfigurableRecordStoreFactory,
)

IN_MEMORY_RECORD_STORE_TARGET = "persista.record.store.InMemoryRecordStore"


def _make_store() -> InMemoryRecordStore:
    """Return an opened InMemoryRecordStore instance for testing."""
    store = InMemoryRecordStore()
    store.open()
    return store


######################################################
#     Tests for ConfigurableRecordStoreFactory     #
######################################################


# --- Inheritance ---


def test_configurable_record_store_factory_is_base_record_store_factory() -> None:
    assert isinstance(ConfigurableRecordStoreFactory(_make_store()), BaseRecordStoreFactory)


# --- make_record_store from instance ---


def test_configurable_record_store_factory_make_record_store_returns_base_record_store() -> None:
    factory = ConfigurableRecordStoreFactory(_make_store())
    assert isinstance(factory.make_record_store(), BaseRecordStore)


def test_configurable_record_store_factory_make_record_store_returns_same_instance() -> None:
    store = _make_store()
    factory = ConfigurableRecordStoreFactory(store)
    assert factory.make_record_store() is store


# --- make_record_store from dict ---


def test_configurable_record_store_factory_make_record_store_from_dict_returns_base_record_store() -> (
    None
):
    factory = ConfigurableRecordStoreFactory({"_target_": IN_MEMORY_RECORD_STORE_TARGET})
    assert isinstance(factory.make_record_store(), BaseRecordStore)


def test_configurable_record_store_factory_make_record_store_from_dict_returns_correct_type() -> (
    None
):
    factory = ConfigurableRecordStoreFactory({"_target_": IN_MEMORY_RECORD_STORE_TARGET})
    assert isinstance(factory.make_record_store(), InMemoryRecordStore)


# --- _get_repr_kwargs ---


def test_configurable_record_store_factory_get_repr_kwargs_instance() -> None:
    store = _make_store()
    factory = ConfigurableRecordStoreFactory(store)
    assert objects_are_equal(factory._get_repr_kwargs(), {"record_store": store})


def test_configurable_record_store_factory_get_repr_kwargs_dict_input() -> None:
    config = {"_target_": IN_MEMORY_RECORD_STORE_TARGET}
    factory = ConfigurableRecordStoreFactory(config)
    assert objects_are_equal(factory._get_repr_kwargs(), {"record_store": config})


# --- __repr__ and __str__ ---


def test_configurable_record_store_factory_repr_starts_with_class_name() -> None:
    factory = ConfigurableRecordStoreFactory(_make_store())
    assert repr(factory).startswith("ConfigurableRecordStoreFactory(")


def test_configurable_record_store_factory_str_starts_with_class_name() -> None:
    factory = ConfigurableRecordStoreFactory(_make_store())
    assert str(factory).startswith("ConfigurableRecordStoreFactory(")
