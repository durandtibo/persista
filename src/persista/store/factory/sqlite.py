r"""Provide factories for SQLite-backed persista BaseStore models."""

from __future__ import annotations

__all__ = ["PickleSQLiteStoreFactory", "SQLiteStoreFactory", "TypedSQLiteStoreFactory"]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.store.factory.base import BaseStoreFactory
from persista.store.sqlite import PickleSQLiteStore, SQLiteStore, TypedSQLiteStore

if TYPE_CHECKING:
    from pathlib import Path


class SQLiteStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new :class:`~persista.store.SQLiteStore`
    instance on each call to :meth:`make_store`.

    Args:
        database: The ``database`` argument passed to
            ``sqlite3.connect`` (path, ``":memory:"``, or ``file:``
            URI).
        **kwargs: Additional keyword arguments to pass to
            ``sqlite3.connect``.

    Example:
        ```pycon
        >>> from persista.store.factory import SQLiteStoreFactory
        >>> factory = SQLiteStoreFactory(":memory:")
        >>> store = factory.make_store()

        ```
    """

    def __init__(self, database: Path | str = ":memory:", **kwargs: Any) -> None:
        self._database = database
        self._kwargs = kwargs

    def make_store(self) -> SQLiteStore:
        return SQLiteStore(self._database, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"database": self._database} | self._kwargs


class TypedSQLiteStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new
    :class:`~persista.store.TypedSQLiteStore` instance on each call to
    :meth:`make_store`.

    Args:
        database: The ``database`` argument passed to
            ``sqlite3.connect`` (path, ``":memory:"``, or ``file:``
            URI).
        value_schema: Optional mapping of value field names to SQLite
            type strings.
        **kwargs: Additional keyword arguments to pass to
            ``sqlite3.connect``.

    Example:
        ```pycon
        >>> from persista.store.factory import TypedSQLiteStoreFactory
        >>> factory = TypedSQLiteStoreFactory(":memory:", value_schema={"author": "TEXT"})
        >>> store = factory.make_store()

        ```
    """

    def __init__(
        self,
        database: Path | str = ":memory:",
        value_schema: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        self._database = database
        self._value_schema = value_schema
        self._kwargs = kwargs

    def make_store(self) -> TypedSQLiteStore:
        return TypedSQLiteStore(self._database, value_schema=self._value_schema, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"database": self._database, "value_schema": self._value_schema} | self._kwargs


class PickleSQLiteStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new
    :class:`~persista.store.PickleSQLiteStore` instance on each call to
    :meth:`make_store`.

    Args:
        database: The ``database`` argument passed to
            ``sqlite3.connect`` (path, ``":memory:"``, or ``file:``
            URI).
        **kwargs: Additional keyword arguments to pass to
            ``sqlite3.connect``.

    Example:
        ```pycon
        >>> from persista.store.factory import PickleSQLiteStoreFactory
        >>> factory = PickleSQLiteStoreFactory(":memory:")
        >>> store = factory.make_store()

        ```
    """

    def __init__(self, database: Path | str = ":memory:", **kwargs: Any) -> None:
        self._database = database
        self._kwargs = kwargs

    def make_store(self) -> PickleSQLiteStore:
        return PickleSQLiteStore(self._database, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"database": self._database} | self._kwargs
