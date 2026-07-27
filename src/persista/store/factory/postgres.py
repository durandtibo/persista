r"""Provide factories for Postgres-backed persista BaseStore models."""

from __future__ import annotations

__all__ = ["PostgresStoreFactory", "TypedPostgresStoreFactory"]

from typing import Any

from coola.display import MultilineDisplayMixin

from persista.store.factory.base import BaseStoreFactory
from persista.store.postgres import PostgresStore, TypedPostgresStore


class PostgresStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new
    :class:`~persista.store.PostgresStore` instance on each call to
    :meth:`make_store`.

    Args:
        conninfo: The connection string/DSN passed to
            ``psycopg.connect``.
        table: The name of the table backing this store.
        **kwargs: Additional keyword arguments to pass to
            ``psycopg.connect``.

    Example:
        ```pycon
        >>> from persista.store.factory import PostgresStoreFactory
        >>> factory = PostgresStoreFactory("postgresql://user:pass@localhost/dbname")
        >>> store = factory.make_store()  # doctest: +SKIP

        ```
    """

    def __init__(self, conninfo: str, *, table: str = "store", **kwargs: Any) -> None:
        self._conninfo = conninfo
        self._table = table
        self._kwargs = kwargs

    def make_store(self) -> PostgresStore:
        return PostgresStore(self._conninfo, table=self._table, **self._kwargs)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {"conninfo": self._conninfo, "table": self._table} | self._kwargs


class TypedPostgresStoreFactory(BaseStoreFactory, MultilineDisplayMixin):
    """A factory that creates a new
    :class:`~persista.store.TypedPostgresStore` instance on each call to
    :meth:`make_store`.

    Args:
        conninfo: The connection string/DSN passed to
            ``psycopg.connect``.
        table: The name of the table backing this store.
        value_schema: Optional mapping of value field names to
            Postgres type strings.
        **kwargs: Additional keyword arguments to pass to
            ``psycopg.connect``.

    Example:
        ```pycon
        >>> from persista.store.factory import TypedPostgresStoreFactory
        >>> factory = TypedPostgresStoreFactory(
        ...     "postgresql://user:pass@localhost/dbname", value_schema={"author": "TEXT"}
        ... )
        >>> store = factory.make_store()  # doctest: +SKIP

        ```
    """

    def __init__(
        self,
        conninfo: str,
        *,
        table: str = "store",
        value_schema: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        self._conninfo = conninfo
        self._table = table
        self._value_schema = value_schema
        self._kwargs = kwargs

    def make_store(self) -> TypedPostgresStore:
        return TypedPostgresStore(
            self._conninfo, table=self._table, value_schema=self._value_schema, **self._kwargs
        )

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {
            "conninfo": self._conninfo,
            "table": self._table,
            "value_schema": self._value_schema,
        } | self._kwargs
