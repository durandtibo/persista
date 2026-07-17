r"""Provide a SQLite-backed implementation of ``BaseStore``, storing
values as JSON."""

from __future__ import annotations

__all__ = ["BaseSQLiteStore", "SQLiteStore", "TypedSQLiteStore"]

import json
import logging
import sqlite3
from abc import abstractmethod
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

    A single ``store`` table backs every value; the primary key
    column is named by :attr:`_key_column`. :meth:`get`,
    :meth:`get_many`, :meth:`filter`, and :meth:`iter_batches` all
    query the full row and hand it to :meth:`_row_to_value` to turn
    it back into a value dict, which is what lets subclasses differ
    in how a value is laid out across columns (a single JSON column
    vs. typed columns plus a JSON overflow column) without
    duplicating any of the surrounding query logic.

    Subclasses only need to implement :meth:`_create_table_sql`,
    :meth:`_row_to_value`, :meth:`_build_filter_condition`, and
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

    def __init__(self, database: Path | str, **kwargs: Any) -> None:
        self._database = database
        self._kwargs = kwargs
        self._closed = False
        self._conn = sqlite3.connect(database, **kwargs)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the store's table if it doesn't already exist.

        Called once from ``__init__`` and again each time the store
        is reopened via :meth:`__enter__` after being closed. A
        ``:memory:`` database starts empty every time it is
        (re)connected to, so this is what makes reopening a closed
        in-memory store behave like a reset rather than resuming
        where it left off.
        """
        try:
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
    def _build_filter_condition(self, key: str) -> str:
        """Build the SQL condition fragment (with a single ``?``
        placeholder) that matches value field ``key`` against a bound
        parameter."""

    @abstractmethod
    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        """Write ``items`` to the table, replacing any existing row for
        the same key."""

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
        """
        if str(path) == ":memory:":
            uri = "file::memory:?cache=shared"
        elif read_only:
            uri = f"file:{path}?mode=ro"
        else:
            uri = f"file:{path}?mode=rwc"
        return cls(uri, uri=True, **kwargs)

    def close(self) -> None:
        if self._closed:
            return
        logger.info("Closing SQLite at %s", self._database)
        self._conn.close()
        self._closed = True

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT * FROM store WHERE {self._key_column} = ?",  # noqa: S608
            (key,),
        ).fetchone()
        return self._row_to_value(row) if row else None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        placeholders = ", ".join("?" * len(keys))
        rows = self._conn.execute(
            f"SELECT * FROM store WHERE {self._key_column} IN ({placeholders})",  # noqa: S608
            keys,
        ).fetchall()
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
            rows = self._conn.execute("SELECT * FROM store").fetchall()
            return [self._row_to_value(row) for row in rows]

        conditions = [self._build_filter_condition(key) for key in field_filters]
        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT * FROM store WHERE {where}",  # noqa: S608
            list(field_filters.values()),
        ).fetchall()
        return [self._row_to_value(row) for row in rows]

    def delete(self, key: str) -> None:
        self._conn.execute(f"DELETE FROM store WHERE {self._key_column} = ?", (key,))  # noqa: S608
        self._conn.commit()

    def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        placeholders = ", ".join("?" * len(keys))
        self._conn.execute(
            f"DELETE FROM store WHERE {self._key_column} IN ({placeholders})",  # noqa: S608
            keys,
        )
        self._conn.commit()

    def contains_many(self, keys: list[str]) -> tuple[list[str], list[str]]:
        if not keys:
            return [], []
        placeholders = ", ".join("?" * len(keys))
        existing = {
            row[0]
            for row in self._conn.execute(
                f"SELECT {self._key_column} FROM store "  # noqa: S608
                f"WHERE {self._key_column} IN ({placeholders})",
                keys,
            ).fetchall()
        }
        found = [key for key in keys if key in existing]
        missing = [key for key in keys if key not in existing]
        return found, missing

    def keys(self) -> Iterator[str]:
        cursor = self._conn.execute(f"SELECT {self._key_column} FROM store")  # noqa: S608
        for (key,) in cursor:
            yield key

    def iter_batches(
        self, batch_size: int = 32
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        validate_batch_size(batch_size)
        cursor = self._conn.execute("SELECT * FROM store")
        for batch in batchify(cursor, size=batch_size):
            yield {row[0]: self._row_to_value(row) for row in batch}

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

    def _create_table_sql(self) -> str:
        return _CREATE_TABLE

    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
        return json.loads(row[1])

    def _build_filter_condition(self, key: str) -> str:
        validate_field_name(key)
        return f"json_extract(value, '$.{key}') = ?"

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            self._conn.executemany(
                "INSERT OR REPLACE INTO store VALUES (?, ?)",
                [(key, json.dumps(value)) for key, value in items.items()],
            )
            self._conn.commit()

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
        >>> store = TypedSQLiteStore(":memory:", value_schema=schema)
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

    def _row_to_value(self, row: tuple[Any, ...]) -> dict[str, Any]:
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

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            self._conn.executemany(
                self._build_insert(),
                [self._value_to_row(key, value) for key, value in items.items()],
            )
            self._conn.commit()

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
