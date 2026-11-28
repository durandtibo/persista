r"""Provide a DuckDB-backed implementation of ``BaseStore``."""

from __future__ import annotations

__all__ = ["DuckDBStore"]

import contextlib
import logging
import threading
import weakref
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.imports import lazy_import
from coola.utils.path import sanitize_path

from persista.store.sql import SQLStore
from persista.store.validation import validate_field_name
from persista.utils.imports import check_duckdb

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence
    from pathlib import Path

    from persista.store.codec import Codec

if TYPE_CHECKING:
    import duckdb
else:
    # Imported when the first store is opened.
    duckdb = lazy_import("duckdb")

logger: logging.Logger = logging.getLogger(__name__)

# The write lock of each database file that an open store uses, keyed by
# the device and inode of the file. A lock is dropped once no store holds
# it.
_DATABASE_LOCKS: weakref.WeakValueDictionary[tuple[int, int], threading.RLock] = (
    weakref.WeakValueDictionary()
)
_DATABASE_LOCKS_GUARD = threading.Lock()


class DuckDBStore(SQLStore, MultilineDisplayMixin):
    """A DuckDB-backed key-value store.

    Persists values to a DuckDB database and supports adding,
    retrieving, filtering, and deleting key-value pairs. The values are
    kept in the table ``store``, which has a ``key`` column and a
    ``value`` column. With the default
    :class:`~persista.store.JsonCodec`, the ``value`` column holds JSON
    and :meth:`filter` uses it to read only the values that may match a
    condition on a string or an integer (see
    :func:`~persista.store.sql.select_push_down_fields`). With a
    :class:`~persista.store.PickleCodec`, it holds opaque bytes, which
    keep Python types, and :meth:`filter` reads every value.

    A store has one connection, used by the sync and the async methods,
    so they see the same data. The async methods run in a worker thread
    of the store.

    A write with ``on_conflict`` set to ``"raise"``, ``"skip"`` or
    ``"merge"`` runs in a transaction. The writes of all the stores of one
    process that use the same database file wait for each other, so it is
    atomic against them. DuckDB allows only one process to write to a
    database. A write made without a store (for example with
    :attr:`connection`) while a store writes the same rows can make one
    of them raise ``duckdb.TransactionException``.

    Opening the store creates the database file, its parent directories
    and the table if they do not exist (unless ``read_only``).

    Args:
        database: Path to the DuckDB file, or ``":memory:"`` for a private
            in-memory database. Matches the ``database`` argument name
            used by ``duckdb.connect``.
        codec: The codec of the values, a
            :class:`~persista.store.JsonCodec` (default) or a
            :class:`~persista.store.PickleCodec`. Decoding a pickle
            payload can execute arbitrary code: only use it with a
            trusted database.
        read_only: If ``True``, open an existing database read-only. No
            file or directory is created.
        **kwargs: Additional keyword arguments to pass to
            ``duckdb.connect``.

    Raises:
        RuntimeError: If the ``duckdb`` package is not installed.
        ValueError: If the codec is not supported, or if ``read_only`` is
            used with an in-memory database.

    Example:
        ```pycon
        >>> from persista.store import DuckDBStore
        >>> with DuckDBStore(":memory:") as store:
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

    _scheme = "duckdb"
    _key_type = "VARCHAR"

    def __init__(
        self,
        database: Path | str = ":memory:",
        *,
        codec: Codec | None = None,
        read_only: bool = False,
        **kwargs: Any,
    ) -> None:
        check_duckdb()
        if database != ":memory:":
            database = sanitize_path(database)
        elif read_only:
            msg = f"read_only needs a database file, not an in-memory database: {database!r}"
            raise ValueError(msg)
        super().__init__(database, codec=codec, read_only=read_only, **kwargs)
        self._conn: duckdb.DuckDBPyConnection | None = None

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Return the underlying DuckDB connection.

        This is not part of the regular store API. It is meant for
        debugging or running specific commands. The store must be open.

        Raises:
            RuntimeError: If the store is not open.
        """
        if self._conn is None:
            msg = f"{type(self).__name__} is not open."
            raise RuntimeError(msg)
        return self._conn

    def _open(self) -> None:
        check_duckdb()
        database = self._database
        if not self._read_only and not isinstance(database, str):
            database.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(database, read_only=self._read_only, **self._kwargs)
        # An in-memory database belongs to this connection only.
        if not isinstance(database, str):
            self._write_lock = _get_database_lock(database)
        self._init_schema()

    def _close(self) -> None:
        if self._conn is None:
            return
        logger.info("Closing DuckDB at %s", self._database)
        self._conn.close()
        self._conn = None
        self._write_lock = contextlib.nullcontext()

    def _fetch(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        return self.connection.execute(sql, params).fetchall()

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        self.connection.execute(sql, params)

    def _executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        self.connection.executemany(sql, rows)

    @contextlib.contextmanager
    def _transaction(self) -> Generator[None, None, None]:
        connection = self.connection
        connection.begin()
        try:
            yield
            connection.commit()
        except BaseException:
            # DuckDB ends the transaction itself after some errors, and
            # then rollback fails: keep the first error.
            with contextlib.suppress(duckdb.Error):
                connection.rollback()
            raise

    def _table_columns(self) -> list[tuple[str, str, bool]]:
        found = self._fetch(
            "SELECT 1 FROM information_schema.tables WHERE table_catalog = current_database() "
            "AND table_schema = current_schema() AND lower(table_name) = 'store'"
        )
        if not found:
            return []
        # The columns of table_info are: cid, name, type, notnull,
        # dflt_value, pk.
        return [(row[1], row[2], bool(row[5])) for row in self._fetch("PRAGMA table_info('store')")]

    def _filter_condition(self, field: str, value: str | int) -> tuple[str, list[Any]]:
        validate_field_name(field)
        text = f"json_extract_string(value, '$.{field}')"
        if isinstance(value, int):
            # A number is extracted as text, such as '1' or '1.0'. It is
            # cast to an integer: comparing the text with an integer would
            # fail on a field that holds another text. A number with
            # decimals is rounded, and is then excluded by the filter.
            return f"TRY_CAST({text} AS BIGINT) = ?", [value]
        return f"{text} = ?", [value]


def _get_database_lock(database: Path) -> threading.RLock:
    r"""Return the write lock of a database file.

    Args:
        database: The path to an existing database file.

    Returns:
        The same lock for every path that leads to the same file, as long
        as a caller holds a reference to it.
    """
    stat = database.stat()
    key = (stat.st_dev, stat.st_ino)
    with _DATABASE_LOCKS_GUARD:
        lock = _DATABASE_LOCKS.get(key)
        if lock is None:
            lock = _DATABASE_LOCKS[key] = threading.RLock()
        return lock
