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

from typing import TYPE_CHECKING, Any, ClassVar

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


class _UntypedRecordStoreFactory(BaseRecordStoreFactory, MultilineDisplayMixin):
    r"""Base class for a record store factory building an untyped (JSON-
    metadata) SQL-backed record store on each call.

    Subclasses only need to set ``_record_store_cls`` to the record
    store class to build (e.g. :class:`DuckDBRecordStore`).

    Args:
        database: The path to the database file, or ``":memory:"``
            for an in-memory database.
        **kwargs: Additional keyword arguments passed to
            ``_record_store_cls``.
    """

    _record_store_cls: ClassVar[Any]

    def __init__(self, database: Path | str = ":memory:", **kwargs: Any) -> None:
        self._database = database
        self._kwargs = kwargs

    def make_record_store(self) -> Any:
        return self._record_store_cls(self._database, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        # `database` is listed last so it always reflects the actual
        # value passed to the underlying store, even if `self._kwargs`
        # happens to contain a `database` key of its own.
        return {**self._kwargs, "database": self._database}


class _TypedRecordStoreFactory(BaseRecordStoreFactory, MultilineDisplayMixin):
    r"""Base class for a record store factory building a typed (per-field
    SQL column) SQL-backed record store on each call.

    Subclasses only need to set ``_record_store_cls`` to the record
    store class to build (e.g. :class:`TypedDuckDBRecordStore`).

    Args:
        database: The path to the database file, or ``":memory:"``
            for an in-memory database.
        metadata_schema: A mapping from metadata field name to its SQL
            column type declaration (e.g. ``{"author": "TEXT"}``).
            ``None`` is equivalent to an empty mapping, i.e. no
            metadata columns beyond the JSON overflow column.
        **kwargs: Additional keyword arguments passed to
            ``_record_store_cls``.
    """

    _record_store_cls: ClassVar[Any]

    def __init__(
        self,
        database: Path | str = ":memory:",
        metadata_schema: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        self._database = database
        self._metadata_schema = metadata_schema
        self._kwargs = kwargs

    def make_record_store(self) -> Any:
        return self._record_store_cls(
            self._database, metadata_schema=self._metadata_schema, **self._kwargs
        )

    def _get_repr_kwargs(self) -> dict[str, Any]:
        # `database`/`metadata_schema` are listed last so they always
        # reflect the actual values passed to the underlying store,
        # even if `self._kwargs` happens to contain keys of its own
        # with those names.
        return {
            **self._kwargs,
            "database": self._database,
            "metadata_schema": self._metadata_schema,
        }


class DuckDBRecordStoreFactory(_UntypedRecordStoreFactory):
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

    _record_store_cls = DuckDBRecordStore

    def make_record_store(self) -> DuckDBRecordStore:
        return super().make_record_store()


class TypedDuckDBRecordStoreFactory(_TypedRecordStoreFactory):
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

    _record_store_cls = TypedDuckDBRecordStore

    def make_record_store(self) -> TypedDuckDBRecordStore:
        return super().make_record_store()


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


class SQLiteRecordStoreFactory(_UntypedRecordStoreFactory):
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

    _record_store_cls = SQLiteRecordStore

    def make_record_store(self) -> SQLiteRecordStore:
        return super().make_record_store()


class TypedSQLiteRecordStoreFactory(_TypedRecordStoreFactory):
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

    _record_store_cls = TypedSQLiteRecordStore

    def make_record_store(self) -> TypedSQLiteRecordStore:
        return super().make_record_store()
