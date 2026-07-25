r"""Provide a configurable factory for persista ``Cache`` instances."""

from __future__ import annotations

__all__ = ["ConfigurableCacheFactory"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.cache.factory.base import BaseCacheFactory
from persista.cache.resolve import resolve_cache

if TYPE_CHECKING:
    from persista.cache.cache import Cache


class ConfigurableCacheFactory(BaseCacheFactory, MultilineDisplayMixin):
    """A concrete Cache factory that accepts either a pre-built
    :class:`~persista.cache.Cache` instance or a configuration
    dictionary.

    When a dict is provided it is resolved at each
    :meth:`make_cache` call via
    :func:`~persista.cache.resolve.resolve_cache`,
    which uses ``objectory`` to instantiate the configured class.
    When an instance is provided it is returned as-is.

    Args:
        cache: A fully configured
            :class:`~persista.cache.Cache`
            instance, or a :class:`dict` containing an ``objectory``
            factory specification (must include a ``"_target_"`` key
            pointing to the fully-qualified class name).

    Example:
        ```pycon
        >>> from persista.cache import Cache
        >>> from persista.cache.factory import ConfigurableCacheFactory
        >>> factory = ConfigurableCacheFactory(Cache())
        >>> cache = factory.make_cache()

        ```
    """

    def __init__(self, cache: Cache | dict[str, Any]) -> None:
        self._cache = cache

    def make_cache(self) -> Cache:
        return resolve_cache(self._cache)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"cache": self._cache}
