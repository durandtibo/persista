r"""Provide a DuckDB-backed ``BaseStore`` implementation with an
optional typed value schema."""

from __future__ import annotations

__all__ = ["TypedDuckDBStore"]

import json
import logging
from typing import TYPE_CHECKING, Any

from persista.store.duckdb import BaseDuckDBStore
from persista.store.validation import validate_field_name

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

logger: logging.Logger = logging.getLogger(__name__)

_KEY_COLUMN = "_KEY_"


class TypedDuckDBStore(BaseDuckDBStore):
    """A DuckDB-backed key-value store with an optional typed value
    schema.

    Persists values to a DuckDB database and supports adding,
    retrieving, and filtering by value fields.  An optional
    ``value_schema`` maps known value field names to DuckDB types.
    Known fields are stored as typed columns for fast, index-friendly
    queries.  Any value fields not in the schema are stored in an
    ``extra`` JSON overflow column, so nothing is lost.

    Args:
        path: Path to the DuckDB file, or ``":memory:"`` for an
            in-memory database (useful for testing).
        value_schema: Optional mapping of value field names to DuckDB
            type strings (e.g. ``{"author": "VARCHAR", "year":
            "INTEGER"}``).  Fields in the schema get native typed
            columns; all other value fields go into the ``extra``
            JSON overflow column.  Defaults to ``None``, which stores
            every value field as JSON only.
        **kwargs: Additional keyword arguments to pass to
            ``duckdb.connect``.

    Example:
        ```pycon
        >>> from persista.store import TypedDuckDBStore
        >>> schema = {"author": "VARCHAR", "year": "INTEGER", "category": "VARCHAR"}
        >>> store = TypedDuckDBStore(":memory:", value_schema=schema)
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
        path: Path | str = ":memory:",
        value_schema: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        value_schema = value_schema or {}
        if _KEY_COLUMN in value_schema:
            msg = f"value_schema must not contain the reserved key column name {_KEY_COLUMN!r}"
            raise ValueError(msg)
        super().__init__(path, **kwargs)
        self._schema: dict[str, str] = value_schema
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        if not self._kwargs.get("read_only", False):
            self._conn.execute(self._build_create_table())

    def _select_columns(self) -> list[str]:
        return [_KEY_COLUMN, *self._schema.keys(), "extra"]

    def _row_to_kv(self, row: tuple) -> tuple[str, dict[str, Any]]:
        return row[0], self._row_to_value(row)

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            self._conn.executemany(
                self._build_insert(),
                [self._value_to_row(key, value) for key, value in items.items()],
            )

        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        if not field_filters:
            rows = self._conn.execute("SELECT * FROM store").fetchall()
            return [self._row_to_value(row) for row in rows]

        conditions, values = [], []
        for key, value in field_filters.items():
            if key in self._schema:
                conditions.append(f"{key} = ?")
            else:
                validate_field_name(key)
                conditions.append(f"json_extract_string(extra, '$.{key}') = ?")
            values.append(value)

        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT * FROM store WHERE {where}",  # noqa: S608
            values,
        ).fetchall()
        return [self._row_to_value(row) for row in rows]

    # ---------------------------------------------------------------------------
    # Private helpers
    # ---------------------------------------------------------------------------

    def _build_create_table(self) -> str:
        """Build the CREATE TABLE statement from the schema."""
        typed_cols = "".join(f", {name} {dtype}" for name, dtype in self._schema.items())
        return (
            f"CREATE TABLE IF NOT EXISTS store "
            f"({_KEY_COLUMN} VARCHAR PRIMARY KEY{typed_cols}, extra JSON)"
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
