r"""Provide the base factory interface for creating persista BaseStore
models."""

from __future__ import annotations

__all__ = ["BaseStoreFactory"]

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from persista.store.base import BaseStore


class BaseStoreFactory(ABC):
    """Abstract base class for :class:`~persista.store.BaseStore`
    factories.

    Subclasses implement :meth:`make_store` to instantiate
    and return a configured
    :class:`~persista.store.BaseStore` object.
    This pattern decouples store creation from the rest of the
    codebase, making it easy to swap stores (e.g. in-memory, SQLite,
    DuckDB) without changing call sites.

    Example:
        ```pycon
        >>> from persista.store import InMemoryStore, BaseStore
        >>> from persista.store.factory import BaseStoreFactory
        >>> class MyStoreFactory(BaseStoreFactory):
        ...     def make_store(self) -> BaseStore:
        ...         return InMemoryStore()
        ...
        >>> factory = MyStoreFactory()
        >>> store = factory.make_store()

        ```
    """

    @abstractmethod
    def make_store(self) -> BaseStore:
        """Create and return a configured BaseStore instance.

        Returns:
            A :class:`~persista.store.BaseStore` instance. The store
            is not opened; call :meth:`~persista.store.BaseStore.open`
            (or use it as a context manager) before using it.
        """
