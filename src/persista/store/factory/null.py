r"""Provide a factory for :class:`~persista.store.NullStore`."""

from __future__ import annotations

__all__ = ["NullStoreFactory"]

from typing import Any

from coola.display import InlineDisplayMixin

from persista.store.factory.base import BaseStoreFactory
from persista.store.null import NullStore


class NullStoreFactory(BaseStoreFactory, InlineDisplayMixin):
    """A factory that creates a new :class:`~persista.store.NullStore`
    instance on each call to :meth:`make_store`.

    Example:
        ```pycon
        >>> from persista.store.factory import NullStoreFactory
        >>> factory = NullStoreFactory()
        >>> store = factory.make_store()

        ```
    """

    def make_store(self) -> NullStore:
        return NullStore()

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {}
