r"""Contain factories for caches."""

from __future__ import annotations

__all__ = [
    "BaseCacheFactory",
    "CacheFactory",
    "ConfigurableCacheFactory",
    "StoreCacheFactory",
]

from persista.cache.factory.base import BaseCacheFactory
from persista.cache.factory.configurable import ConfigurableCacheFactory
from persista.cache.factory.store import StoreCacheFactory
from persista.cache.factory.vanilla import CacheFactory
