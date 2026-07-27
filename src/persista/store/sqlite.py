r"""Provide a SQLite-backed implementation of ``BaseStore``, storing
values as JSON."""

from __future__ import annotations

__all__ = ["BaseSQLiteStore", "PickleSQLiteStore", "SQLiteStore", "TypedSQLiteStore"]

import asyncio
import json
import logging
import pickle
import sqlite3
import threading
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.path import sanitize_path

from persista.store.base import BaseStore
from persista.store.uri import decode_path_uri, encode_path_uri
from persista.store.validation import (
    aresolve_conflicts,
    normalize_on_conflict,
    resolve_conflicts,
    validate_batch_size,
    validate_field_name,
    validate_value_schema,
)
from persista.utils.imports import is_aiosqlite_available
from persista.utils.path import prepare_store_path

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator, Iterator, Mapping
    from pathlib import Path

    from typing_extensions import Self

    from persista.store.types import OnConflict

if is_aiosqlite_available():  # pragma: no cover
    import aiosqlite

logger: logging.Logger = logging.getLogger(__name__)

_STOP_ITERATION = object()

# Conservative default for SQLITE_MAX_VARIABLE_NUMBER: older SQLite builds
# default to 999 bound parameters per statement, so batch methods chunk
# IN (...) clauses to stay well under that regardless of how the sqlite3
# extension was compiled.
_MAX_SQL_VARIABLES = 900


