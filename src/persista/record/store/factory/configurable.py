r"""Provide a configurable factory for persista ``BaseRecordStore``
instances."""

from __future__ import annotations

__all__ = ["ConfigurableRecordStoreFactory"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.record.store.factory.base import BaseRecordStoreFactory
from persista.record.store.resolve import resolve_record_store

if TYPE_CHECKING:
    from persista.record.store.base import BaseRecordStore


class ConfigurableRecordStoreFactory(BaseRecordStoreFactory, MultilineDisplayMixin):
    """A concrete BaseRecordStore factory that accepts either a
    pre-built :class:`~persista.record.store.BaseRecordStore` instance
    or a configuration dictionary.

    When a dict is provided it is resolved at each
    :meth:`make_record_store` call via
    :func:`~persista.record.store.resolve.resolve_record_store`, which
    uses ``objectory`` to instantiate the configured class. When an
    instance is provided it is returned as-is.

    Args:
        record_store: A fully configured
            :class:`~persista.record.store.BaseRecordStore` instance,
            or a :class:`dict` containing an ``objectory`` factory
            specification (must include a ``"_target_"`` key pointing
            to the fully-qualified class name).

    Example:
        ```pycon
        >>> from persista.record.store import InMemoryRecordStore
        >>> from persista.record.store.factory import ConfigurableRecordStoreFactory
        >>> factory = ConfigurableRecordStoreFactory(InMemoryRecordStore())
        >>> store = factory.make_record_store()

        ```
    """

    def __init__(self, record_store: BaseRecordStore | dict[str, Any]) -> None:
        self._record_store = record_store

    def make_record_store(self) -> BaseRecordStore:
        return resolve_record_store(self._record_store)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"record_store": self._record_store}
