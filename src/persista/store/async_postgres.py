r"""Provide an asynchronous Postgres-backed implementation of
``AsyncBaseStore``, storing values as JSONB."""

from __future__ import annotations

__all__ = ["AsyncBasePostgresStore", "AsyncPostgresStore", "AsyncTypedPostgresStore"]

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.store.base import AsyncBaseStore
from persista.store.validation import (
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
    validate_table_name,
)
from persista.utils.imports import check_psycopg, is_psycopg_available

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Mapping
    from typing import Self

    from persista.store.types import OnConflict

if is_psycopg_available():  # pragma: no cover
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb

logger: logging.Logger = logging.getLogger(__name__)


class AsyncBasePostgresStore(AsyncBaseStore, MultilineDisplayMixin):
    r"""Define a base class for Postgres-backed asynchronous key-value
    stores.

    Mirrors :class:`~persista.store.postgres.BasePostgresStore`, but
    runs every query through :class:`psycopg.AsyncConnection` instead
    of the blocking :class:`psycopg.Connection`, so it can be awaited
    from an async application without stalling the event loop on
    network I/O.

    A single table (named by the ``table`` argument, ``"store"`` by
    default) backs every value; the primary key column is named by
    :attr:`_key_column`. :meth:`get`, :meth:`get_many`, :meth:`filter`,
    and :meth:`iter_batches` all query the full row and hand it to
    :meth:`_row_to_value` to turn it back into a value dict, which is
    what lets subclasses differ in how a value is laid out across
    columns (a single JSONB column vs. typed columns plus a JSONB
    overflow column) without duplicating any of the surrounding query
    logic.

    Subclasses only need to implement :meth:`_create_table_sql`,
    :meth:`_row_to_value`, :meth:`_build_filter_condition`, and
    :meth:`_set_many` (see :class:`AsyncPostgresStore` for a
    JSONB-only layout and :class:`AsyncTypedPostgresStore` for an
    optionally typed one).

    The table schema is created lazily, on the first query, rather
    than in the constructor -- ``__init__`` cannot ``await``, so
    there's no synchronous point at which the schema could be
    created eagerly.

    Args:
        conninfo: The connection string/DSN passed to
            ``psycopg.AsyncConnection.connect`` (e.g.
            ``"postgresql://user:pass@localhost/dbname"``).
        table: The name of the table backing this store. Must be a
            valid SQL identifier (letters, digits, underscores, not
            starting with a digit).
        **kwargs: Additional keyword arguments to pass to
            ``psycopg.AsyncConnection.connect``.
    """

    #: Name of the table's primary key column.
    _key_column: str = "key"

    def __init__(self, conninfo: str, *, table: str = "store", **kwargs: Any) -> None:
        check_psycopg()
        validate_table_name(table)
        self._conninfo = conninfo
        self._table = table
        self._kwargs = kwargs
        self._closed = False
        self._conn: psycopg.AsyncConnection | None = None
        self._schema_ready = False

    @property
    def _table_ident(self) -> sql.Identifier:
        return sql.Identifier(self._table)

    async def _ensure_schema(self) -> None:
        """Connect to the database and create the store's table if it
        doesn't already exist.

        Called lazily before every query, since the connection cannot be
        established eagerly in ``__init__`` (see the class docstring).
        Also called again each time the store is reopened via
        :meth:`__aenter__` after being closed.
        """
        if self._conn is None:
            self._conn = await psycopg.AsyncConnection.connect(
                self._conninfo, autocommit=True, **self._kwargs
            )
        if self._schema_ready:
            return
        await self._conn.execute(self._create_table_sql())
        self._schema_ready = True

    @abstractmethod
    def _create_table_sql(self) -> sql.Composed:
        """Return the ``CREATE TABLE IF NOT EXISTS`` statement for this
        store's schema."""

    @abstractmethod
    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
        """Convert a raw ``SELECT * FROM {table}`` row back to a value
        dict."""

    @abstractmethod
    def _build_filter_condition(self, key: str) -> sql.Composable:
        """Build the SQL condition fragment (with a single ``%s``
        placeholder) that matches value field ``key`` against a bound
        parameter."""

    @abstractmethod
    async def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        """Write ``items`` to the table, replacing any existing row for
        the same key."""

    async def close(self) -> None:
        if self._closed:
            return
        logger.info("Closing Postgres connection for table %s", self._table)
        if self._conn is not None:
            await self._conn.close()
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    async def get(self, key: str) -> dict[str, Any] | None:
        await self._ensure_schema()
        query = sql.SQL("SELECT * FROM {table} WHERE {key_col} = %s").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        async with self._conn.cursor() as cur:
            await cur.execute(query, (key,))
            row = await cur.fetchone()
        return self._row_to_value(row) if row else None

    async def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        await self._ensure_schema()
        query = sql.SQL("SELECT * FROM {table} WHERE {key_col} = ANY(%s)").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        async with self._conn.cursor() as cur:
            await cur.execute(query, (keys,))
            rows = await cur.fetchall()
        by_key = {row[0]: self._row_to_value(row) for row in rows}
        return [by_key.get(key) for key in keys]

    async def set(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
    ) -> None:
        await self.set_many({key: value}, on_conflict=on_conflict)

    async def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        if not items:
            return
        await self._ensure_schema()
        on_conflict = normalize_on_conflict(on_conflict)
        if on_conflict == "overwrite":
            await self._set_many(items)
            return

        conflicts = set((await self.contains_many(list(items)))[0])
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
            raise KeyError(msg)

        to_write: dict[str, dict[str, Any]] = {}
        for key, value in items.items():
            if key in conflicts:
                if on_conflict == "skip":
                    continue
                to_write[key] = {**(await self.get(key) or {}), **value}
                continue
            to_write[key] = value

        await self._set_many(to_write)

    async def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        await self._ensure_schema()
        if not field_filters:
            query = sql.SQL("SELECT * FROM {table}").format(table=self._table_ident)
            async with self._conn.cursor() as cur:
                await cur.execute(query)
                rows = await cur.fetchall()
            return [self._row_to_value(row) for row in rows]

        conditions = [self._build_filter_condition(key) for key in field_filters]
        where = sql.SQL(" AND ").join(conditions)
        query = sql.SQL("SELECT * FROM {table} WHERE {where}").format(
            table=self._table_ident, where=where
        )
        async with self._conn.cursor() as cur:
            await cur.execute(query, list(field_filters.values()))
            rows = await cur.fetchall()
        return [self._row_to_value(row) for row in rows]

    async def delete(self, key: str) -> None:
        await self._ensure_schema()
        query = sql.SQL("DELETE FROM {table} WHERE {key_col} = %s").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        await self._conn.execute(query, (key,))

    async def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        await self._ensure_schema()
        query = sql.SQL("DELETE FROM {table} WHERE {key_col} = ANY(%s)").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        await self._conn.execute(query, (keys,))

    async def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        if not keys:
            return [], []
        await self._ensure_schema()
        query = sql.SQL("SELECT {key_col} FROM {table} WHERE {key_col} = ANY(%s)").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        async with self._conn.cursor() as cur:
            await cur.execute(query, (keys,))
            existing = {row[0] for row in await cur.fetchall()}
        found = [key for key in keys if key in existing]
        missing = [key for key in keys if key not in existing]
        return found, missing

    async def keys(self) -> AsyncIterator[str]:
        await self._ensure_schema()
        query = sql.SQL("SELECT {key_col} FROM {table}").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        async with self._conn.cursor() as cur:
            await cur.execute(query)
            async for (key,) in cur:
                yield key

    async def iter_batches(
        self, batch_size: int = 32
    ) -> AsyncGenerator[dict[str, dict[str, Any]], None]:
        validate_batch_size(batch_size)
        await self._ensure_schema()
        query = sql.SQL("SELECT * FROM {table}").format(table=self._table_ident)
        # A named (server-side) cursor requires an explicit transaction
        # block even on an autocommit connection.
        async with (
            self._conn.transaction(),
            self._conn.cursor(name=f"iter_batches_{id(self)}") as cur,
        ):
            cur.itersize = batch_size
            await cur.execute(query)
            batch: dict[str, dict[str, Any]] = {}
            async for row in cur:
                batch[row[0]] = self._row_to_value(row)
                if len(batch) >= batch_size:
                    yield batch
                    batch = {}
            if batch:
                yield batch

    async def count(self) -> int:
        await self._ensure_schema()
        query = sql.SQL("SELECT COUNT(*) FROM {table}").format(table=self._table_ident)
        async with self._conn.cursor() as cur:
            await cur.execute(query)
            row = await cur.fetchone()
            return row[0] if row else 0

    def _get_repr_kwargs(self) -> dict[str, Any]:
        # `count` is intentionally omitted: computing it requires an
        # awaited query, which isn't available from this sync method.
        return {"table": self._table, "closed": self._closed} | self._kwargs

    async def __aenter__(self) -> Self:
        if self._closed:
            self._closed = False
            self._conn = None
            self._schema_ready = False
        return self


