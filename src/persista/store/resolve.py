r"""Provide a resolution utility for creating persista ``BaseStore``
instances."""

from __future__ import annotations

__all__ = ["resolve_store"]

from typing import Any

from coola.factory import resolve_object

from persista.store.base import BaseStore


def resolve_store(store: BaseStore | dict[str, Any]) -> BaseStore:
    """Resolve a :class:`~persista.store.BaseStore` instance from an
    existing object or a configuration dictionary.

    If ``store`` is already a :class:`~persista.store.BaseStore`
    instance it is returned as-is. If it is a :class:`dict`, it is
    treated as an ``objectory`` factory configuration and instantiated
    via :func:`objectory.factory`. See
    :func:`~coola.factory.resolve_object` for details.

    Args:
        store: Either a fully configured
            :class:`~persista.store.BaseStore` instance, or a
            :class:`dict` containing an ``objectory`` factory
            specification (must include a ``"_target_"`` key
            pointing to the fully-qualified class name).

    Returns:
        A configured :class:`~persista.store.BaseStore` instance.

    Raises:
        TypeError: If the resolved object is not a
            :class:`~persista.store.BaseStore` instance.

    Example:
        ```pycon
        >>> from persista.store import InMemoryStore, resolve_store
        >>> # From an existing instance:
        >>> store = resolve_store(InMemoryStore())
        >>> # From a configuration dictionary:
        >>> store = resolve_store({"_target_": "persista.store.InMemoryStore"})

        ```
    """
    return resolve_object(store, cls=BaseStore)
