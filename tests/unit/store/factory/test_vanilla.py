from __future__ import annotations

from coola.equality import objects_are_equal

from persista.store import BaseStore, InMemoryStore
from persista.store.factory import BaseStoreFactory, StoreFactory


def _make_store() -> InMemoryStore:
    """Return an opened InMemoryStore instance for testing."""
    store = InMemoryStore()
    store.open()
    return store


##################################
#     Tests for StoreFactory     #
##################################


# --- Inheritance ---


def test_store_factory_is_base_store_factory() -> None:
    assert isinstance(StoreFactory(_make_store()), BaseStoreFactory)


# --- make_store ---


def test_store_factory_make_store_returns_base_store() -> None:
    factory = StoreFactory(_make_store())
    assert isinstance(factory.make_store(), BaseStore)


def test_store_factory_make_store_returns_same_instance() -> None:
    store = _make_store()
    factory = StoreFactory(store)
    assert factory.make_store() is store


def test_store_factory_make_store_returns_same_instance_across_calls() -> None:
    store = _make_store()
    factory = StoreFactory(store)
    assert factory.make_store() is factory.make_store()


# --- _get_repr_kwargs ---


def test_store_factory_get_repr_kwargs() -> None:
    store = _make_store()
    factory = StoreFactory(store)
    assert objects_are_equal(factory._get_repr_kwargs(), {"store": store})


# --- __repr__ and __str__ ---


def test_store_factory_repr_starts_with_class_name() -> None:
    factory = StoreFactory(_make_store())
    assert repr(factory).startswith("StoreFactory(")


def test_store_factory_str_starts_with_class_name() -> None:
    factory = StoreFactory(_make_store())
    assert str(factory).startswith("StoreFactory(")


def test_store_factory_repr_contains_store() -> None:
    factory = StoreFactory(_make_store())
    assert "store" in repr(factory)


def test_store_factory_str_contains_store() -> None:
    factory = StoreFactory(_make_store())
    assert "store" in str(factory)
