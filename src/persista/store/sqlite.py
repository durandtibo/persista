r"""Provide a SQLite-backed implementation of ``BaseStore``."""

from __future__ import annotations

__all__ = ["SQLiteStore"]

import contextlib
import logging
import sqlite3
import threading
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.path import sanitize_path

from persista.store.sql import SQLStore
from persista.store.validation import validate_field_name

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence
    from pathlib import Path

    from persista.store.codec import Codec

logger: logging.Logger = logging.getLogger(__name__)

# Conservative default for SQLITE_MAX_VARIABLE_NUMBER: older SQLite builds
# default to 999 bound parameters per statement, so batch methods chunk
# IN (...) clauses to stay well under that regardless of how the sqlite3
# extension was compiled.
_MAX_SQL_VARIABLES = 900

# The connections to a shared cache do not wait for each other: SQLite
# fails at once with "database table is locked". The stores that use a
# shared cache therefore share this lock instead of their own.
_SHARED_CACHE_LOCK = threading.RLock()


class SQLiteStore(SQLStore, MultilineDisplayMixin):
    """A SQLite-backed key-value store.

    Persists values to a SQLite database and supports adding,
    retrieving, filtering, and deleting key-value pairs. The values are
    kept in the table ``store``, which has a ``key`` column and a
    ``value`` column. With the default
    :class:`~persista.store.JsonCodec`, the ``value`` column holds JSON,
    so SQLite's ``json1`` functions can read it and :meth:`filter` is
    applied by the database. With a
    :class:`~persista.store.PickleCodec`, it holds opaque bytes, which
    keep Python types, and :meth:`filter` reads every value.

    A store has one connection, used by the sync and the async methods,
    so they see the same data. The async methods run in a worker thread
    of the store.

    A write with ``on_conflict`` set to ``"raise"``, ``"skip"`` or
    ``"merge"`` runs in a ``BEGIN IMMEDIATE`` transaction, so it is atomic
    against the other writers of the database, including other stores
    and other processes. A write waits for the other writers up to
    ``timeout`` seconds (5 by default, see :func:`sqlite3.connect`), then
    raises ``sqlite3.OperationalError``. The stores of one process that
    use the same shared cache (``cache=shared``) wait for each other
    without time limit.

    Opening the store creates the database file, its parent directories
    and the table if they do not exist (unless ``read_only``).

    Args:
        database: The path to the database file, ``":memory:"`` for a
            private in-memory database, or a ``file:`` URI (with
            ``uri=True``).
        codec: The codec of the values, a
            :class:`~persista.store.JsonCodec` (default) or a
            :class:`~persista.store.PickleCodec`. Decoding a pickle
            payload can execute arbitrary code: only use it with a
            trusted database.
        read_only: If ``True``, open an existing database read-only. No
            file or directory is created.
        **kwargs: Additional keyword arguments to pass to
            ``sqlite3.connect`` (e.g. ``uri=True``, ``timeout``,
            ``check_same_thread``, which defaults to ``False``).

    Raises:
        ValueError: If the codec is not supported, if ``isolation_level``
            or ``autocommit`` is given (the store manages its
            transactions), or if ``read_only`` is used with an in-memory
            database.

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

        A pickle codec keeps Python types, and a read-only store reads
        an existing database:

        ```pycon
        >>> import tempfile
        >>> from persista.store import PickleCodec, SQLiteStore
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     with SQLiteStore(f"{tmpdir}/data.db", codec=PickleCodec()) as store:
        ...         store.set("1", {"tags": {"python"}})
        ...     with SQLiteStore(
        ...         f"{tmpdir}/data.db", codec=PickleCodec(), read_only=True
        ...     ) as store:
        ...         store.get("1")
        ...
        {'tags': {'python'}}

        ```
    """

    _scheme = "sqlite"
    _key_type = "TEXT"
    _max_variables = _MAX_SQL_VARIABLES

    def __init__(
        self,
        database: Path | str = ":memory:",
        *,
        codec: Codec | None = None,
        read_only: bool = False,
        **kwargs: Any,
    ) -> None:
        managed = sorted({"autocommit", "isolation_level"} & kwargs.keys())
        if managed:
            msg = f"SQLiteStore manages its transactions, so it does not accept {managed}"
            raise ValueError(msg)
        if str(database).startswith("file:"):
            database = str(database)
        elif database != ":memory:":
            database = sanitize_path(database)
        if read_only and _is_memory_database(database):
            msg = f"read_only needs a database file, not an in-memory database: {database!r}"
            raise ValueError(msg)
        super().__init__(database, codec=codec, read_only=read_only, **kwargs)
        self._conn: sqlite3.Connection | None = None
        # A read-only store always opens a file: database as a URI.
        if (read_only or kwargs.get("uri")) and _is_shared_cache(database):
            self._lock = self._guard = _SHARED_CACHE_LOCK

    @property
    def connection(self) -> sqlite3.Connection:
        """Return the underlying SQLite connection.

        This is not part of the regular store API. It is meant for
        debugging or running specific commands, such as creating an
        index. The store must be open. The connection is in autocommit
        mode: a statement is committed when it ends, unless it is run
        after an explicit ``BEGIN``, which must be ended before the store
        writes again.

        Raises:
            RuntimeError: If the store is not open.
        """
        if self._conn is None:
            msg = f"{type(self).__name__} is not open."
            raise RuntimeError(msg)
        return self._conn

    @classmethod
    def _uri_kwargs(cls, database: str) -> dict[str, Any]:
        # A SQLite URI needs uri=True.
        return {"uri": True} if database.startswith("file:") else {}

    def _open(self) -> None:
        database = self._database
        # Autocommit: the store starts its transactions itself.
        kwargs: dict[str, Any] = {
            "check_same_thread": False,
            **self._kwargs,
            "isolation_level": None,
        }
        if self._read_only:
            database = _read_only_uri(database)
            kwargs["uri"] = True
        elif not isinstance(database, str):
            database.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(database, **kwargs)
        self._init_schema()

    def _close(self) -> None:
        if self._conn is None:
            return
        logger.info("Closing SQLite at %s", self._database)
        self._conn.close()
        self._conn = None

    def _fetch(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        # Reading every row ends the statement, which releases its lock.
        return self.connection.execute(sql, params).fetchall()

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        self.connection.execute(sql, params)

    def _executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        self.connection.executemany(sql, rows)

    @contextlib.contextmanager
    def _transaction(self) -> Generator[None, None, None]:
        connection = self.connection
        # IMMEDIATE takes the write lock before the first read, so no
        # other writer can change what the transaction read.
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            connection.execute("COMMIT")
        except BaseException:
            # SQLite ends the transaction itself after some errors.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    def _table_columns(self) -> list[tuple[str, str, bool]]:
        # The columns of table_info are: cid, name, type, notnull,
        # dflt_value, pk.
        return [(row[1], row[2], bool(row[5])) for row in self._fetch("PRAGMA table_info(store)")]

    def _filter_expr(self, field: str) -> str:
        validate_field_name(field)
        return f"json_extract(value, '$.{field}')"


def _is_memory_database(database: Path | str) -> bool:
    r"""Indicate whether a SQLite database lives in memory.

    Args:
        database: A path, ``":memory:"``, or a ``file:`` URI.

    Returns:
        ``True`` for ``":memory:"`` and for a URI of an in-memory database.
    """
    database = str(database)
    if database == ":memory:":
        return True
    if not database.startswith("file:"):
        return False
    path, _, query = database.removeprefix("file:").partition("?")
    return path == ":memory:" or "mode=memory" in query.split("&")


def _is_shared_cache(database: Path | str) -> bool:
    r"""Indicate whether a SQLite database is a URI that uses a shared
    cache.

    Args:
        database: A path, ``":memory:"``, or a ``file:`` URI.

    Returns:
        ``True`` for a ``file:`` URI with the parameter ``cache=shared``.
    """
    database = str(database)
    return database.startswith("file:") and "cache=shared" in database.partition("?")[2].split("&")


def _read_only_uri(database: Path | str) -> str:
    r"""Build the URI that opens a database file read-only.

    Args:
        database: An absolute path, or a ``file:`` URI.

    Returns:
        A ``file:`` URI with ``mode=ro``, which replaces any other mode.
    """
    if not isinstance(database, str):
        # as_uri() escapes the characters that have a meaning in a URI.
        return f"{database.as_uri()}?mode=ro"
    path, _, query = database.partition("#")[0].partition("?")
    params = [param for param in query.split("&") if param and not param.startswith("mode=")]
    return f"{path}?{'&'.join([*params, 'mode=ro'])}"