_CREATE_TABLE_SQL = """CREATE TABLE IF NOT EXISTS {table} ( key
               TEXT PRIMARY KEY,

               value JSONB NOT NULL )
               """


class AsyncPostgresStore(AsyncBasePostgresStore):
    """An asynchronous Postgres-backed key-value store.

    Persists values to a Postgres database and supports adding,
    retrieving, filtering, and deleting key-value pairs. Each value is
    stored as a JSONB column, which provides flexibility for arbitrary
    value fields without requiring a fixed schema. Mirrors
    :class:`~persista.store.postgres.PostgresStore`, but every method
    is a coroutine, backed by :class:`psycopg.AsyncConnection` instead
    of the blocking :class:`psycopg.Connection`.

    Args:
        conninfo: The connection string/DSN passed to
            ``psycopg.AsyncConnection.connect`` (e.g.
            ``"postgresql://user:pass@localhost/dbname"``).
        table: The name of the table backing this store.
        **kwargs: Additional keyword arguments to pass to
            ``psycopg.AsyncConnection.connect``.

    Example:
        ```pycon
        >>> import asyncio
        >>> from persista.store import AsyncPostgresStore
        >>> async def main():
        ...     store = AsyncPostgresStore("postgresql://user:pass@localhost/dbname")
        ...     await store.set_many(
        ...         {
        ...             "1": {"title": "Intro to Python", "author": "Alice"},
        ...             "2": {"title": "Advanced Python", "author": "Alice"},
        ...         }
        ...     )
        ...     result = await store.filter(author="Alice")
        ...     print(len(result))
        ...     await store.close()
        ...
        >>> asyncio.run(main())  # doctest: +SKIP
        2

        ```
    """

    def _create_table_sql(self) -> sql.Composed:
        return sql.SQL(_CREATE_TABLE_SQL).format(table=self._table_ident)

    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
        return row[1]

    def _build_filter_condition(self, key: str) -> sql.Composable:
        validate_field_name(key)
        # value->>{field} extracts as text, so the bound parameter (which
        # may be an int, bool, etc.) must be cast to text to compare.
        return sql.SQL("value->>{field} = %s::text").format(field=sql.Literal(key))

    async def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            query = sql.SQL(
                "INSERT INTO {table} ({key_col}, value) VALUES (%s, %s) "
                "ON CONFLICT ({key_col}) DO UPDATE SET value = EXCLUDED.value"
            ).format(table=self._table_ident, key_col=sql.Identifier(self._key_column))
            async with self._conn.cursor() as cur:
                await cur.executemany(query, [(key, Jsonb(value)) for key, value in items.items()])

        logger.debug("Added/replaced %d key-value pair(s)", len(items))


