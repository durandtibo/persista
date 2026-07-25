r"""Provide a concrete default factory for persista BaseStore models."""

from __future__ import annotations

__all__ = ["StoreFactory"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.store.factory.base import BaseStoreFactory

if TYPE_CHECKING:
    from persista.store.base import BaseStore


class StoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A concrete BaseStore factory that wraps a pre-built
    :class:`~persista.store.BaseStore` instance.

    Use this when the store is already instantiated and you simply
    want to wrap it in the :class:`~BaseStoreFactory` interface —
    for example, when injecting a fixed store into a component that
    expects a factory.

    Args:
        store: A fully configured
            :class:`~persista.store.BaseStore`
            instance to return from :meth:`make_store`.

    Example:
        ```pycon
        >>> from persista.store import InMemoryStore
        >>> from persista.store.factory import StoreFactory
        >>> factory = StoreFactory(InMemoryStore())
        >>> store = factory.make_store()

        ```
    """

    def __init__(self, store: BaseStore) -> None:
        self._store = store

    def make_store(self) -> BaseStore:
        return self._store

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"store": self._store}
