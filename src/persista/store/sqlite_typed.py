r"""Provide a SQLite-backed ``BaseStore`` implementation with an
optional typed value schema."""

from __future__ import annotations

__all__ = ["TypedSQLiteStore"]

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from coola.utils.batching import batchify

from persista.store.sqlite import BaseSQLiteStore
from persista.store.validation import normalize_on_conflict, validate_batch_size

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Mapping
    from pathlib import Path

    from persista.store.types import OnConflict

logger: logging.Logger = logging.getLogger(__name__)

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
        super().__init__(database, **kwargs)
        self._schema: dict[str, str] = value_schema
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        try:
            self._conn.execute(self._build_create_table())
            self._conn.commit()
        except sqlite3.OperationalError:
            # Connection is read-only (e.g. opened via a `mode=ro` URI);
            # assume the table already exists.
            pass

    @classmethod
    def from_path(
        cls,
        path: Path | str,
        *,
        value_schema: dict[str, str] | None = None,
        read_only: bool = False,
        **kwargs: Any,
    ) -> TypedSQLiteStore:
        """Construct a :class:`TypedSQLiteStore` from a file path.

        Builds the appropriate ``file:`` URI for ``sqlite3.connect``,
        including read-only access, so callers don't need to
        construct SQLite URIs themselves.

        Args:
            path: Path to the SQLite file, or ``":memory:"`` for an
                in-memory database (useful for testing).
            value_schema: Optional mapping of value field names to
                SQLite type strings. See the class docstring.
            read_only: If ``True``, open the database in read-only
                mode. The database file must already exist.
            **kwargs: Additional keyword arguments to pass to
                ``sqlite3.connect``.

        Returns:
            A new :class:`TypedSQLiteStore` connected to ``path``.
        """
        if str(path) == ":memory:":
            uri = "file::memory:?cache=shared"
        elif read_only:
            uri = f"file:{path}?mode=ro"
        else:
            uri = f"file:{path}?mode=rwc"
        return cls(uri, value_schema=value_schema, uri=True, **kwargs)

    def get(self, key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT * FROM store WHERE {_KEY_COLUMN} = ?",  # noqa: S608
            (key,),
        ).fetchone()
        return self._row_to_value(row) if row else None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        placeholders = ", ".join("?" * len(keys))
        rows = self._conn.execute(
            f"SELECT * FROM store WHERE {_KEY_COLUMN} IN ({placeholders})",  # noqa: S608
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
                self._build_insert(),
                [self._value_to_row(key, value) for key, value in to_write.items()],
            )
            self._conn.commit()

        logger.debug("Added/replaced %d key-value pair(s)", len(to_write))

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not field_filters:
            rows = self._conn.execute("SELECT * FROM store").fetchall()
            return [self._row_to_value(row) for row in rows]

        conditions, values = [], []
        for key, value in field_filters.items():
            if key in self._schema:
                conditions.append(f"{key} = ?")
            else:
                conditions.append(f"json_extract(extra, '$.{key}') = ?")
            values.append(value)

        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT * FROM store WHERE {where}",  # noqa: S608
            values,
        ).fetchall()
        return [self._row_to_value(row) for row in rows]

    def delete(self, key: str) -> None:
        self._conn.execute(f"DELETE FROM store WHERE {_KEY_COLUMN} = ?", (key,))  # noqa: S608
        self._conn.commit()

    def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        placeholders = ", ".join("?" * len(keys))
        self._conn.execute(
            f"DELETE FROM store WHERE {_KEY_COLUMN} IN ({placeholders})",  # noqa: S608
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
                f"SELECT {_KEY_COLUMN} FROM store WHERE {_KEY_COLUMN} IN ({placeholders})",  # noqa: S608
                keys,
            ).fetchall()
        }
        found = [key for key in keys if key in existing]
        missing = [key for key in keys if key not in existing]
        return found, missing

    def keys(self) -> Iterator[str]:
        cursor = self._conn.execute(f"SELECT {_KEY_COLUMN} FROM store")  # noqa: S608
        for (key,) in cursor:
            yield key

    def iter_batches(
        self, batch_size: int = 32
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        validate_batch_size(batch_size)
        cursor = self._conn.execute("SELECT * FROM store")
        for batch in batchify(cursor, size=batch_size):
            yield {row[0]: self._row_to_value(row) for row in batch}

    # ---------------------------------------------------------------------------
    # Private helpers
    # ---------------------------------------------------------------------------

    def _build_create_table(self) -> str:
        """Build the CREATE TABLE statement from the schema."""
        typed_cols = "".join(f", {name} {dtype}" for name, dtype in self._schema.items())
        return (
            f"CREATE TABLE IF NOT EXISTS store "
            f"({_KEY_COLUMN} TEXT PRIMARY KEY{typed_cols}, extra JSON)"
        )

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

    def _row_to_value(self, row: tuple) -> dict[str, Any]:
        """Convert a raw database row back to a value dict."""
        # row layout: key, [schema cols...], extra
        schema_vals = dict(zip(self._schema.keys(), row[1 : 1 + len(self._schema)]))
        extra_json = row[1 + len(self._schema)]
        value = {k: v for k, v in schema_vals.items() if v is not None}
        if extra_json:
            value.update(json.loads(extra_json))
        return value
