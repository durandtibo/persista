from __future__ import annotations

from coola.equality import objects_are_equal

from persista.store import BaseStore, InMemoryStore
from persista.store.factory import BaseStoreFactory, ConfigurableStoreFactory

IN_MEMORY_DOCUMENT_STORE_TARGET = "persista.store.InMemoryStore"


def _make_store() -> InMemoryStore:
    """Return an InMemoryStore instance for testing."""
    return InMemoryStore()


##############################################
#     Tests for ConfigurableStoreFactory     #
##############################################


# --- Inheritance ---


def test_configurable_store_factory_is_base_store_factory() -> None:
    assert isinstance(ConfigurableStoreFactory(_make_store()), BaseStoreFactory)


# --- make_store from instance ---


def test_configurable_store_factory_make_store_returns_base_store() -> None:
    factory = ConfigurableStoreFactory(_make_store())
    assert isinstance(factory.make_store(), BaseStore)


def test_configurable_store_factory_make_store_returns_same_instance() -> None:
    store = _make_store()
    factory = ConfigurableStoreFactory(store)
    assert factory.make_store() is store


# --- make_store from dict ---


def test_configurable_store_factory_make_store_from_dict_returns_base_store() -> None:
    factory = ConfigurableStoreFactory({"_target_": IN_MEMORY_DOCUMENT_STORE_TARGET})
    assert isinstance(factory.make_store(), BaseStore)


def test_configurable_store_factory_make_store_from_dict_returns_correct_type() -> None:
    factory = ConfigurableStoreFactory({"_target_": IN_MEMORY_DOCUMENT_STORE_TARGET})
    assert isinstance(factory.make_store(), InMemoryStore)


# --- _get_repr_kwargs ---


def test_configurable_store_factory_get_repr_kwargs_instance() -> None:
    store = _make_store()
    factory = ConfigurableStoreFactory(store)
    assert objects_are_equal(factory._get_repr_kwargs(), {"store": store})


def test_configurable_store_factory_get_repr_kwargs_dict_input() -> None:
    config = {"_target_": IN_MEMORY_DOCUMENT_STORE_TARGET}
    factory = ConfigurableStoreFactory(config)
    assert objects_are_equal(factory._get_repr_kwargs(), {"store": config})


# --- __repr__ and __str__ ---


def test_configurable_store_factory_repr_starts_with_class_name() -> None:
    factory = ConfigurableStoreFactory(_make_store())
    assert repr(factory).startswith("ConfigurableStoreFactory(")


def test_configurable_store_factory_str_starts_with_class_name() -> None:
    factory = ConfigurableStoreFactory(_make_store())
    assert str(factory).startswith("ConfigurableStoreFactory(")


def test_configurable_store_factory_repr_contains_store() -> None:
    factory = ConfigurableStoreFactory(_make_store())
    assert "store" in repr(factory)


def test_configurable_store_factory_str_contains_store() -> None:
    factory = ConfigurableStoreFactory(_make_store())
    assert "store" in str(factory)