_KEY_COLUMN = "_KEY_"


class AsyncTypedPostgresStore(AsyncBasePostgresStore):
    """An asynchronous Postgres-backed key-value store with an optional
    typed value schema.

    Persists values to a Postgres database and supports adding,
    retrieving, and filtering by value fields. An optional
    ``value_schema`` maps known value field names to Postgres types.
    Known fields are stored as typed columns for fast, index-friendly
    queries. Any value fields not in the schema are stored in an
    ``extra`` JSONB overflow column, so nothing is lost. Mirrors
    :class:`~persista.store.postgres.TypedPostgresStore`, but every
    method is a coroutine, backed by :class:`psycopg.AsyncConnection`
    instead of the blocking :class:`psycopg.Connection`.

    Args:
        conninfo: The connection string/DSN passed to
            ``psycopg.AsyncConnection.connect``.
        table: The name of the table backing this store.
        value_schema: Optional mapping of value field names to
            Postgres type strings (e.g. ``{"author": "TEXT", "year":
            "INTEGER"}``). Fields in the schema get native typed
            columns; all other value fields go into the ``extra``
            JSONB overflow column. Defaults to ``None``, which stores
            every value field as JSONB only.
        **kwargs: Additional keyword arguments to pass to
            ``psycopg.AsyncConnection.connect``.

    Example:
        ```pycon
        >>> import asyncio
        >>> from persista.store import AsyncTypedPostgresStore
        >>> async def main():
        ...     schema = {"author": "TEXT", "year": "INTEGER"}
        ...     store = AsyncTypedPostgresStore(
        ...         "postgresql://user:pass@localhost/dbname", value_schema=schema
        ...     )
        ...     await store.set_many(
        ...         {
        ...             "1": {"title": "Intro to Python", "author": "Alice", "year": 2022},
        ...             "2": {"title": "History of Rome", "author": "Bob", "year": 2021},
        ...         }
        ...     )
        ...     result = await store.filter(author="Alice")
        ...     print(len(result))
        ...     await store.close()
        ...
        >>> asyncio.run(main())  # doctest: +SKIP
        1

        ```
    """

    _key_column = _KEY_COLUMN

    def __init__(
        self,
        conninfo: str,
        *,
        table: str = "store",
        value_schema: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        value_schema = value_schema or {}
        if _KEY_COLUMN in value_schema:
            msg = f"value_schema must not contain the reserved key column name {_KEY_COLUMN!r}"
            raise ValueError(msg)
        self._schema: dict[str, str] = value_schema
        super().__init__(conninfo, table=table, **kwargs)

    def _create_table_sql(self) -> sql.Composed:
        typed_cols = sql.SQL("").join(
            sql.SQL(", {col} {dtype}").format(
                col=sql.Identifier(name),
                dtype=sql.SQL(dtype),  # pyright: ignore[reportArgumentType]
            )
            for name, dtype in self._schema.items()
        )
        return sql.SQL(
            "CREATE TABLE IF NOT EXISTS {table} ({key_col} TEXT PRIMARY KEY{typed_cols}, extra JSONB)"
        ).format(
            table=self._table_ident, key_col=sql.Identifier(_KEY_COLUMN), typed_cols=typed_cols
        )

    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
        # row layout: key, [schema cols...], extra
        schema_vals = dict(zip(self._schema.keys(), row[1 : 1 + len(self._schema)], strict=True))
        extra = row[1 + len(self._schema)]
        value = {k: v for k, v in schema_vals.items() if v is not None}
        if extra:
            value.update(extra)
        return value

    def _build_filter_condition(self, key: str) -> sql.Composable:
        if key in self._schema:
            return sql.SQL("{col} = %s").format(col=sql.Identifier(key))
        validate_field_name(key)
        # extra->>{field} extracts as text, so the bound parameter (which
        # may be an int, bool, etc.) must be cast to text to compare.
        return sql.SQL("extra->>{field} = %s::text").format(field=sql.Literal(key))

    async def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            query = self._build_insert()
            async with self._conn.cursor() as cur:
                await cur.executemany(
                    query, [self._value_to_row(key, value) for key, value in items.items()]
                )

        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    def _build_insert(self) -> sql.Composed:
        col_names = [_KEY_COLUMN, *self._schema.keys(), "extra"]
        columns = sql.SQL(", ").join(sql.Identifier(name) for name in col_names)
        placeholders = sql.SQL(", ").join(sql.Placeholder() * len(col_names))
        update_cols = sql.SQL(", ").join(
            sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(name))
            for name in [*self._schema.keys(), "extra"]
        )
        return sql.SQL(
            "INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
            "ON CONFLICT ({key_col}) DO UPDATE SET {update_cols}"
        ).format(
            table=self._table_ident,
            columns=columns,
            placeholders=placeholders,
            key_col=sql.Identifier(_KEY_COLUMN),
            update_cols=update_cols,
        )

    def _value_to_row(self, key: str, value: dict[str, Any]) -> tuple[Any, ...]:
        known = [value.get(k) for k in self._schema]
        extra = {k: v for k, v in value.items() if k not in self._schema}
        return (key, *known, Jsonb(extra) if extra else None)
