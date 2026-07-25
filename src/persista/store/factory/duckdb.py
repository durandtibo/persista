r"""Provide factories for DuckDB-backed persista BaseStore models."""

from __future__ import annotations

__all__ = ["DuckDBStoreFactory", "TypedDuckDBStoreFactory"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.store.duckdb import DuckDBStore, TypedDuckDBStore
from persista.store.factory.base import BaseStoreFactory

if TYPE_CHECKING:
    from pathlib import Path


class DuckDBStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new :class:`~persista.store.DuckDBStore`
    instance on each call to :meth:`make_store`.

    Args:
        path: Path to the DuckDB file, or ``":memory:"`` for an
            in-memory database.
        **kwargs: Additional keyword arguments to pass to
            ``duckdb.connect``.

    Example:
        ```pycon
        >>> from persista.store.factory import DuckDBStoreFactory
        >>> factory = DuckDBStoreFactory(":memory:")
        >>> store = factory.make_store()

        ```
    """

    def __init__(self, path: Path | str = ":memory:", **kwargs: Any) -> None:
        self._path = path
        self._kwargs = kwargs

    def make_store(self) -> DuckDBStore:
        return DuckDBStore(self._path, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"path": self._path} | self._kwargs


class TypedDuckDBStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new
    :class:`~persista.store.TypedDuckDBStore` instance on each call to
    :meth:`make_store`.

    Args:
        path: Path to the DuckDB file, or ``":memory:"`` for an
            in-memory database.
        value_schema: Optional mapping of value field names to DuckDB
            type strings.
        **kwargs: Additional keyword arguments to pass to
            ``duckdb.connect``.

    Example:
        ```pycon
        >>> from persista.store.factory import TypedDuckDBStoreFactory
        >>> factory = TypedDuckDBStoreFactory(":memory:", value_schema={"author": "TEXT"})
        >>> store = factory.make_store()

        ```
    """

    def __init__(
        self,
        path: Path | str = ":memory:",
        value_schema: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        self._path = path
        self._value_schema = value_schema
        self._kwargs = kwargs

    def make_store(self) -> TypedDuckDBStore:
        return TypedDuckDBStore(self._path, value_schema=self._value_schema, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"path": self._path, "value_schema": self._value_schema} | self._kwargs
