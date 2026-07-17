r"""Provide a SQLite-backed implementation of ``BaseStore``, storing
values as JSON."""

from __future__ import annotations

__all__ = ["BaseSQLiteStore", "SQLiteStore"]

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify

from persista.store.base import BaseStore
from persista.store.validation import (
    normalize_on_conflict,
    validate_batch_size,
    validate_field_name,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Mapping
    from pathlib import Path

    from typing_extensions import Self

    from persista.store.types import OnConflict

logger: logging.Logger = logging.getLogger(__name__)


class BaseSQLiteStore(BaseStore, MultilineDisplayMixin):
    r"""Define a base class for SQLite-backed key-value stores.

    The constructor mirrors :func:`sqlite3.connect`: the first
    positional argument is the ``database`` argument accepted by
    ``sqlite3.connect`` (a path, ``":memory:"``, or a ``file:`` URI
    when ``uri=True`` is passed), and any additional keyword
    arguments are forwarded as-is.  Use :meth:`SQLiteStore.from_path`
    for a more convenient constructor that builds the appropriate URI
    for you, including read-only access.

    Args:
        database: The ``database`` argument passed to
            ``sqlite3.connect`` (path, ``":memory:"``, or ``file:`` URI).
        **kwargs: Additional keyword arguments to pass to
            ``sqlite3.connect`` (e.g. ``uri=True``, ``timeout``,
            ``check_same_thread``).
    """

    def __init__(self, database: Path | str, **kwargs: Any) -> None:
        self._database = database
        self._kwargs = kwargs
        self._closed = False
        self._conn = sqlite3.connect(database, **kwargs)

    def _ensure_schema(self) -> None:
        """Recreate the store's table schema on a fresh connection.

        Called once from ``__init__`` and again each time the store is
        reopened via :meth:`__enter__` after being closed. A
        ``:memory:`` database starts empty every time it is
        (re)connected to, so this is what makes reopening a closed in-
        memory store behave like a reset rather than resuming where it
        left off. The default implementation does nothing; subclasses
        override it.
        """

    def close(self) -> None:
        if self._closed:
            return
        logger.info("Closing SQLite at %s", self._database)
        self._conn.close()
        self._closed = True

    def delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM store WHERE key = ?", (key,))
        self._conn.commit()

    def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        placeholders = ", ".join("?" * len(keys))
        self._conn.execute(
            f"DELETE FROM store WHERE key IN ({placeholders})",  # noqa: S608
            keys,
        )
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM store").fetchone()[0]

    def get_columns_info(self) -> dict[str, str]:
        """Return the column names and types of the store's table.

        Returns:
            A mapping of column name to SQLite declared type.
        """
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

    def __enter__(self) -> Self:
        if self._closed:
            self._conn = sqlite3.connect(self._database, **self._kwargs)
            self._closed = False
            self._ensure_schema()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


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
        >>> store = SQLiteStore(":memory:")
        >>> store.set_many(
        ...     {
        ...         "1": {"title": "Intro to Python", "author": "Alice", "category": "Programming"},
        ...         "2": {"title": "Advanced Python", "author": "Alice", "category": "Programming"},
        ...         "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
        ...     }
        ... )
        >>> len(store.filter(author="Alice"))
        2
        >>> len(store.filter(author="Alice", category="Programming"))
        2
        >>> len(store.filter(category="History"))
        1

        ```
    """

    def __init__(self, database: Path | str = ":memory:", **kwargs: Any) -> None:
        super().__init__(database, **kwargs)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        try:
            self._conn.execute(_CREATE_TABLE)
            self._conn.commit()
        except sqlite3.OperationalError:
            # Connection is read-only (e.g. opened via a `mode=ro` URI);
            # assume the table already exists.
            pass

    @classmethod
    def from_path(cls, path: Path | str, *, read_only: bool = False, **kwargs: Any) -> SQLiteStore:
        """Construct a :class:`SQLiteStore` from a file path.

        Builds the appropriate ``file:`` URI for ``sqlite3.connect``,
        including read-only access, so callers don't need to
        construct SQLite URIs themselves.

        Args:
            path: Path to the SQLite file, or ``":memory:"`` for an
                in-memory database (useful for testing).
            read_only: If ``True``, open the database in read-only
                mode. The database file must already exist.
            **kwargs: Additional keyword arguments to pass to
                ``sqlite3.connect``.

        Returns:
            A new :class:`SQLiteStore` connected to ``path``.
        """
        if str(path) == ":memory:":
            uri = "file::memory:?cache=shared"
        elif read_only:
            uri = f"file:{path}?mode=ro"
        else:
            uri = f"file:{path}?mode=rwc"
        return cls(uri, uri=True, **kwargs)

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT value FROM store WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        placeholders = ", ".join("?" * len(keys))
        rows = self._conn.execute(
            f"SELECT key, value FROM store WHERE key IN ({placeholders})",  # noqa: S608
            keys,
        ).fetchall()
        by_key = {key: json.loads(value) for key, value in rows}
        return [by_key.get(key) for key in keys]

    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
        self.set_many({key: value}, on_conflict=on_conflict)

    def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        if not items:
            return
        on_conflict = normalize_on_conflict(on_conflict)

        conflicts = set(self.contains_many(list(items))[0])
        if conflicts and on_conflict == "raise":
            msg = f"Key(s) already exist in the store: {sorted(conflicts)}"
            raise KeyError(msg)

        to_write: dict[str, dict[str, Any]] = {}
        for key, value in items.items():
            if key in conflicts:
                if on_conflict == "skip":
                    continue
                if on_conflict == "merge":
                    to_write[key] = {**(self.get(key) or {}), **value}
                    continue
            to_write[key] = value

        if to_write:
            self._conn.executemany(
                "INSERT OR REPLACE INTO store VALUES (?, ?)",
                [(key, json.dumps(value)) for key, value in to_write.items()],
            )
            self._conn.commit()

        logger.debug("Added/replaced %d key-value pair(s)", len(to_write))

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not field_filters:
            rows = self._conn.execute("SELECT value FROM store").fetchall()
            return [json.loads(value) for (value,) in rows]

        for key in field_filters:
            validate_field_name(key)
        conditions = [f"json_extract(value, '$.{key}') = ?" for key in field_filters]
        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT value FROM store WHERE {where}",  # noqa: S608
            list(field_filters.values()),
        ).fetchall()
        return [json.loads(value) for (value,) in rows]

    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        if not keys:
            return [], []
        placeholders = ", ".join("?" * len(keys))
        existing = {
            row[0]
            for row in self._conn.execute(
                f"SELECT key FROM store WHERE key IN ({placeholders})",  # noqa: S608
                keys,
            ).fetchall()
        }
        found = [key for key in keys if key in existing]
        missing = [key for key in keys if key not in existing]
        return found, missing

    def keys(self) -> Iterator[str]:
        cursor = self._conn.execute("SELECT key FROM store")
        for (key,) in cursor:
            yield key

    def iter_batches(
        self, batch_size: int = 32
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        validate_batch_size(batch_size)
        cursor = self._conn.execute("SELECT key, value FROM store")
        for batch in batchify(cursor, size=batch_size):
            yield {key: json.loads(value) for key, value in batch}
