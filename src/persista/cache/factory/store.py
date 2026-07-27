r"""Provide a Cache factory backed by a BaseStore factory."""

from __future__ import annotations

__all__ = ["StoreCacheFactory"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.cache.cache import Cache
from persista.cache.factory.base import BaseCacheFactory

if TYPE_CHECKING:
    from persista.store.factory.base import BaseStoreFactory


class StoreCacheFactory(BaseCacheFactory, MultilineDisplayMixin):
    """A concrete Cache factory that builds its backing store from a
    :class:`~persista.store.factory.BaseStoreFactory`.

    Use this when the store itself needs to be freshly created (e.g.
    a new connection, a new in-memory dict) each time a
    :class:`~persista.cache.Cache` is requested, rather than sharing
    one store instance across every cache.

    Args:
        store_factory: The factory used to create the backing store
            passed to each :class:`~persista.cache.Cache` built by
            :meth:`make_cache`.
        default_ttl: The default time-to-live, in seconds, forwarded
            to each created :class:`~persista.cache.Cache`. See
            :class:`~persista.cache.Cache` for details.
        ignore_none: Forwarded to each created
            :class:`~persista.cache.Cache`. See
            :class:`~persista.cache.Cache` for details.

    Example:
        ```pycon
        >>> from persista.cache.factory import StoreCacheFactory
        >>> from persista.store.factory import StoreFactory
        >>> from persista.store import InMemoryStore
        >>> factory = StoreCacheFactory(StoreFactory(InMemoryStore()))
        >>> with factory.make_cache() as cache:
        ...     cache.set("greeting", "hello")
        ...     cache.get("greeting")
        ...
        'hello'

        ```
    """

    def __init__(
        self,
        store_factory: BaseStoreFactory,
        default_ttl: float | None = None,
        ignore_none: bool = False,
    ) -> None:
        self._store_factory = store_factory
        self._default_ttl = default_ttl
        self._ignore_none = ignore_none

    def make_cache(self) -> Cache:
        return Cache(
            store=self._store_factory.make_store(),
            default_ttl=self._default_ttl,
            ignore_none=self._ignore_none,
        )

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {
            "store_factory": self._store_factory,
            "default_ttl": self._default_ttl,
            "ignore_none": self._ignore_none,
        }