def _chunk(items: list[Any], size: int) -> Iterator[list[Any]]:
    """Yield ``items`` in chunks of at most ``size`` elements."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _next_or_stop(iterator: Iterator[Any]) -> Any:
    """Advance ``iterator``, returning a sentinel instead of raising
    ``StopIteration``.

    Needed because :func:`asyncio.to_thread` runs ``next`` in a worker
    thread and hands its result back through a :class:`asyncio.Future`,
    which isn't allowed to carry a ``StopIteration`` (PEP 479):
    propagating it as-is surfaces as an opaque ``RuntimeError`` instead
    of the ``StopIteration`` callers expect to catch.
    """
    try:
        return next(iterator)
    except StopIteration:
        return _STOP_ITERATION


class BaseSQLiteStore(BaseStore, MultilineDisplayMixin):
    r"""Define a base class for SQLite-backed key-value stores.

    A single ``store`` table backs every value; the primary key
    column is named by :attr:`_key_column`. :meth:`get`,
    :meth:`get_many`, :meth:`filter`, and :meth:`iter_batches` all
    query the full row and hand it to :meth:`_row_to_value` to turn
    it back into a value dict, which is what lets subclasses differ
    in how a value is laid out across columns (a single JSON column
    vs. typed columns plus a JSON overflow column) without
    duplicating any of the surrounding query logic.

    Subclasses only need to implement :meth:`_create_table_sql`,
    :meth:`_row_to_value`, :meth:`_filter_expr`, and
    :meth:`_set_many` (see :class:`SQLiteStore` for a JSON-only
    layout and :class:`~persista.store.sqlite_typed.TypedSQLiteStore`
    for an optionally typed one).

    The constructor mirrors :func:`sqlite3.connect`: the first
    positional argument is the ``database`` argument accepted by
    ``sqlite3.connect`` (a path, ``":memory:"``, or a ``file:`` URI
    when ``uri=True`` is passed), and any additional keyword
    arguments are forwarded as-is.  Use :meth:`from_path` for a more
    convenient constructor that builds the appropriate URI for you,
    including read-only access.

    Args:
        database: The ``database`` argument passed to
            ``sqlite3.connect`` (path, ``":memory:"``, or ``file:`` URI).
        **kwargs: Additional keyword arguments to pass to
            ``sqlite3.connect`` (e.g. ``uri=True``, ``timeout``,
            ``check_same_thread``).
    """

    #: Name of the table's primary key column.
    _key_column: str = "key"

    #: URI scheme used by :meth:`to_uri`/:meth:`from_uri`.
    _scheme: str = "sqlite"

    def __init__(self, database: Path | str, **kwargs: Any) -> None:
        self._database = database
        # Plain path/":memory:" identifier used by to_uri(). Overridden by
        # from_path() when database is instead the wrapped `file:...` URI
        # that sqlite3.connect() expects, so to_uri()/from_uri() round-trip
        # the original path rather than double-wrapping it.
        self._path_for_uri: Path | str = database
        self._kwargs = kwargs
        self._closed = True
        # Guards every access to self._conn: the no-aiosqlite async fallback
        # runs sync methods via asyncio.to_thread, which can execute
        # concurrently on the same sqlite3.Connection from different OS
        # threads -- unsafe regardless of check_same_thread. Reentrant so
        # set_many can hold it across the whole check-then-act sequence for
        # on_conflict != "overwrite" (which calls self.get/self.contains_many,
        # themselves taking the lock) while still serializing against other
        # threads for the entire operation.
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._aconn: aiosqlite.Connection | None = None
        self._aconn_lock = asyncio.Lock()
        self._awrite_lock = asyncio.Lock()
        self._aschema_ready = False

    def _check_open(self) -> None:
        if self._closed:
            msg = (
                f"{type(self).__name__} is not open; call open()/aopen() or use it as a "
                "context manager."
            )
            raise RuntimeError(msg)

    def open(self) -> None:
        if not self._closed:
            return
        self._conn = self._connect()
        self._ensure_schema()
        self._aschema_ready = False
        self._closed = False

    async def aopen(self) -> None:
        if not self._closed:
            return
        await asyncio.to_thread(self.open)

    async def _ensure_aconn(self) -> aiosqlite.Connection:
        """Lazily open (and schema-initialize) the aiosqlite connection.

        Only called when :func:`is_aiosqlite_available` is ``True``;
        callers must check that first and fall back to
        ``asyncio.to_thread`` otherwise (see e.g. :meth:`aget`).
        """
        self._check_open()
        async with self._aconn_lock:
            if self._aconn is None:
                self._aconn = await aiosqlite.connect(self._database, **self._kwargs)
            if not self._aschema_ready:
                try:
                    await self._aconn.execute(self._create_table_sql())
                    await self._aconn.commit()
                except sqlite3.OperationalError:
                    pass
                self._aschema_ready = True
        return self._aconn

    def _connect(self) -> sqlite3.Connection:
        """Open the sync ``sqlite3`` connection.

        Defaults ``check_same_thread`` to ``False`` (unless the caller
        already specified it via constructor kwargs) so that the
        no-``aiosqlite`` fallback -- which runs the sync methods on
        this same connection via ``asyncio.to_thread``, i.e. from a
        worker thread rather than the thread that opened the
        connection -- doesn't hit sqlite3's default same-thread
        check. Callers doing genuinely concurrent multi-threaded
        access of their own are still responsible for serializing it
        themselves; SQLite's own per-connection lock keeps individual
        statements safe either way.
        """
        connect_kwargs = {"check_same_thread": False, **self._kwargs}
        return sqlite3.connect(self._database, **connect_kwargs)

    def _ensure_schema(self) -> None:
        """Create the store's table if it doesn't already exist.

        Called once from ``__init__`` and again each time the store is
        reopened via :meth:`__enter__` after being closed. A
        ``:memory:`` database starts empty every time it is
        (re)connected to, so this is what makes reopening a closed in-
        memory store behave like a reset rather than resuming where it
        left off.
        """
        try:
            with self._lock:
                self._conn.execute(self._create_table_sql())
                self._conn.commit()
        except sqlite3.OperationalError:
            # Connection is read-only (e.g. opened via a `mode=ro` URI);
            # assume the table already exists.
            pass

    @abstractmethod
    def _create_table_sql(self) -> str:
        """Return the ``CREATE TABLE IF NOT EXISTS`` statement for this
        store's schema."""

    @abstractmethod
    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
        """Convert a raw ``SELECT * FROM store`` row back to a value
        dict."""

    @abstractmethod
    def _filter_expr(self, key: str) -> str:
        """Build the SQL expression that extracts value field ``key``
        for use in a ``filter()``/``afilter()`` condition.

        The expression is combined with either ``= ?`` (with the
        expected value bound as a parameter) or ``IS NULL`` (with no
        bound parameter), depending on whether the expected value for
        ``key`` is ``None`` -- SQL's ``NULL = ?`` never evaluates to
        true even when the bound parameter is ``NULL``, so matching an
        explicitly-stored JSON ``null`` requires ``IS NULL`` instead.
        """

    @abstractmethod
    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        """Write ``items`` to the table, replacing any existing row for
        the same key."""

    @abstractmethod
    async def _aset_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        """Async equivalent of :meth:`_set_many`, using the lazily
        opened ``aiosqlite`` connection."""

    @classmethod
    def from_path(cls, path: Path | str, *, read_only: bool = False, **kwargs: Any) -> Self:
        """Construct a store from a file path.

        Builds the appropriate ``file:`` URI for ``sqlite3.connect``,
        including read-only access, so callers don't need to
        construct SQLite URIs themselves.

        Args:
            path: Path to the SQLite file, or ``":memory:"`` for an
                in-memory database (useful for testing).
            read_only: If ``True``, open the database in read-only
                mode. The database file must already exist.
            **kwargs: Additional keyword arguments to pass to the
                constructor (and, from there, to ``sqlite3.connect``).

        Returns:
            A new store connected to ``path``.

        Example:
            ```pycon
            >>> import tempfile
            >>> from persista.store import SQLiteStore
            >>> with tempfile.TemporaryDirectory() as tmpdir:
            ...     store = SQLiteStore.from_path(f"{tmpdir}/data.db")
            ...     store.open()
            ...     store.set("1", {"title": "Intro to Python"})
            ...     store.get("1")
            ...     store.close()
            ...
            {'title': 'Intro to Python'}

            ```
        """
        if str(path) == ":memory:":
            uri = "file::memory:?cache=shared"
        elif read_only:
            # Sanitize (but don't create parent directories for) the path so
            # to_uri() returns the same absolute form regardless of read_only,
            # rather than an unresolved path that only round-trips correctly
            # from the same working directory.
            path = sanitize_path(path)
            uri = f"file:{path}?mode=ro"
        else:
            path = prepare_store_path(path)
            uri = f"file:{path}?mode=rwc"
        store = cls(uri, uri=True, **kwargs)
        store._path_for_uri = path
        return store

    def to_uri(self) -> str:
        return encode_path_uri(self._scheme, str(self._path_for_uri))

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:
        path = decode_path_uri(uri, expected_scheme=cls._scheme)
        return cls.from_path(path, read_only=read_only)

    def _close_aconn_sync(self) -> None:
        """Close ``self._aconn`` from a synchronous context.

        Must only be called when no event loop is currently running.
        """
        try:
            asyncio.run(self._aconn.close())
        except RuntimeError:
            # The event loop that owned the async connection (e.g. a
            # per-test loop managed by pytest-asyncio) is already
            # closed, so the underlying connection is already gone;
            # there is nothing more to clean up.
            logger.debug(
                "Async SQLite connection for %s could not be closed "
                "cleanly because its event loop is already closed",
                self._database,
            )
        self._aconn = None

    def close(self) -> None:
        if self._aconn is not None:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                self._close_aconn_sync()
            else:
                msg = (
                    "An async SQLite connection is open and close() was called from "
                    "inside a running event loop; use `await store.aclose()` instead."
                )
                raise RuntimeError(msg)
        if self._closed:
            return
        logger.info("Closing SQLite at %s", self._database)
        with self._lock:
            self._conn.close()
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def get(self, key: str) -> dict[str, Any] | None:
        self._check_open()
        with self._lock:
            row = self._conn.execute(
                f"SELECT * FROM store WHERE {self._key_column} = ?",  # noqa: S608
                (key,),
            ).fetchone()
        return self._row_to_value(row) if row else None

    async def aget(self, key: str) -> dict[str, Any] | None:
        if not is_aiosqlite_available():
            return await asyncio.to_thread(self.get, key)
        conn = await self._ensure_aconn()
        cursor = await conn.execute(
            f"SELECT * FROM store WHERE {self._key_column} = ?",  # noqa: S608
            (key,),
        )
        row = await cursor.fetchone()
        return self._row_to_value(row) if row else None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        self._check_open()
        if not keys:
            return []
        by_key: dict[str, dict[str, Any]] = {}
        for chunk in _chunk(keys, _MAX_SQL_VARIABLES):
            placeholders = ", ".join("?" * len(chunk))
            with self._lock:
                rows = self._conn.execute(
                    f"SELECT * FROM store WHERE {self._key_column} IN ({placeholders})",  # noqa: S608
                    chunk,
                ).fetchall()
            by_key.update((row[0], self._row_to_value(row)) for row in rows)
        return [by_key.get(key) for key in keys]

    async def aget_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        if not is_aiosqlite_available():
            return await asyncio.to_thread(self.get_many, keys)
        conn = await self._ensure_aconn()
        by_key: dict[str, dict[str, Any]] = {}
        for chunk in _chunk(keys, _MAX_SQL_VARIABLES):
            placeholders = ", ".join("?" * len(chunk))
            cursor = await conn.execute(
                f"SELECT * FROM store WHERE {self._key_column} IN ({placeholders})",  # noqa: S608
                chunk,
            )
            rows = await cursor.fetchall()
            by_key.update((row[0], self._row_to_value(row)) for row in rows)
        return [by_key.get(key) for key in keys]

    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
        self.set_many({key: value}, on_conflict=on_conflict)

    async def aset(
        self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite"
    ) -> None:
        await self.aset_many({key: value}, on_conflict=on_conflict)

    def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        self._check_open()
        if not items:
            return
        on_conflict = normalize_on_conflict(on_conflict)
        if on_conflict == "overwrite":
            self._set_many(items)
            return

        # Hold the (reentrant) connection lock across the whole
        # check-then-act sequence so a concurrent set/set_many on the same
        # keys (whether from another thread here, or the no-aiosqlite async
        # fallback) can't interleave between the conflict check and the
        # write.
        with self._lock:
            to_write = resolve_conflicts(items, on_conflict, self.contains_many, self.get)
            self._set_many(to_write)

    async def aset_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        if not items:
            return
        if not is_aiosqlite_available():
            await asyncio.to_thread(self.set_many, items, on_conflict)
            return
        on_conflict = normalize_on_conflict(on_conflict)
        if on_conflict == "overwrite":
            await self._aset_many(items)
            return

        # The native aiosqlite path uses a separate connection
        # (self._aconn). Serialize its own check-then-act sequence with a
        # dedicated lock -- self._aconn_lock can't be reused here since
        # self.aget/self.acontains_many (called from aresolve_conflicts)
        # each acquire it internally via _ensure_aconn, and asyncio.Lock
        # isn't reentrant.
        async with self._awrite_lock:
            to_write = await aresolve_conflicts(items, on_conflict, self.acontains_many, self.aget)
            await self._aset_many(to_write)

    def _build_filter_where(self, field_filters: Mapping[str, Any]) -> tuple[str, list[Any]]:
        """Build the ``WHERE`` clause and bound parameters for
        ``field_filters``, matching ``None`` expected values against
        ``IS NULL`` instead of a bound ``= ?`` parameter."""
        conditions: list[str] = []
        values: list[Any] = []
        for key, expected in field_filters.items():
            expr = self._filter_expr(key)
            if expected is None:
                conditions.append(f"{expr} IS NULL")
            else:
                conditions.append(f"{expr} = ?")
                values.append(expected)
        return " AND ".join(conditions), values

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        self._check_open()
        if not field_filters:
            with self._lock:
                rows = self._conn.execute("SELECT * FROM store").fetchall()
            return [self._row_to_value(row) for row in rows]

        where, values = self._build_filter_where(field_filters)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM store WHERE {where}",  # noqa: S608
                values,
            ).fetchall()
        return [self._row_to_value(row) for row in rows]

    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not is_aiosqlite_available():
            return await asyncio.to_thread(lambda: self.filter(**field_filters))
        conn = await self._ensure_aconn()
        if not field_filters:
            cursor = await conn.execute("SELECT * FROM store")
            rows = await cursor.fetchall()
            return [self._row_to_value(row) for row in rows]

        where, values = self._build_filter_where(field_filters)
        cursor = await conn.execute(
            f"SELECT * FROM store WHERE {where}",  # noqa: S608
            values,
        )
        rows = await cursor.fetchall()
        return [self._row_to_value(row) for row in rows]

    def delete(self, key: str) -> None:
        self._check_open()
        with self._lock:
            self._conn.execute(
                f"DELETE FROM store WHERE {self._key_column} = ?",  # noqa: S608
                (key,),
            )
            self._conn.commit()

    async def adelete(self, key: str) -> None:
        if not is_aiosqlite_available():
            await asyncio.to_thread(self.delete, key)
            return
        conn = await self._ensure_aconn()
        await conn.execute(f"DELETE FROM store WHERE {self._key_column} = ?", (key,))  # noqa: S608
        await conn.commit()

    def delete_many(self, keys: list[str]) -> None:
        self._check_open()
        if not keys:
            return
        with self._lock:
            for chunk in _chunk(keys, _MAX_SQL_VARIABLES):
                placeholders = ", ".join("?" * len(chunk))
                self._conn.execute(
                    f"DELETE FROM store WHERE {self._key_column} IN ({placeholders})",  # noqa: S608
                    chunk,
                )
            self._conn.commit()

    async def adelete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        if not is_aiosqlite_available():
            await asyncio.to_thread(self.delete_many, keys)
            return
        conn = await self._ensure_aconn()
        for chunk in _chunk(keys, _MAX_SQL_VARIABLES):
            placeholders = ", ".join("?" * len(chunk))
            await conn.execute(
                f"DELETE FROM store WHERE {self._key_column} IN ({placeholders})",  # noqa: S608
                chunk,
            )
        await conn.commit()

    def clear(self) -> None:
        self._check_open()
        with self._lock:
            self._conn.execute("DELETE FROM store")
            self._conn.commit()

    async def aclear(self) -> None:
        if not is_aiosqlite_available():
            await asyncio.to_thread(self.clear)
            return
        conn = await self._ensure_aconn()
        await conn.execute("DELETE FROM store")
        await conn.commit()

    def contains(self, key: str) -> bool:
        self._check_open()
        with self._lock:
            row = self._conn.execute(
                f"SELECT 1 FROM store WHERE {self._key_column} = ? LIMIT 1",  # noqa: S608
                [key],
            ).fetchone()
        return row is not None

    async def acontains(self, key: str) -> bool:
        if not is_aiosqlite_available():
            return await asyncio.to_thread(self.contains, key)
        conn = await self._ensure_aconn()
        cursor = await conn.execute(
            f"SELECT 1 FROM store WHERE {self._key_column} = ? LIMIT 1",  # noqa: S608
            [key],
        )
        return await cursor.fetchone() is not None

    def contains_many(self, keys: list[str]) -> list[bool]:
        self._check_open()
        if not keys:
            return []
        existing: set[str] = set()
        for chunk in _chunk(keys, _MAX_SQL_VARIABLES):
            placeholders = ", ".join("?" * len(chunk))
            with self._lock:
                rows = self._conn.execute(
                    f"SELECT {self._key_column} FROM store "  # noqa: S608
                    f"WHERE {self._key_column} IN ({placeholders})",
                    chunk,
                ).fetchall()
            existing.update(row[0] for row in rows)
        return [key in existing for key in keys]

    async def acontains_many(self, keys: list[str]) -> list[bool]:
        if not keys:
            return []
        if not is_aiosqlite_available():
            return await asyncio.to_thread(self.contains_many, keys)
        conn = await self._ensure_aconn()
        existing: set[str] = set()
        for chunk in _chunk(keys, _MAX_SQL_VARIABLES):
            placeholders = ", ".join("?" * len(chunk))
            cursor = await conn.execute(
                f"SELECT {self._key_column} FROM store "  # noqa: S608
                f"WHERE {self._key_column} IN ({placeholders})",
                chunk,
            )
            existing.update(row[0] for row in await cursor.fetchall())
        return [key in existing for key in keys]

    def keys(self) -> Iterator[str]:
        self._check_open()
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._key_column} FROM store"  # noqa: S608
            ).fetchall()
        for (key,) in rows:
            yield key

    async def akeys(self) -> AsyncIterator[str]:
        if not is_aiosqlite_available():
            iterator = await asyncio.to_thread(lambda: iter(self.keys()))
            while True:
                key = await asyncio.to_thread(_next_or_stop, iterator)
                if key is _STOP_ITERATION:
                    return
                yield key
        conn = await self._ensure_aconn()
        cursor = await conn.execute(f"SELECT {self._key_column} FROM store")  # noqa: S608
        async for (key,) in cursor:
            yield key

    def iter_batches(
        self, batch_size: int = 32
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        validate_batch_size(batch_size)
        self._check_open()
        sql = f"SELECT * FROM store ORDER BY {self._key_column} LIMIT ? OFFSET ?"  # noqa: S608
        offset = 0
        while True:
            with self._lock:
                rows = self._conn.execute(sql, (batch_size, offset)).fetchall()
            if not rows:
                return
            yield {row[0]: self._row_to_value(row) for row in rows}
            if len(rows) < batch_size:
                return
            offset += batch_size

    async def aiter_batches(self, batch_size: int = 32) -> AsyncIterator[dict[str, dict[str, Any]]]:
        validate_batch_size(batch_size)
        if not is_aiosqlite_available():
            iterator = await asyncio.to_thread(
                lambda: iter(self.iter_batches(batch_size=batch_size))
            )
            while True:
                batch = await asyncio.to_thread(_next_or_stop, iterator)
                if batch is _STOP_ITERATION:
                    return
                yield batch
        conn = await self._ensure_aconn()
        cursor = await conn.execute("SELECT * FROM store")
        batch: dict[str, dict[str, Any]] = {}
        async for row in cursor:
            batch[row[0]] = self._row_to_value(row)
            if len(batch) >= batch_size:
                yield batch
                batch = {}
        if batch:
            yield batch

    def count(self) -> int:
        self._check_open()
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM store").fetchone()[0]

    async def acount(self) -> int:
        if not is_aiosqlite_available():
            return await asyncio.to_thread(self.count)
        conn = await self._ensure_aconn()
        cursor = await conn.execute("SELECT COUNT(*) FROM store")
        row = await cursor.fetchone()
        return row[0]

    async def aclose(self) -> None:
        if self._aconn is not None:
            await self._aconn.close()
            self._aconn = None
        if not self._closed:
            logger.info("Closing SQLite at %s", self._database)
            with self._lock:
                self._conn.close()
            self._closed = True

    def get_columns_info(self) -> dict[str, str]:
        """Return the column names and types of the store's table.

        Returns:
            A mapping of column name to SQLite declared type.

        Example:
            ```pycon
            >>> from persista.store import SQLiteStore
            >>> with SQLiteStore(":memory:") as store:
            ...     store.get_columns_info()
            ...
            {'key': 'TEXT', 'value': 'JSON'}

            ```
        """
        self._check_open()
        with self._lock:
            rows = self._conn.execute("PRAGMA table_info(store)").fetchall()
        # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
        return {row[1]: row[2] for row in rows}

    def show_columns_info(self) -> None:
        """Print the store's table column names and types to stdout.

        This is a convenience wrapper around :meth:`get_columns_info`
        for interactive/debugging use. For programmatic access, use
        :meth:`get_columns_info` instead.
        """
        for name, dtype in self.get_columns_info().items():
            logger.info(f"{name}\t{dtype}")

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"database": self._database, "closed": self._closed}
        if not self._closed:
            kwargs["count"] = self.count()
        return kwargs | self._kwargs


_CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS store (
        key   TEXT PRIMARY KEY,
        value JSON NOT NULL
    )
"""


class SQLiteStore(BaseSQLiteStore):
    """A SQLite-backed key-value store.

    Persists values to a SQLite database and supports adding,
    retrieving, filtering, and deleting key-value pairs.  Each value
    is stored as a JSON column (using SQLite's built-in ``json1``
    functions), which provides flexibility for arbitrary value
    fields without requiring a fixed schema.

    The constructor mirrors :func:`sqlite3.connect` directly. For the
    common case of opening a file by path (optionally read-only), use
    :meth:`from_path` instead.

    Args:
        database: The ``database`` argument passed to
            ``sqlite3.connect`` (path, ``":memory:"``, or ``file:`` URI).
        **kwargs: Additional keyword arguments to pass to
            ``sqlite3.connect``.

    Example:
        ```pycon
        >>> from persista.store import SQLiteStore
        >>> with SQLiteStore(":memory:") as store:
        ...     store.set_many(
        ...         {
        ...             "1": {
        ...                 "title": "Intro to Python",
        ...                 "author": "Alice",
        ...                 "category": "Programming",
        ...             },
        ...             "2": {
        ...                 "title": "Advanced Python",
        ...                 "author": "Alice",
        ...                 "category": "Programming",
        ...             },
        ...             "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
        ...         }
        ...     )
        ...     len(store.filter(author="Alice"))
        ...     len(store.filter(author="Alice", category="Programming"))
        ...     len(store.filter(category="History"))
        ...
        2
        2
        1

        ```
    """

    def __init__(self, database: Path | str = ":memory:", **kwargs: Any) -> None:
        super().__init__(database, **kwargs)

    def _create_table_sql(self) -> str:
        return _CREATE_TABLE

    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
        return json.loads(row[1])

    def _filter_expr(self, key: str) -> str:
        validate_field_name(key)
        return f"json_extract(value, '$.{key}')"

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            with self._lock:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO store VALUES (?, ?)",
                    [(key, json.dumps(value)) for key, value in items.items()],
                )
                self._conn.commit()

        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    async def _aset_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            conn = await self._ensure_aconn()
            await conn.executemany(
                "INSERT OR REPLACE INTO store VALUES (?, ?)",
                [(key, json.dumps(value)) for key, value in items.items()],
            )
            await conn.commit()
        logger.debug("Added/replaced %d key-value pair(s)", len(items))


_KEY_COLUMN = "_KEY_"


class TypedSQLiteStore(BaseSQLiteStore):
    """A SQLite-backed key-value store with an optional typed value
    schema.

    Persists values to a SQLite database and supports adding,
    retrieving, and filtering by value fields.  An optional
    ``value_schema`` maps known value field names to SQLite types.
    Known fields are stored as typed columns for fast, index-friendly
    queries.  Any value fields not in the schema are stored in an
    ``extra`` JSON overflow column, so nothing is lost.

    The constructor mirrors :func:`sqlite3.connect` directly (plus the
    ``value_schema`` argument). For the common case of opening a file
    by path (optionally read-only), use :meth:`from_path` instead.

    Args:
        database: The ``database`` argument passed to
            ``sqlite3.connect`` (path, ``":memory:"``, or ``file:`` URI).
        value_schema: Optional mapping of value field names to SQLite
            type strings (e.g. ``{"author": "TEXT", "year":
            "INTEGER"}``).  Fields in the schema get native typed
            columns; all other value fields go into the ``extra``
            JSON overflow column.  Defaults to ``None``, which stores
            every value field as JSON only.
        **kwargs: Additional keyword arguments to pass to
            ``sqlite3.connect``.

    Example:
        ```pycon
        >>> from persista.store import TypedSQLiteStore
        >>> schema = {"author": "TEXT", "year": "INTEGER", "category": "TEXT"}
        >>> with TypedSQLiteStore(":memory:", value_schema=schema) as store:
        ...     store.set_many(
        ...         {
        ...             "1": {
        ...                 "title": "Intro to Python",
        ...                 "author": "Alice",
        ...                 "category": "Programming",
        ...             },
        ...             "2": {
        ...                 "title": "Advanced Python",
        ...                 "author": "Alice",
        ...                 "category": "Programming",
        ...             },
        ...             "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
        ...         }
        ...     )
        ...     len(store.filter(author="Alice"))
        ...     len(store.filter(author="Alice", category="Programming"))
        ...     len(store.filter(category="History"))
        ...
        2
        2
        1

        ```

    Note:
        :meth:`from_uri` reconstructs the store with an empty
        ``value_schema``, so value fields that were stored in typed
        columns won't appear in :meth:`get`/:meth:`filter` results
        until the caller re-supplies the original ``value_schema`` to
        a fresh construction; the data itself isn't lost in the
        database, just not visible through the reconstructed store.
    """

    _key_column = _KEY_COLUMN
    _scheme = "sqlite+typed"

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
        validate_value_schema(value_schema)
        self._schema: dict[str, str] = value_schema
        super().__init__(database, **kwargs)

    def _create_table_sql(self) -> str:
        typed_cols = "".join(f", {name} {dtype}" for name, dtype in self._schema.items())
        return (
            f"CREATE TABLE IF NOT EXISTS store "
            f"({_KEY_COLUMN} TEXT PRIMARY KEY{typed_cols}, extra JSON)"
        )

    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
        # row layout: key, [schema cols...], extra
        schema_vals = dict(zip(self._schema.keys(), row[1 : 1 + len(self._schema)], strict=True))
        extra_json = row[1 + len(self._schema)]
        value = {k: v for k, v in schema_vals.items() if v is not None}
        if extra_json:
            value.update(json.loads(extra_json))
        return value

    def _filter_expr(self, key: str) -> str:
        if key in self._schema:
            return key
        validate_field_name(key)
        return f"json_extract(extra, '$.{key}')"

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            with self._lock:
                self._conn.executemany(
                    self._build_insert(),
                    [self._value_to_row(key, value) for key, value in items.items()],
                )
                self._conn.commit()

        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    async def _aset_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            conn = await self._ensure_aconn()
            await conn.executemany(
                self._build_insert(),
                [self._value_to_row(key, value) for key, value in items.items()],
            )
            await conn.commit()
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


_CREATE_TABLE_PICKLE = """
    CREATE TABLE IF NOT EXISTS store (
        key   TEXT PRIMARY KEY,
        value BLOB NOT NULL
    )
