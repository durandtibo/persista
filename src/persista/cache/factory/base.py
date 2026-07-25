r"""Provide the base factory interface for creating persista ``Cache``
instances."""

from __future__ import annotations

__all__ = ["BaseCacheFactory"]

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from persista.cache.cache import Cache


class BaseCacheFactory(ABC):
    """Abstract base class for :class:`~persista.cache.Cache` factories.

    Subclasses implement :meth:`make_cache` to instantiate
    and return a configured
    :class:`~persista.cache.Cache` object.
    This pattern decouples cache creation from the rest of the
    codebase, making it easy to swap how a cache is built (e.g. a
    shared instance vs. a fresh one per call) without changing call
    sites.

    Example:
        ```pycon
        >>> from persista.cache import Cache
        >>> from persista.cache.factory import BaseCacheFactory
        >>> class MyCacheFactory(BaseCacheFactory):
        ...     def make_cache(self) -> Cache:
        ...         return Cache()
        ...
        >>> factory = MyCacheFactory()
        >>> cache = factory.make_cache()

        ```
    """

    @abstractmethod
    def make_cache(self) -> Cache:
        """Create and return a configured Cache instance.

        Returns:
            A :class:`~persista.cache.Cache`
            instance ready for use.
        """
