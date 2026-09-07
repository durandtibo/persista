r"""Provide record store factories for the ready-to-use ``persista``-
backed record stores."""

from __future__ import annotations

__all__ = [
    "DuckDBRecordStoreFactory",
    "InMemoryRecordStoreFactory",
    "SQLiteRecordStoreFactory",
    "TypedDuckDBRecordStoreFactory",
    "TypedSQLiteRecordStoreFactory",
]

from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.record.store.custom import (
    DuckDBRecordStore,
    InMemoryRecordStore,
    SQLiteRecordStore,
    TypedDuckDBRecordStore,
    TypedSQLiteRecordStore,
)
from persista.record.store.factory.base import BaseRecordStoreFactory

if TYPE_CHECKING:
    from pathlib import Path


class DuckDBRecordStoreFactory(BaseRecordStoreFactory, MultilineDisplayMixin):
    r"""Implement a record store factory that builds a new
    :class:`~persista.record.store.DuckDBRecordStore` on each call.

    Args:
        database: The path to the DuckDB database file, or
            ``":memory:"`` for an in-memory database.
        **kwargs: Additional keyword arguments passed to
            :class:`~persista.record.store.DuckDBRecordStore`.

    Example:
        ```pycon
        >>> from persista.record.store.factory import DuckDBRecordStoreFactory
        >>> factory = DuckDBRecordStoreFactory()
        >>> store = factory.make_record_store()

        ```
    """

    def __init__(self, database: Path | str = ":memory:", **kwargs: Any) -> None:
        self._database = database
        self._kwargs = kwargs

    def make_record_store(self) -> DuckDBRecordStore:
        return DuckDBRecordStore(self._database, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"database": self._database} | self._kwargs


class TypedDuckDBRecordStoreFactory(BaseRecordStoreFactory, MultilineDisplayMixin):
    r"""Implement a record store factory that builds a new
    :class:`~persista.record.store.TypedDuckDBRecordStore` on each
    call.

    Args:
        database: The path to the DuckDB database file, or
            ``":memory:"`` for an in-memory database.
        metadata_schema: A mapping from metadata field name to its SQL
            column type declaration (e.g. ``{"author": "TEXT"}``).
            ``None`` is equivalent to an empty mapping, i.e. no
            metadata columns beyond the JSON overflow column.
        **kwargs: Additional keyword arguments passed to
            :class:`~persista.record.store.TypedDuckDBRecordStore`.

    Example:
        ```pycon
        >>> from persista.record.store.factory import TypedDuckDBRecordStoreFactory
        >>> factory = TypedDuckDBRecordStoreFactory(metadata_schema={"author": "TEXT"})
        >>> store = factory.make_record_store()

        ```
    """

    def __init__(
        self,
        database: Path | str = ":memory:",
        metadata_schema: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        self._database = database
        self._metadata_schema = metadata_schema
        self._kwargs = kwargs

    def make_record_store(self) -> TypedDuckDBRecordStore:
        return TypedDuckDBRecordStore(
            self._database, metadata_schema=self._metadata_schema, **self._kwargs
        )

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {
            "database": self._database,
            "metadata_schema": self._metadata_schema,
        } | self._kwargs


class InMemoryRecordStoreFactory(BaseRecordStoreFactory, MultilineDisplayMixin):
    r"""Implement a record store factory that builds a new
    :class:`~persista.record.store.InMemoryRecordStore` on each call.

    Example:
        ```pycon
        >>> from persista.record.store.factory import InMemoryRecordStoreFactory
        >>> factory = InMemoryRecordStoreFactory()
        >>> store = factory.make_record_store()

        ```
    """

    def make_record_store(self) -> InMemoryRecordStore:
        return InMemoryRecordStore()

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {}


class SQLiteRecordStoreFactory(BaseRecordStoreFactory, MultilineDisplayMixin):
    r"""Implement a record store factory that builds a new
    :class:`~persista.record.store.SQLiteRecordStore` on each call.

    Args:
        database: The path to the SQLite database file, or
            ``":memory:"`` for an in-memory database.
        **kwargs: Additional keyword arguments passed to
            :class:`~persista.record.store.SQLiteRecordStore`.

    Example:
        ```pycon
        >>> from persista.record.store.factory import SQLiteRecordStoreFactory
        >>> factory = SQLiteRecordStoreFactory()
        >>> store = factory.make_record_store()

        ```
    """

    def __init__(self, database: Path | str = ":memory:", **kwargs: Any) -> None:
        self._database = database
        self._kwargs = kwargs

    def make_record_store(self) -> SQLiteRecordStore:
        return SQLiteRecordStore(self._database, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"database": self._database} | self._kwargs


class TypedSQLiteRecordStoreFactory(BaseRecordStoreFactory, MultilineDisplayMixin):
    r"""Implement a record store factory that builds a new
    :class:`~persista.record.store.TypedSQLiteRecordStore` on each
    call.

    Args:
        database: The path to the SQLite database file, or
            ``":memory:"`` for an in-memory database.
        metadata_schema: A mapping from metadata field name to its SQL
            column type declaration (e.g. ``{"author": "TEXT"}``).
            ``None`` is equivalent to an empty mapping, i.e. no
            metadata columns beyond the JSON overflow column.
        **kwargs: Additional keyword arguments passed to
            :class:`~persista.record.store.TypedSQLiteRecordStore`.

    Example:
        ```pycon
        >>> from persista.record.store.factory import TypedSQLiteRecordStoreFactory
        >>> factory = TypedSQLiteRecordStoreFactory(metadata_schema={"author": "TEXT"})
        >>> store = factory.make_record_store()

        ```
    """

    def __init__(
        self,
        database: Path | str = ":memory:",
        metadata_schema: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        self._database = database
        self._metadata_schema = metadata_schema
        self._kwargs = kwargs

    def make_record_store(self) -> TypedSQLiteRecordStore:
        return TypedSQLiteRecordStore(
            self._database, metadata_schema=self._metadata_schema, **self._kwargs
        )

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {
            "database": self._database,
            "metadata_schema": self._metadata_schema,
        } | self._kwargs
