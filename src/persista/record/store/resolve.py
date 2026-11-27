r"""Provide a resolution utility for creating persista
``BaseRecordStore`` instances."""

from __future__ import annotations

__all__ = ["resolve_record_store"]

from typing import Any

from coola.factory import resolve_object

from persista.record.store.base import BaseRecordStore


def resolve_record_store(store: BaseRecordStore | dict[str, Any]) -> BaseRecordStore:
    """Resolve a :class:`~persista.record.store.BaseRecordStore`
    instance from an existing object or a configuration dictionary.

    If ``store`` is already a
    :class:`~persista.record.store.BaseRecordStore` instance it is
    returned as-is. If it is a :class:`dict`, it is treated as an
    ``objectory`` factory configuration and instantiated via
    :func:`objectory.factory`. See
    :func:`~coola.factory.resolve_object` for details.

    Args:
        store: Either a fully configured
            :class:`~persista.record.store.BaseRecordStore` instance,
            or a :class:`dict` containing an ``objectory`` factory
            specification (must include a ``"_target_"`` key pointing
            to the fully-qualified class name).

    Returns:
        A configured :class:`~persista.record.store.BaseRecordStore`
        instance.

    Raises:
        TypeError: If the resolved object is not a
            :class:`~persista.record.store.BaseRecordStore` instance.

    Example:
        ```pycon
        >>> from persista.record.store import InMemoryRecordStore, resolve_record_store
        >>> # From an existing instance:
        >>> store = resolve_record_store(InMemoryRecordStore())
        >>> # From a configuration dictionary:
        >>> store = resolve_record_store({"_target_": "persista.record.store.InMemoryRecordStore"})

        ```
    """
    return resolve_object(store, cls=BaseRecordStore)
