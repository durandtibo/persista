from __future__ import annotations

import pytest

from persista.cache import Cache, resolve_cache

CACHE_TARGET = "persista.cache.Cache"


def _make_cache() -> Cache:
    """Return a Cache instance for testing."""
    return Cache()


###################################
#     Tests for resolve_cache     #
###################################


# --- Pass-through ---


def test_resolve_cache_returns_cache_instance() -> None:
    assert isinstance(resolve_cache(_make_cache()), Cache)


def test_resolve_cache_passthrough_returns_same_instance() -> None:
    cache = _make_cache()
    assert resolve_cache(cache) is cache


# --- From dict ---


def test_resolve_cache_from_dict_returns_cache() -> None:
    result = resolve_cache({"_target_": CACHE_TARGET})
    assert isinstance(result, Cache)


def test_resolve_cache_from_dict_with_kwargs_returns_configured_cache() -> None:
    result = resolve_cache({"_target_": CACHE_TARGET, "default_ttl": 60.0})
    assert isinstance(result, Cache)
    assert result.default_ttl == 60.0


# --- Invalid input ---


def test_resolve_cache_invalid_type_raises_type_error() -> None:
    with pytest.raises(TypeError, match=r"Received object is not a Cache instance"):
        resolve_cache("not-a-cache")
