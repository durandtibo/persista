from __future__ import annotations

import pytest
from coola.equality import objects_are_equal

from persista.cache import Cache
from persista.cache.factory import BaseCacheFactory, StoreCacheFactory
from persista.store import InMemoryStore
from persista.store.factory import StoreFactory

#######################################
#     Tests for StoreCacheFactory     #
#######################################


# --- Inheritance ---


def test_store_cache_factory_is_base_cache_factory() -> None:
    assert isinstance(StoreCacheFactory(StoreFactory(InMemoryStore())), BaseCacheFactory)


# --- make_cache ---


def test_store_cache_factory_make_cache_returns_cache() -> None:
    factory = StoreCacheFactory(StoreFactory(InMemoryStore()))
    assert isinstance(factory.make_cache(), Cache)


def test_store_cache_factory_make_cache_uses_store_from_store_factory() -> None:
    store = InMemoryStore()
    factory = StoreCacheFactory(StoreFactory(store))
    cache = factory.make_cache()
    cache.set("key", "value")
    assert store.get("key")["value"] == "value"


def test_store_cache_factory_make_cache_returns_new_cache_across_calls() -> None:
    factory = StoreCacheFactory(StoreFactory(InMemoryStore()))
    assert factory.make_cache() is not factory.make_cache()


def test_store_cache_factory_make_cache_forwards_default_ttl() -> None:
    factory = StoreCacheFactory(StoreFactory(InMemoryStore()), default_ttl=60)
    assert factory.make_cache().default_ttl == 60


def test_store_cache_factory_make_cache_forwards_ignore_none() -> None:
    factory = StoreCacheFactory(StoreFactory(InMemoryStore()), ignore_none=True)
    cache = factory.make_cache()
    cache.set("key", None)
    assert cache.get("key") is None
    assert not cache.contains("key")


def test_store_cache_factory_make_cache_raises_error_if_default_ttl_is_negative() -> None:
    factory = StoreCacheFactory(StoreFactory(InMemoryStore()), default_ttl=-1)
    with pytest.raises(ValueError, match="default_ttl must be non-negative"):
        factory.make_cache()


# --- _get_repr_kwargs ---


def test_store_cache_factory_get_repr_kwargs() -> None:
    store_factory = StoreFactory(InMemoryStore())
    factory = StoreCacheFactory(store_factory, default_ttl=60, ignore_none=True)
    assert objects_are_equal(
        factory._get_repr_kwargs(),
        {"store_factory": store_factory, "default_ttl": 60, "ignore_none": True},
    )


# --- __repr__ and __str__ ---


def test_store_cache_factory_repr_starts_with_class_name() -> None:
    factory = StoreCacheFactory(StoreFactory(InMemoryStore()))
    assert repr(factory).startswith("StoreCacheFactory(")


def test_store_cache_factory_str_starts_with_class_name() -> None:
    factory = StoreCacheFactory(StoreFactory(InMemoryStore()))
    assert str(factory).startswith("StoreCacheFactory(")


def test_store_cache_factory_repr_contains_store_factory() -> None:
    factory = StoreCacheFactory(StoreFactory(InMemoryStore()))
    assert "store_factory" in repr(factory)


def test_store_cache_factory_str_contains_store_factory() -> None:
    factory = StoreCacheFactory(StoreFactory(InMemoryStore()))
    assert "store_factory" in str(factory)
