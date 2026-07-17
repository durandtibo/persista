r"""Provide a Postgres-backed implementation of ``BaseStore``, storing
values as JSONB."""

from __future__ import annotations

__all__ = ["BasePostgresStore", "PostgresStore", "TypedPostgresStore"]

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify

from persista.store.base import BaseStore
from persista.store.validation import (
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
    validate_table_name,
)
from persista.utils.imports import check_psycopg, is_psycopg_available

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Mapping
    from typing import Self

    from persista.store.types import OnConflict

if is_psycopg_available():  # pragma: no cover
    import psycopg
    from psycopg import sql
    from psycopg.types.json import Jsonb

logger: logging.Logger = logging.getLogger(__name__)


class BasePostgresStore(BaseStore, MultilineDisplayMixin):
    r"""Define a base class for Postgres-backed key-value stores.

    A single table (named by the ``table`` argument, ``"store"`` by
    default) backs every value; the primary key column is named by
    :attr:`_key_column`. :meth:`get`, :meth:`get_many`, :meth:`filter`,
    and :meth:`iter_batches` all query the full row and hand it to
    :meth:`_row_to_value` to turn it back into a value dict, which is
    what lets subclasses differ in how a value is laid out across
    columns (a single JSONB column vs. typed columns plus a JSONB
    overflow column) without duplicating any of the surrounding query
    logic. This mirrors :class:`~persista.store.sqlite.BaseSQLiteStore`.

    Subclasses only need to implement :meth:`_create_table_sql`,
    :meth:`_row_to_value`, :meth:`_build_filter_condition`, and
    :meth:`_set_many` (see :class:`PostgresStore` for a JSONB-only
    layout and :class:`~persista.store.postgres.TypedPostgresStore`
    for an optionally typed one).

    Args:
        conninfo: The connection string/DSN passed to
            ``psycopg.connect`` (e.g.
            ``"postgresql://user:pass@localhost/dbname"``).
        table: The name of the table backing this store. Must be a
            valid SQL identifier (letters, digits, underscores, not
            starting with a digit).
        **kwargs: Additional keyword arguments to pass to
            ``psycopg.connect``.
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
        self._conn = psycopg.connect(conninfo, autocommit=True, **kwargs)
        self._conn.execute(self._create_table_sql())

    @property
    def _table_ident(self) -> sql.Identifier:
        return sql.Identifier(self._table)

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
    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        """Write ``items`` to the table, replacing any existing row for
        the same key."""

    def close(self) -> None:
        if self._closed:
            return
        logger.info("Closing Postgres connection for table %s", self._table)
        self._conn.close()
        self._closed = True

    def get(self, key: str) -> dict[str, Any] | None:
        query = sql.SQL("SELECT * FROM {table} WHERE {key_col} = %s").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        with self._conn.cursor() as cur:
            cur.execute(query, (key,))
            row = cur.fetchone()
        return self._row_to_value(row) if row else None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        query = sql.SQL("SELECT * FROM {table} WHERE {key_col} = ANY(%s)").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        with self._conn.cursor() as cur:
            cur.execute(query, (keys,))
            rows = cur.fetchall()
        by_key = {row[0]: self._row_to_value(row) for row in rows}
        return [by_key.get(key) for key in keys]

    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
        self.set_many({key: value}, on_conflict=on_conflict)

    def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        if not items:
            return
        on_conflict = normalize_on_conflict(on_conflict)
        if on_conflict == "overwrite":
            self._set_many(items)
            return

        conflicts = set(self.contains_many(list(items))[0])
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
            raise KeyError(msg)

        to_write: dict[str, dict[str, Any]] = {}
        for key, value in items.items():
            if key in conflicts:
                if on_conflict == "skip":
                    continue
                to_write[key] = {**(self.get(key) or {}), **value}
                continue
            to_write[key] = value

        self._set_many(to_write)

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not field_filters:
            query = sql.SQL("SELECT * FROM {table}").format(table=self._table_ident)
            with self._conn.cursor() as cur:
                cur.execute(query)
                rows = cur.fetchall()
            return [self._row_to_value(row) for row in rows]

        conditions = [self._build_filter_condition(key) for key in field_filters]
        where = sql.SQL(" AND ").join(conditions)
        query = sql.SQL("SELECT * FROM {table} WHERE {where}").format(
            table=self._table_ident, where=where
        )
        with self._conn.cursor() as cur:
            cur.execute(query, list(field_filters.values()))
            rows = cur.fetchall()
        return [self._row_to_value(row) for row in rows]

    def delete(self, key: str) -> None:
        query = sql.SQL("DELETE FROM {table} WHERE {key_col} = %s").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        self._conn.execute(query, (key,))

    def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        query = sql.SQL("DELETE FROM {table} WHERE {key_col} = ANY(%s)").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        self._conn.execute(query, (keys,))

    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        if not keys:
            return [], []
        query = sql.SQL("SELECT {key_col} FROM {table} WHERE {key_col} = ANY(%s)").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        with self._conn.cursor() as cur:
            cur.execute(query, (keys,))
            existing = {row[0] for row in cur.fetchall()}
        found = [key for key in keys if key in existing]
        missing = [key for key in keys if key not in existing]
        return found, missing

    def keys(self) -> Iterator[str]:
        query = sql.SQL("SELECT {key_col} FROM {table}").format(
            table=self._table_ident, key_col=sql.Identifier(self._key_column)
        )
        with self._conn.cursor() as cur:
            cur.execute(query)
            for (key,) in cur.fetchall():
                yield key

    def iter_batches(
        self, batch_size: int = 32
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        validate_batch_size(batch_size)
        query = sql.SQL("SELECT * FROM {table}").format(table=self._table_ident)
        # A named (server-side) cursor requires an explicit transaction
        # block even on an autocommit connection.
        with (
            self._conn.transaction(),
            self._conn.cursor(name=f"iter_batches_{id(self)}") as cur,
        ):
            cur.itersize = batch_size
            cur.execute(query)
            for batch in batchify(cur, size=batch_size):
                yield {row[0]: self._row_to_value(row) for row in batch}

    def count(self) -> int:
        query = sql.SQL("SELECT COUNT(*) FROM {table}").format(table=self._table_ident)
        with self._conn.cursor() as cur:
            cur.execute(query)
            row = cur.fetchone()
            return row[0] if row else 0

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"table": self._table, "closed": self._closed}
        if not self._closed:
            kwargs["count"] = self.count()
        return kwargs | self._kwargs

    def __enter__(self) -> Self:
        return self


class PostgresStore(BasePostgresStore):
    """A Postgres-backed key-value store.

    Persists values to a Postgres database and supports adding,
    retrieving, filtering, and deleting key-value pairs. Each value is
    stored as a JSONB column, which provides flexibility for arbitrary
    value fields without requiring a fixed schema.

    Args:
        conninfo: The connection string/DSN passed to
            ``psycopg.connect`` (e.g.
            ``"postgresql://user:pass@localhost/dbname"``).
        table: The name of the table backing this store.
        **kwargs: Additional keyword arguments to pass to
            ``psycopg.connect``.

    Example:
        ```pycon
        >>> from persista.store import PostgresStore
        >>> store = PostgresStore("postgresql://user:pass@localhost/dbname")  # doctest: +SKIP
        >>> store.set_many(  # doctest: +SKIP
        ...     {
        ...         "1": {"title": "Intro to Python", "author": "Alice"},
        ...         "2": {"title": "Advanced Python", "author": "Alice"},
        ...     }
        ... )
        >>> len(store.filter(author="Alice"))  # doctest: +SKIP
        2

        ```
    """

    def _create_table_sql(self) -> sql.Composed:
        return sql.SQL("""
            CREATE TABLE IF NOT EXISTS {table} (
                key   TEXT PRIMARY KEY,
                value JSONB NOT NULL
            )
            """).format(table=self._table_ident)

    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
        return row[1]

    def _build_filter_condition(self, key: str) -> sql.Composable:
        validate_field_name(key)
        # value->>{field} extracts as text, so the bound parameter (which
        # may be an int, bool, etc.) must be cast to text to compare.
        return sql.SQL("value->>{field} = %s::text").format(field=sql.Literal(key))

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            query = sql.SQL(
                "INSERT INTO {table} ({key_col}, value) VALUES (%s, %s) "
                "ON CONFLICT ({key_col}) DO UPDATE SET value = EXCLUDED.value"
            ).format(table=self._table_ident, key_col=sql.Identifier(self._key_column))
            with self._conn.cursor() as cur:
                cur.executemany(query, [(key, Jsonb(value)) for key, value in items.items()])

        logger.debug("Added/replaced %d key-value pair(s)", len(items))


_KEY_COLUMN = "_KEY_"


class TypedPostgresStore(BasePostgresStore):
    """A Postgres-backed key-value store with an optional typed value
    schema.

    Persists values to a Postgres database and supports adding,
    retrieving, and filtering by value fields. An optional
    ``value_schema`` maps known value field names to Postgres types.
    Known fields are stored as typed columns for fast, index-friendly
    queries. Any value fields not in the schema are stored in an
    ``extra`` JSONB overflow column, so nothing is lost. Mirrors
    :class:`~persista.store.sqlite.TypedSQLiteStore`.

    Args:
        conninfo: The connection string/DSN passed to
            ``psycopg.connect``.
        table: The name of the table backing this store.
        value_schema: Optional mapping of value field names to
            Postgres type strings (e.g. ``{"author": "TEXT", "year":
            "INTEGER"}``). Fields in the schema get native typed
            columns; all other value fields go into the ``extra``
            JSONB overflow column. Defaults to ``None``, which stores
            every value field as JSONB only.
        **kwargs: Additional keyword arguments to pass to
            ``psycopg.connect``.

    Example:
        ```pycon
        >>> from persista.store import TypedPostgresStore
        >>> schema = {"author": "TEXT", "year": "INTEGER"}
        >>> store = TypedPostgresStore(  # doctest: +SKIP
        ...     "postgresql://user:pass@localhost/dbname", value_schema=schema
        ... )
        >>> store.set_many(  # doctest: +SKIP
        ...     {
        ...         "1": {"title": "Intro to Python", "author": "Alice", "year": 2022},
        ...         "2": {"title": "History of Rome", "author": "Bob", "year": 2021},
        ...     }
        ... )
        >>> len(store.filter(author="Alice"))  # doctest: +SKIP
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

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            query = self._build_insert()
            with self._conn.cursor() as cur:
                cur.executemany(
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