"""


class PickleSQLiteStore(BaseSQLiteStore):
    """A SQLite-backed key-value store that serializes values with
    ``pickle`` instead of JSON.

    Unlike :class:`SQLiteStore`, this store can persist arbitrary
    Python objects within a value's fields (tuples, sets, datetimes,
    custom classes, etc.), not just JSON-compatible types. The
    tradeoff is that values are opaque binary blobs: SQLite's
    ``json1`` functions can't see into them, so :meth:`filter` can't
    push field comparisons down to SQL and instead falls back to
    scanning and unpickling every row in Python. Since
    :func:`pickle.loads` can execute arbitrary code, this store must
    never be pointed at a database file that isn't fully trusted.

    The constructor mirrors :func:`sqlite3.connect` directly. For the
    common case of opening a file by path (optionally read-only), use
    :meth:`from_path` instead.

    Args:
        database: The ``database`` argument passed to
            ``sqlite3.connect`` (path, ``":memory:"``, or ``file:`` URI).
        **kwargs: Additional keyword arguments to pass to
            ``sqlite3.connect``.

    Example:
        ```pycon
        >>> from persista.store import PickleSQLiteStore
        >>> with PickleSQLiteStore(":memory:") as store:
        ...     store.set("1", {"title": "Intro to Python", "tags": ["python", "intro"]})
        ...     store.get("1")
        ...
        {'title': 'Intro to Python', 'tags': ['python', 'intro']}

        ```
    """

    _scheme = "sqlite+pickle"

    def __init__(self, database: Path | str = ":memory:", **kwargs: Any) -> None:
        super().__init__(database, **kwargs)

    def _create_table_sql(self) -> str:
        return _CREATE_TABLE_PICKLE

    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
        return pickle.loads(row[1])  # noqa: S301

    def _filter_expr(self, key: str) -> str:
        msg = (
            "PickleSQLiteStore stores values as opaque pickled blobs, so field "
            "filters can't be pushed down to SQL; filter() overrides the base "
            "implementation instead of relying on this method."
        )
        raise NotImplementedError(msg)

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        self._check_open()
        with self._lock:
            rows = self._conn.execute("SELECT * FROM store").fetchall()
        values = (self._row_to_value(row) for row in rows)
        if not field_filters:
            return list(values)
        return [
            value
            for value in values
            if all(value.get(name) == expected for name, expected in field_filters.items())
        ]

    async def afilter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not is_aiosqlite_available():
            return await asyncio.to_thread(lambda: self.filter(**field_filters))
        conn = await self._ensure_aconn()
        cursor = await conn.execute("SELECT * FROM store")
        rows = await cursor.fetchall()
        values = (self._row_to_value(row) for row in rows)
        if not field_filters:
            return list(values)
        return [
            value
            for value in values
            if all(value.get(name) == expected for name, expected in field_filters.items())
        ]

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            with self._lock:
                self._conn.executemany(
                    "INSERT OR REPLACE INTO store VALUES (?, ?)",
                    [(key, pickle.dumps(value)) for key, value in items.items()],
                )
                self._conn.commit()

        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    async def _aset_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            conn = await self._ensure_aconn()
            await conn.executemany(
                "INSERT OR REPLACE INTO store VALUES (?, ?)",
                [(key, pickle.dumps(value)) for key, value in items.items()],
            )
            await conn.commit()
        logger.debug("Added/replaced %d key-value pair(s)", len(items))
