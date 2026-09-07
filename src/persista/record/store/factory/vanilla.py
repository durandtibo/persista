r"""Provide a concrete default factory for persista
``BaseRecordStore`` instances."""

from __future__ import annotations

__all__ = ["RecordStoreFactory"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.record.store.factory.base import BaseRecordStoreFactory

if TYPE_CHECKING:
    from persista.record.store.base import BaseRecordStore


class RecordStoreFactory(BaseRecordStoreFactory, MultilineDisplayMixin):
    """A concrete BaseRecordStore factory that wraps a pre-built
    :class:`~persista.record.store.BaseRecordStore` instance.

    Use this when the record store is already instantiated and you
    simply want to wrap it in the :class:`~BaseRecordStoreFactory`
    interface -- for example, when injecting a fixed record store
    into a component that expects a factory.

    Args:
        record_store: A fully configured
            :class:`~persista.record.store.BaseRecordStore` instance
            to return from :meth:`make_record_store`.

    Example:
        ```pycon
        >>> from persista.record.store import InMemoryRecordStore
        >>> from persista.record.store.factory import RecordStoreFactory
        >>> factory = RecordStoreFactory(InMemoryRecordStore())
        >>> store = factory.make_record_store()

        ```
    """

    def __init__(self, record_store: BaseRecordStore) -> None:
        self._record_store = record_store

    def make_record_store(self) -> BaseRecordStore:
        return self._record_store

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"record_store": self._record_store}
