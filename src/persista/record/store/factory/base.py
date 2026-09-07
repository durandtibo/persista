r"""Provide the base factory interface for creating persista
``BaseRecordStore`` instances."""

from __future__ import annotations

__all__ = ["BaseRecordStoreFactory"]

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from persista.record.store.base import BaseRecordStore


class BaseRecordStoreFactory(ABC):
    """Abstract base class for
    :class:`~persista.record.store.BaseRecordStore` factories.

    Subclasses implement :meth:`make_record_store` to instantiate and
    return a configured :class:`~persista.record.store.BaseRecordStore`
    object. This pattern decouples record store creation from the
    rest of the codebase, making it easy to swap how a record store is
    built (e.g. a shared instance vs. a fresh one per call) without
    changing call sites.

    Example:
        ```pycon
        >>> from persista.record.store import BaseRecordStore, InMemoryRecordStore
        >>> from persista.record.store.factory import BaseRecordStoreFactory
        >>> class MyRecordStoreFactory(BaseRecordStoreFactory):
        ...     def make_record_store(self) -> BaseRecordStore:
        ...         return InMemoryRecordStore()
        ...
        >>> factory = MyRecordStoreFactory()
        >>> store = factory.make_record_store()

        ```
    """

    @abstractmethod
    def make_record_store(self) -> BaseRecordStore:
        """Create and return a configured BaseRecordStore instance.

        Returns:
            A :class:`~persista.record.store.BaseRecordStore`
            instance ready for use.
        """
