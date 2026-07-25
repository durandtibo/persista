r"""Provide a configurable factory for persista BaseStore models."""

from __future__ import annotations

__all__ = ["ConfigurableStoreFactory"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.store.factory.base import BaseStoreFactory
from persista.store.resolve import resolve_store

if TYPE_CHECKING:
    from persista.store.base import BaseStore


class ConfigurableStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A concrete BaseStore factory that accepts either a pre-built
    :class:`~persista.store.BaseStore` instance or a configuration
    dictionary.

    When a dict is provided it is resolved at each
    :meth:`make_store` call via
    :func:`~persista.store.resolve.resolve_store`,
    which uses ``objectory`` to instantiate the configured class.
    When an instance is provided it is returned as-is.

    Args:
        store: A fully configured
            :class:`~persista.store.BaseStore`
            instance, or a :class:`dict` containing an ``objectory``
            factory specification (must include a ``"_target_"`` key
            pointing to the fully-qualified class name).

    Example:
        ```pycon
        >>> from persista.store import InMemoryStore
        >>> from persista.store.factory import ConfigurableStoreFactory
        >>> factory = ConfigurableStoreFactory(InMemoryStore())
        >>> store = factory.make_store()

        ```
    """

    def __init__(self, store: BaseStore | dict[str, Any]) -> None:
        self._store = store

    def make_store(self) -> BaseStore:
        return resolve_store(self._store)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"store": self._store}
