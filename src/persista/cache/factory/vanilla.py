r"""Provide a concrete default factory for persista ``Cache``
instances."""

from __future__ import annotations

__all__ = ["CacheFactory"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.cache.factory.base import BaseCacheFactory

if TYPE_CHECKING:
    from persista.cache.cache import Cache


class CacheFactory(BaseCacheFactory, MultilineDisplayMixin):
    """A concrete Cache factory that wraps a pre-built
    :class:`~persista.cache.Cache` instance.

    Use this when the cache is already instantiated and you simply
    want to wrap it in the :class:`~BaseCacheFactory` interface —
    for example, when injecting a fixed cache into a component that
    expects a factory.

    Args:
        cache: A fully configured
            :class:`~persista.cache.Cache`
            instance to return from :meth:`make_cache`.

    Example:
        ```pycon
        >>> from persista.cache import Cache
        >>> from persista.cache.factory import CacheFactory
        >>> factory = CacheFactory(Cache())
        >>> cache = factory.make_cache()

        ```
    """

    def __init__(self, cache: Cache) -> None:
        self._cache = cache

    def make_cache(self) -> Cache:
        return self._cache

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"cache": self._cache}
