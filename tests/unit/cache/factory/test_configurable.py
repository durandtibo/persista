from __future__ import annotations

from coola.equality import objects_are_equal

from persista.cache import Cache
from persista.cache.factory import BaseCacheFactory, ConfigurableCacheFactory

CACHE_TARGET = "persista.cache.Cache"


def _make_cache() -> Cache:
    """Return a Cache instance for testing."""
    return Cache()


##############################################
#     Tests for ConfigurableCacheFactory     #
##############################################


# --- Inheritance ---


def test_configurable_cache_factory_is_base_cache_factory() -> None:
    assert isinstance(ConfigurableCacheFactory(_make_cache()), BaseCacheFactory)


# --- make_cache from instance ---


def test_configurable_cache_factory_make_cache_returns_cache() -> None:
    factory = ConfigurableCacheFactory(_make_cache())
    assert isinstance(factory.make_cache(), Cache)


def test_configurable_cache_factory_make_cache_returns_same_instance() -> None:
    cache = _make_cache()
    factory = ConfigurableCacheFactory(cache)
    assert factory.make_cache() is cache


# --- make_cache from dict ---


def test_configurable_cache_factory_make_cache_from_dict_returns_cache() -> None:
    factory = ConfigurableCacheFactory({"_target_": CACHE_TARGET})
    assert isinstance(factory.make_cache(), Cache)


def test_configurable_cache_factory_make_cache_from_dict_returns_correct_type() -> None:
    factory = ConfigurableCacheFactory({"_target_": CACHE_TARGET})
    assert isinstance(factory.make_cache(), Cache)


# --- _get_repr_kwargs ---


def test_configurable_cache_factory_get_repr_kwargs_instance() -> None:
    cache = _make_cache()
    factory = ConfigurableCacheFactory(cache)
    assert objects_are_equal(factory._get_repr_kwargs(), {"cache": cache})


def test_configurable_cache_factory_get_repr_kwargs_dict_input() -> None:
    config = {"_target_": CACHE_TARGET}
    factory = ConfigurableCacheFactory(config)
    assert objects_are_equal(factory._get_repr_kwargs(), {"cache": config})


# --- __repr__ and __str__ ---


def test_configurable_cache_factory_repr_starts_with_class_name() -> None:
    factory = ConfigurableCacheFactory(_make_cache())
    assert repr(factory).startswith("ConfigurableCacheFactory(")


def test_configurable_cache_factory_str_starts_with_class_name() -> None:
    factory = ConfigurableCacheFactory(_make_cache())
    assert str(factory).startswith("ConfigurableCacheFactory(")


def test_configurable_cache_factory_repr_contains_cache() -> None:
    factory = ConfigurableCacheFactory(_make_cache())
    assert "cache" in repr(factory)


def test_configurable_cache_factory_str_contains_cache() -> None:
    factory = ConfigurableCacheFactory(_make_cache())
    assert "cache" in str(factory)
