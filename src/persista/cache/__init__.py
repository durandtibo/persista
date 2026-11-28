r"""Contain caches."""

from __future__ import annotations

__all__ = ["MISSING", "Cache", "cached", "get_cache", "set_cache"]

from persista.cache.cache import MISSING, Cache
from persista.cache.interface import cached, get_cache, set_cache
