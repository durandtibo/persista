from __future__ import annotations

from coola.equality import objects_are_equal

from persista.store import BaseStore, InMemoryStore
from persista.store.factory import BaseStoreFactory, InMemoryStoreFactory

########################################
#     Tests for InMemoryStoreFactory     #
########################################


# --- Inheritance ---


def test_in_memory_store_factory_is_base_store_factory() -> None:
    assert isinstance(InMemoryStoreFactory(), BaseStoreFactory)


# --- make_store ---


def test_in_memory_store_factory_make_store_returns_base_store() -> None:
    factory = InMemoryStoreFactory()
    assert isinstance(factory.make_store(), BaseStore)


def test_in_memory_store_factory_make_store_returns_in_memory_store() -> None:
    factory = InMemoryStoreFactory()
    assert isinstance(factory.make_store(), InMemoryStore)


def test_in_memory_store_factory_make_store_returns_new_instance_each_call() -> None:
    factory = InMemoryStoreFactory()
    assert factory.make_store() is not factory.make_store()


# --- _get_repr_kwargs ---


def test_in_memory_store_factory_get_repr_kwargs() -> None:
    factory = InMemoryStoreFactory()
    assert objects_are_equal(factory._get_repr_kwargs(), {})


# --- __repr__ and __str__ ---


def test_in_memory_store_factory_repr_starts_with_class_name() -> None:
    factory = InMemoryStoreFactory()
    assert repr(factory).startswith("InMemoryStoreFactory(")


def test_in_memory_store_factory_str_starts_with_class_name() -> None:
    factory = InMemoryStoreFactory()
    assert str(factory).startswith("InMemoryStoreFactory(")
