r"""Provide a factory for :class:`~persista.store.InMemoryStore`."""

from __future__ import annotations

__all__ = ["InMemoryStoreFactory"]

from typing import Any

from coola.display import InlineDisplayMixin

from persista.store.factory.base import BaseStoreFactory
from persista.store.in_memory import InMemoryStore


class InMemoryStoreFactory(BaseStoreFactory, InlineDisplayMixin):
    """A factory that creates a new
    :class:`~persista.store.InMemoryStore` instance on each call to
    :meth:`make_store`.

    Example:
        ```pycon
        >>> from persista.store.factory import InMemoryStoreFactory
        >>> factory = InMemoryStoreFactory()
        >>> store = factory.make_store()

        ```
    """

    def make_store(self) -> InMemoryStore:
        return InMemoryStore()

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {}
