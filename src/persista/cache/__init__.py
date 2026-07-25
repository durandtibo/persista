r"""Contain caches."""

from __future__ import annotations

__all__ = [
    "Cache",
    "async_cached",
    "cached",
    "get_cache",
    "make_json_key",
    "make_key",
    "make_pickle_key",
    "set_cache",
]

from persista.cache.cache import Cache
from persista.cache.interface import async_cached, cached, get_cache, set_cache
from persista.cache.utils import make_json_key, make_key, make_pickle_key
