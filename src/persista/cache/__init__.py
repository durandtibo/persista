r"""Contain caches."""

from __future__ import annotations

__all__ = [
    "AsyncTTLCache",
    "Cache",
    "async_cached",
    "cached",
    "get_async_ttl_cache",
    "get_cache",
    "make_json_key",
    "make_key",
    "make_pickle_key",
    "set_async_ttl_cache",
    "set_cache",
]

from persista.cache.async_ttl import AsyncTTLCache
from persista.cache.cache import Cache
from persista.cache.interface import (
    async_cached,
    cached,
    get_async_ttl_cache,
    get_cache,
    set_async_ttl_cache,
    set_cache,
)
from persista.cache.utils import make_json_key, make_key, make_pickle_key
