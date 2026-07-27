from __future__ import annotations

from coola.equality import objects_are_equal

from persista.cache import Cache
from persista.cache.factory import BaseCacheFactory, CacheFactory


def _make_cache() -> Cache:
    """Return a Cache instance for testing."""
    return Cache()


##################################
#     Tests for CacheFactory     #
##################################


# --- Inheritance ---


def test_cache_factory_is_base_cache_factory() -> None:
    assert isinstance(CacheFactory(_make_cache()), BaseCacheFactory)


# --- make_cache ---


def test_cache_factory_make_cache_returns_cache() -> None:
    factory = CacheFactory(_make_cache())
    assert isinstance(factory.make_cache(), Cache)


def test_cache_factory_make_cache_returns_same_instance() -> None:
    cache = _make_cache()
    factory = CacheFactory(cache)
    assert factory.make_cache() is cache


def test_cache_factory_make_cache_returns_same_instance_across_calls() -> None:
    cache = _make_cache()
    factory = CacheFactory(cache)
    assert factory.make_cache() is factory.make_cache()


# --- _get_repr_kwargs ---


def test_cache_factory_get_repr_kwargs() -> None:
    cache = _make_cache()
    factory = CacheFactory(cache)
    assert objects_are_equal(factory._get_repr_kwargs(), {"cache": cache})


# --- __repr__ and __str__ ---


def test_cache_factory_repr_starts_with_class_name() -> None:
    factory = CacheFactory(_make_cache())
    assert repr(factory).startswith("CacheFactory(")


def test_cache_factory_str_starts_with_class_name() -> None:
    factory = CacheFactory(_make_cache())
    assert str(factory).startswith("CacheFactory(")


def test_cache_factory_repr_contains_cache() -> None:
    factory = CacheFactory(_make_cache())
    assert "cache" in repr(factory)


def test_cache_factory_str_contains_cache() -> None:
    factory = CacheFactory(_make_cache())
    assert "cache" in str(factory)
