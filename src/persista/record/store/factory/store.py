r"""Provide a RecordStore factory backed by a persista BaseStore
factory."""

from __future__ import annotations

__all__ = ["StoreRecordStoreFactory"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.record.store.factory.base import BaseRecordStoreFactory
from persista.record.store.record import RecordStore

if TYPE_CHECKING:
    from persista.store.factory.base import BaseStoreFactory


class StoreRecordStoreFactory(BaseRecordStoreFactory, MultilineDisplayMixin):
    """A concrete record store factory that builds its backing store
    from a :class:`~persista.store.factory.BaseStoreFactory`.

    Use this when the underlying key-value store needs to be freshly
    created (e.g. a new connection, a new in-memory dict) each time a
    :class:`~persista.record.store.RecordStore` is requested, rather
    than sharing one store instance across every record store.

    Args:
        store_factory: The factory used to create the backing
            key-value store passed to each
            :class:`~persista.record.store.RecordStore` built by
            :meth:`make_record_store`.

    Example:
        ```pycon
        >>> from persista.record.store.factory import StoreRecordStoreFactory
        >>> from persista.store.factory import InMemoryStoreFactory
        >>> factory = StoreRecordStoreFactory(InMemoryStoreFactory())
        >>> store = factory.make_record_store()
        >>> store.open()

        ```
    """

    def __init__(self, store_factory: BaseStoreFactory) -> None:
        self._store_factory = store_factory

    def make_record_store(self) -> RecordStore:
        return RecordStore(store=self._store_factory.make_store())

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"store_factory": self._store_factory}
