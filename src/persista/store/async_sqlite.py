r"""Provide a SQLite-backed implementation of ``AsyncBaseStore``,
storing values as JSON."""

from __future__ import annotations

__all__ = ["AsyncBaseSQLiteStore", "AsyncSQLiteStore", "AsyncTypedSQLiteStore"]

import json
import logging
import sqlite3
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin

from persista.store.base import AsyncBaseStore
from persista.store.validation import (
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
)
from persista.utils.imports import check_aiosqlite, is_aiosqlite_available

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Mapping
    from pathlib import Path

    from typing_extensions import Self

    from persista.store.types import OnConflict

if is_aiosqlite_available():  # pragma: no cover
    import aiosqlite

logger: logging.Logger = logging.getLogger(__name__)


class AsyncBaseSQLiteStore(AsyncBaseStore, MultilineDisplayMixin):
    r"""Define a base class for SQLite-backed asynchronous key-value
    stores.

    Mirrors :class:`~persista.store.sqlite.BaseSQLiteStore`, but runs
    every query through :mod:`aiosqlite` instead of the blocking
    :mod:`sqlite3` driver, so it can be awaited from an async
    application without stalling the event loop on disk I/O.

    A single ``store`` table backs every value; the primary key
    column is named by :attr:`_key_column`. :meth:`get`,
    :meth:`get_many`, :meth:`filter`, and :meth:`iter_batches` all
    query the full row and hand it to :meth:`_row_to_value` to turn
    it back into a value dict, which is what lets subclasses differ
    in how a value is laid out across columns without duplicating any
    of the surrounding query logic.

    Subclasses only need to implement :meth:`_create_table_sql`,
    :meth:`_row_to_value`, :meth:`_build_filter_condition`, and
    :meth:`_set_many` (see :class:`AsyncSQLiteStore` for a JSON-only
    layout).

    The table schema is created lazily, on the first query, rather
    than in the constructor -- ``__init__`` cannot ``await``, and
    :func:`aiosqlite.connect` itself connects lazily on first use, so
    there's no synchronous point at which the schema could be
    created eagerly.

    The constructor mirrors :func:`aiosqlite.connect`: the first
    positional argument is the ``database`` argument (a path,
    ``":memory:"``, or a ``file:`` URI when ``uri=True`` is passed),
    and any additional keyword arguments are forwarded as-is. Use
    :meth:`from_path` for a more convenient constructor that builds
    the appropriate URI for you, including read-only access.

    Requires the optional ``aiosqlite`` dependency
    (``pip install aiosqlite``).

    Args:
        database: The ``database`` argument passed to
            ``aiosqlite.connect`` (path, ``":memory:"``, or ``file:``
            URI).
        **kwargs: Additional keyword arguments to pass to
            ``aiosqlite.connect`` (e.g. ``uri=True``, ``timeout``).
    """

    #: Name of the table's primary key column.
    _key_column: str = "key"

    def __init__(self, database: Path | str, **kwargs: Any) -> None:
        check_aiosqlite()
        self._database = database
        self._kwargs = kwargs
        self._closed = False
        self._conn = aiosqlite.connect(database, **kwargs)
        self._connected = False
        self._schema_ready = False

    async def _ensure_schema(self) -> None:
        """Connect to the database and create the store's table if it
        doesn't already exist.

        Called lazily before every query, since neither the
        connection nor the table can be established eagerly in
        ``__init__`` (see the class docstring). Also called again
        each time the store is reopened via :meth:`__aenter__` after
        being closed.
        """
        if not self._connected:
            await self._conn
            self._connected = True
        if self._schema_ready:
            return
        try:
            await self._conn.execute(self._create_table_sql())
            await self._conn.commit()
        except sqlite3.OperationalError:
            # Connection is read-only (e.g. opened via a `mode=ro` URI);
            # assume the table already exists.
            pass
        self._schema_ready = True

    @abstractmethod
    def _create_table_sql(self) -> str:
        """Return the ``CREATE TABLE IF NOT EXISTS`` statement for this
        store's schema."""

    @abstractmethod
    def _row_to_value(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a raw ``SELECT * FROM store`` row back to a value
        dict."""

    @abstractmethod
    def _build_filter_condition(self, key: str) -> str:
        """Build the SQL condition fragment (with a single ``?``
        placeholder) that matches value field ``key`` against a bound
        parameter."""

    @abstractmethod
    async def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        """Write ``items`` to the table, replacing any existing row for
        the same key."""

    @classmethod
    def from_path(cls, path: Path | str, *, read_only: bool = False, **kwargs: Any) -> Self:
        """Construct a store from a file path.

        Builds the appropriate ``file:`` URI for ``aiosqlite.connect``,
        including read-only access, so callers don't need to
        construct SQLite URIs themselves.

        Args:
            path: Path to the SQLite file, or ``":memory:"`` for an
                in-memory database (useful for testing).
            read_only: If ``True``, open the database in read-only
                mode. The database file must already exist.
            **kwargs: Additional keyword arguments to pass to the
                constructor (and, from there, to ``aiosqlite.connect``).

        Returns:
            A new store connected to ``path``.
        """
        if str(path) == ":memory:":
            uri = "file::memory:?cache=shared"
        elif read_only:
            uri = f"file:{path}?mode=ro"
        else:
            uri = f"file:{path}?mode=rwc"
        return cls(uri, uri=True, **kwargs)

    async def close(self) -> None:
        if self._closed:
            return
        logger.info("Closing SQLite at %s", self._database)
        await self._conn.close()
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    async def get(self, key: str) -> dict[str, Any] | None:
        await self._ensure_schema()
        cursor = await self._conn.execute(
            f"SELECT * FROM store WHERE {self._key_column} = ?",  # noqa: S608
            (key,),
        )
        row = await cursor.fetchone()
        return self._row_to_value(row) if row else None

    async def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        await self._ensure_schema()
        placeholders = ", ".join("?" * len(keys))
        cursor = await self._conn.execute(
            f"SELECT * FROM store WHERE {self._key_column} IN ({placeholders})",  # noqa: S608
            keys,
        )
        rows = await cursor.fetchall()
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
            cursor = await self._conn.execute("SELECT * FROM store")
            rows = await cursor.fetchall()
            return [self._row_to_value(row) for row in rows]

        conditions = [self._build_filter_condition(key) for key in field_filters]
        where = " AND ".join(conditions)
        cursor = await self._conn.execute(
            f"SELECT * FROM store WHERE {where}",  # noqa: S608
            list(field_filters.values()),
        )
        rows = await cursor.fetchall()
        return [self._row_to_value(row) for row in rows]

    async def delete(self, key: str) -> None:
        await self._ensure_schema()
        await self._conn.execute(
            f"DELETE FROM store WHERE {self._key_column} = ?",  # noqa: S608
            (key,),
        )
        await self._conn.commit()

    async def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        await self._ensure_schema()
        placeholders = ", ".join("?" * len(keys))
        await self._conn.execute(
            f"DELETE FROM store WHERE {self._key_column} IN ({placeholders})",  # noqa: S608
            keys,
        )
        await self._conn.commit()

    async def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        if not keys:
            return [], []
        await self._ensure_schema()
        placeholders = ", ".join("?" * len(keys))
        cursor = await self._conn.execute(
            f"SELECT {self._key_column} FROM store "  # noqa: S608
            f"WHERE {self._key_column} IN ({placeholders})",
            keys,
        )
        existing = {row[0] for row in await cursor.fetchall()}
        found = [key for key in keys if key in existing]
        missing = [key for key in keys if key not in existing]
        return found, missing

    async def keys(self) -> AsyncIterator[str]:
        await self._ensure_schema()
        cursor = await self._conn.execute(f"SELECT {self._key_column} FROM store")  # noqa: S608
        async for (key,) in cursor:
            yield key

    async def iter_batches(
        self, batch_size: int = 32
    ) -> AsyncGenerator[dict[str, dict[str, Any]], None]:
        validate_batch_size(batch_size)
        await self._ensure_schema()
        cursor = await self._conn.execute("SELECT * FROM store")
        batch: dict[str, dict[str, Any]] = {}
        async for row in cursor:
            batch[row[0]] = self._row_to_value(row)
            if len(batch) >= batch_size:
                yield batch
                batch = {}
        if batch:
            yield batch

    async def count(self) -> int:
        await self._ensure_schema()
        cursor = await self._conn.execute("SELECT COUNT(*) FROM store")
        row = await cursor.fetchone()
        # COUNT(*) always returns exactly one row.
        return row[0]  # type: ignore[index]

    async def get_columns_info(self) -> dict[str, str]:
        """Return the column names and types of the store's table.

        Returns:
            A mapping of column name to SQLite declared type.
        """
        await self._ensure_schema()
        cursor = await self._conn.execute("PRAGMA table_info(store)")
        rows = await cursor.fetchall()
        # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
        return {row[1]: row[2] for row in rows}

    async def show_columns_info(self) -> None:
        """Print the store's table column names and types to stdout.

        This is a convenience wrapper around :meth:`get_columns_info`
        for interactive/debugging use. For programmatic access, use
        :meth:`get_columns_info` instead.
        """
        for name, dtype in (await self.get_columns_info()).items():
            logger.info(f"{name}\t{dtype}")

    def _get_repr_kwargs(self) -> dict[str, Any]:
        # `count` is intentionally omitted: computing it requires an
        # awaited query, which isn't available from this sync method.
        return {"database": self._database, "closed": self._closed} | self._kwargs

    async def __aenter__(self) -> Self:
        if self._closed:
            self._conn = aiosqlite.connect(self._database, **self._kwargs)
            self._closed = False
            self._connected = False
            self._schema_ready = False
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()


_CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS store (
        key   TEXT PRIMARY KEY,
        value JSON NOT NULL
    )
"""


class AsyncSQLiteStore(AsyncBaseSQLiteStore):
    """An asynchronous SQLite-backed key-value store.

    Persists values to a SQLite database and supports adding,
    retrieving, filtering, and deleting key-value pairs. Each value
    is stored as a JSON column (using SQLite's built-in ``json1``
    functions), which provides flexibility for arbitrary value
    fields without requiring a fixed schema. Mirrors
    :class:`~persista.store.sqlite.SQLiteStore`, but every method is
    a coroutine, backed by :mod:`aiosqlite` instead of the blocking
    :mod:`sqlite3` driver.

    The constructor mirrors :func:`aiosqlite.connect` directly. For
    the common case of opening a file by path (optionally read-only),
    use :meth:`~AsyncBaseSQLiteStore.from_path` instead.

    Requires the optional ``aiosqlite`` dependency
    (``pip install aiosqlite``).

    Args:
        database: The ``database`` argument passed to
            ``aiosqlite.connect`` (path, ``":memory:"``, or ``file:``
            URI).
        **kwargs: Additional keyword arguments to pass to
            ``aiosqlite.connect``.

    Example:
        ```pycon
        >>> import asyncio
        >>> from persista.store import AsyncSQLiteStore
        >>> async def main():
        ...     store = AsyncSQLiteStore(":memory:")
        ...     await store.set_many(
        ...         {
        ...             "1": {"title": "Intro to Python", "author": "Alice"},
        ...             "2": {"title": "Advanced Python", "author": "Alice"},
        ...             "3": {"title": "History of Rome", "author": "Bob"},
        ...         }
        ...     )
        ...     result = await store.filter(author="Alice")
        ...     print(len(result))
        ...     await store.close()
        ...
        >>> asyncio.run(main())
        2

        ```
    """

    def __init__(self, database: Path | str = ":memory:", **kwargs: Any) -> None:
        super().__init__(database, **kwargs)

    def _create_table_sql(self) -> str:
        return _CREATE_TABLE

    def _row_to_value(self, row: sqlite3.Row) -> dict[str, Any]:
        return json.loads(row[1])

    def _build_filter_condition(self, key: str) -> str:
        validate_field_name(key)
        return f"json_extract(value, '$.{key}') = ?"

    async def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            await self._conn.executemany(
                "INSERT OR REPLACE INTO store VALUES (?, ?)",
                [(key, json.dumps(value)) for key, value in items.items()],
            )
            await self._conn.commit()

        logger.debug("Added/replaced %d key-value pair(s)", len(items))


_KEY_COLUMN = "_KEY_"


class AsyncTypedSQLiteStore(AsyncBaseSQLiteStore):
    """An asynchronous SQLite-backed key-value store with an optional
    typed value schema.

    Persists values to a SQLite database and supports adding,
    retrieving, and filtering by value fields. An optional
    ``value_schema`` maps known value field names to SQLite types.
    Known fields are stored as typed columns for fast, index-friendly
    queries. Any value fields not in the schema are stored in an
    ``extra`` JSON overflow column, so nothing is lost. Mirrors
    :class:`~persista.store.sqlite.TypedSQLiteStore`, but every
    method is a coroutine, backed by :mod:`aiosqlite` instead of the
    blocking :mod:`sqlite3` driver.

    The constructor mirrors :func:`aiosqlite.connect` directly (plus
    the ``value_schema`` argument). For the common case of opening a
    file by path (optionally read-only), use
    :meth:`~AsyncBaseSQLiteStore.from_path` instead.

    Requires the optional ``aiosqlite`` dependency
    (``pip install aiosqlite``).

    Args:
        database: The ``database`` argument passed to
            ``aiosqlite.connect`` (path, ``":memory:"``, or ``file:``
            URI).
        value_schema: Optional mapping of value field names to SQLite
            type strings (e.g. ``{"author": "TEXT", "year":
            "INTEGER"}``). Fields in the schema get native typed
            columns; all other value fields go into the ``extra``
            JSON overflow column. Defaults to ``None``, which stores
            every value field as JSON only.
        **kwargs: Additional keyword arguments to pass to
            ``aiosqlite.connect``.

    Example:
        ```pycon
        >>> import asyncio
        >>> from persista.store import AsyncTypedSQLiteStore
        >>> async def main():
        ...     schema = {"author": "TEXT", "year": "INTEGER", "category": "TEXT"}
        ...     store = AsyncTypedSQLiteStore(":memory:", value_schema=schema)
        ...     await store.set_many(
        ...         {
        ...             "1": {"title": "Intro to Python", "author": "Alice"},
        ...             "2": {"title": "Advanced Python", "author": "Alice"},
        ...             "3": {"title": "History of Rome", "author": "Bob"},
        ...         }
        ...     )
        ...     result = await store.filter(author="Alice")
        ...     print(len(result))
        ...     await store.close()
        ...
        >>> asyncio.run(main())
        2

        ```
    """

    _key_column = _KEY_COLUMN

    def __init__(
        self,
        database: Path | str = ":memory:",
        value_schema: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        value_schema = value_schema or {}
        if _KEY_COLUMN in value_schema:
            msg = f"value_schema must not contain the reserved key column name {_KEY_COLUMN!r}"
            raise ValueError(msg)
        self._schema: dict[str, str] = value_schema
        super().__init__(database, **kwargs)

    def _create_table_sql(self) -> str:
        typed_cols = "".join(f", {name} {dtype}" for name, dtype in self._schema.items())
        return (
            f"CREATE TABLE IF NOT EXISTS store "
            f"({_KEY_COLUMN} TEXT PRIMARY KEY{typed_cols}, extra JSON)"
        )

    def _row_to_value(self, row: sqlite3.Row) -> dict[str, Any]:
        # row layout: key, [schema cols...], extra
        schema_vals = dict(zip(self._schema.keys(), row[1 : 1 + len(self._schema)], strict=True))
        extra_json = row[1 + len(self._schema)]
        value = {k: v for k, v in schema_vals.items() if v is not None}
        if extra_json:
            value.update(json.loads(extra_json))
        return value

    def _build_filter_condition(self, key: str) -> str:
        if key in self._schema:
            return f"{key} = ?"
        validate_field_name(key)
        return f"json_extract(extra, '$.{key}') = ?"

    async def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            await self._conn.executemany(
                self._build_insert(),
                [self._value_to_row(key, value) for key, value in items.items()],
            )
            await self._conn.commit()

        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    # ---------------------------------------------------------------------------
    # Private helpers
    # ---------------------------------------------------------------------------

    def _build_insert(self) -> str:
        """Build the INSERT OR REPLACE statement from the schema."""
        col_names = [_KEY_COLUMN, *self._schema.keys(), "extra"]
        placeholders = ", ".join("?" * len(col_names))
        return f"INSERT OR REPLACE INTO store ({', '.join(col_names)}) VALUES ({placeholders})"  # noqa: S608

    def _value_to_row(self, key: str, value: dict[str, Any]) -> tuple:
        """Convert a key-value pair to an INSERT row tuple."""
        known = [value.get(k) for k in self._schema]
        extra = {k: v for k, v in value.items() if k not in self._schema}
        return (key, *known, json.dumps(extra) if extra else None)
