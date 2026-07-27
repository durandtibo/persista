from __future__ import annotations

from coola.equality import objects_are_equal

from persista.store import BaseStore, NullStore
from persista.store.factory import BaseStoreFactory, NullStoreFactory

##################################
#     Tests for NullStoreFactory     #
##################################


# --- Inheritance ---


def test_null_store_factory_is_base_store_factory() -> None:
    assert isinstance(NullStoreFactory(), BaseStoreFactory)


# --- make_store ---


def test_null_store_factory_make_store_returns_base_store() -> None:
    factory = NullStoreFactory()
    assert isinstance(factory.make_store(), BaseStore)


def test_null_store_factory_make_store_returns_null_store() -> None:
    factory = NullStoreFactory()
    assert isinstance(factory.make_store(), NullStore)


def test_null_store_factory_make_store_returns_new_instance_each_call() -> None:
    factory = NullStoreFactory()
    assert factory.make_store() is not factory.make_store()


# --- _get_repr_kwargs ---


def test_null_store_factory_get_repr_kwargs() -> None:
    factory = NullStoreFactory()
    assert objects_are_equal(factory._get_repr_kwargs(), {})


# --- __repr__ and __str__ ---


def test_null_store_factory_repr_starts_with_class_name() -> None:
    factory = NullStoreFactory()
    assert repr(factory).startswith("NullStoreFactory(")


def test_null_store_factory_str_starts_with_class_name() -> None:
    factory = NullStoreFactory()
    assert str(factory).startswith("NullStoreFactory(")
