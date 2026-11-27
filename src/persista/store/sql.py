r"""Provide the code shared by the stores that keep their values in a SQL
table.

The table is named ``store`` and has two columns: ``key``, its primary
key, and ``value``, whose type depends on the codec of the store.
"""

from __future__ import annotations

__all__ = [
    "SQLStore",
    "build_where",
    "check_sql_codec",
    "check_table_layout",
    "decode_sql_uri",
    "encode_sql_uri",
    "value_column_type",
]

import contextlib
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

from coola.utils.batching import batchify

from persista.store.base import BaseStore
from persista.store.codec import JsonCodec
from persista.store.uri import decode_codec_uri, encode_path_uri
from persista.store.validation import check_is_open

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence
    from pathlib import Path
    from typing import Self

    from persista.store.codec import Codec
    from persista.store.types import Payload, Plan

# The type of the value column for each codec name.
_VALUE_COLUMN_TYPES: dict[str, str] = {"json": "JSON", "pickle": "BLOB"}

_DELETE_ALL = "DELETE FROM store"
_SELECT_KEYS = "SELECT key FROM store"
_SELECT_FIRST_KEYS = "SELECT key FROM store ORDER BY key LIMIT ?"
_SELECT_NEXT_KEYS = "SELECT key FROM store WHERE key > ? ORDER BY key LIMIT ?"
_SELECT_ALL = "SELECT key, value FROM store"
_SELECT_ONE = "SELECT key, value FROM store WHERE key = ?"
_SELECT_FIRST_BATCH = "SELECT key, value FROM store ORDER BY key LIMIT ?"
_SELECT_NEXT_BATCH = "SELECT key, value FROM store WHERE key > ? ORDER BY key LIMIT ?"
_UPSERT = "INSERT OR REPLACE INTO store (key, value) VALUES (?, ?)"


def check_sql_codec(codec: Codec) -> None:
    r"""Check that a SQL store can keep the payloads of a codec.

    Args:
        codec: The codec to check. Its ``name`` selects the type of the
            value column.

    Raises:
        ValueError: If the name of the codec is not ``"json"`` or
            ``"pickle"``.

    Example:
        ```pycon
        >>> from persista.store import JsonCodec
        >>> from persista.store.sql import check_sql_codec
        >>> check_sql_codec(JsonCodec())

        ```
    """
    if codec.name not in _VALUE_COLUMN_TYPES:
        msg = f"A SQL store needs a codec named {sorted(_VALUE_COLUMN_TYPES)}, not {codec.name!r}"
        raise ValueError(msg)


def value_column_type(codec: Codec) -> str:
    r"""Return the type of the value column for a codec.

    Args:
        codec: The codec of the store.

    Returns:
        ``"JSON"`` for a codec named ``"json"``, and ``"BLOB"`` for a
        codec named ``"pickle"``.

    Raises:
        ValueError: If the name of the codec is not supported.

    Example:
        ```pycon
        >>> from persista.store import PickleCodec
        >>> from persista.store.sql import value_column_type
        >>> value_column_type(PickleCodec())
        'BLOB'

        ```
    """
    check_sql_codec(codec)
    return _VALUE_COLUMN_TYPES[codec.name]


def check_table_layout(
    columns: Sequence[tuple[str, str, bool]],
    *,
    codec: Codec,
    key_type: str,
    database: Path | str,
) -> None:
    r"""Check that an existing table can be used with a codec.

    Args:
        columns: The ``(name, type, is_primary_key)`` of every column of
            the table. The names and types are compared ignoring case.
        codec: The codec of the store.
        key_type: The expected type of the ``key`` column.
        database: The database of the table, used in the error message.

    Raises:
        ValueError: If the columns of the table are not exactly a
            ``key`` primary key of type ``key_type`` and a ``value`` column
            of the type of the codec.

    Example:
        ```pycon
        >>> from persista.store import JsonCodec
        >>> from persista.store.sql import check_table_layout
        >>> check_table_layout(
        ...     [("key", "TEXT", True), ("value", "JSON", False)],
        ...     codec=JsonCodec(),
        ...     key_type="TEXT",
        ...     database=":memory:",
        ... )

        ```
    """
    value_type = value_column_type(codec)
    expected = [("key", key_type.upper(), True), ("value", value_type, False)]
    actual = sorted((name.lower(), dtype.upper(), bool(pk)) for name, dtype, pk in columns)
    if actual != expected:
        found = ", ".join(
            f"{name} {dtype}{' PRIMARY KEY' if pk else ''}" for name, dtype, pk in columns
        )
        msg = (
            f"The table 'store' of {str(database)!r} does not match the codec {codec.name!r}: "
            f"expected the columns (key {key_type} PRIMARY KEY, value {value_type}), "
            f"found ({found})"
        )
        raise ValueError(msg)


def build_where(
    fields: Mapping[str, Any], expression: Callable[[str], str]
) -> tuple[str, list[Any]]:
    r"""Build the ``WHERE`` clause that selects the rows whose fields are
    equal to some values.

    Args:
        fields: The expected value of each field. ``None`` is matched with
            ``IS NULL``, because ``NULL = ?`` is never true in SQL.
        expression: A function that returns the SQL expression that
            reads a field. It must raise if the field name cannot be
            safely interpolated into SQL.

    Returns:
        The condition, without ``WHERE`` (empty if ``fields`` is empty),
        and the values of its parameters.

    Example:
        ```pycon
        >>> from persista.store.sql import build_where
        >>> build_where({"author": "Alice", "year": None}, lambda name: name)
        ('author = ? AND year IS NULL', ['Alice'])

        ```
    """
    conditions: list[str] = []
    params: list[Any] = []
    for name, expected in fields.items():
        expr = expression(name)
        if expected is None:
            conditions.append(f"{expr} IS NULL")
        else:
            conditions.append(f"{expr} = ?")
            params.append(expected)
    return " AND ".join(conditions), params


def encode_sql_uri(scheme: str, database: Path | str, codec: Codec) -> str:
    r"""Encode the location of a SQL store as a URI that carries its
    codec.

    Args:
        scheme: The URI scheme of the backend, such as ``"sqlite"``. The
            suffix ``+pickle`` is added for a codec named ``"pickle"``.
        database: The database of the store.
        codec: The codec of the store.

    Returns:
        The URI.

    Example:
        ```pycon
        >>> from persista.store import PickleCodec
        >>> from persista.store.sql import encode_sql_uri
        >>> encode_sql_uri("sqlite", "/tmp/data.db", PickleCodec())
        'sqlite+pickle:/tmp/data.db'

        ```
    """
    if codec.name == "pickle":
        scheme = f"{scheme}+pickle"
    return encode_path_uri(scheme, str(database))


def decode_sql_uri(uri: str, *, scheme: str, codec: Codec | None = None) -> tuple[str, Codec]:
    r"""Decode a URI produced by :func:`encode_sql_uri`.

    Args:
        uri: The URI to decode.
        scheme: The URI scheme of the backend, without suffix.
        codec: The codec to use instead of the default codec of the
            scheme of ``uri``. It must have the same name.

    Returns:
        The database and the codec.

    Raises:
        ValueError: If the scheme of ``uri`` is neither ``scheme`` nor
            ``scheme+pickle``, or if the name of ``codec`` does not match
            the scheme.

    Example:
        ```pycon
        >>> from persista.store.sql import decode_sql_uri
        >>> decode_sql_uri("sqlite+pickle:/tmp/data.db", scheme="sqlite")
        ('/tmp/data.db', PickleCodec())

        ```
    """
    return decode_codec_uri(
        uri, schemes={"json": scheme, "pickle": f"{scheme}+pickle"}, codec=codec
    )


class SQLStore(BaseStore):
    r"""Define a base class for the stores that keep their values in a
    SQL table, through a connection with a ``qmark`` parameter style.

    It implements the primitives of :class:`~persista.store.BaseStore`
    with SQL statements. A subclass implements ``_open`` and ``_close``,
    the methods that run a statement (``_fetch``, ``_execute``,
    ``_executemany`` and ``_transaction``), ``_table_columns`` and
    ``_filter_expr``, and sets ``_scheme`` and ``_key_type``.

    A write of several rows, and a write that depends on the existing
    values, run in one transaction. An iteration reads the keys in
    order and starts each batch after the last key of the previous one
    (keyset pagination).

    Args:
        database: The database of the store.
        codec: The codec of the store. Its name must be ``"json"`` or
            ``"pickle"``. Defaults to a
            :class:`~persista.store.JsonCodec`.
        read_only: Whether the store only reads an existing database.
        **kwargs: The keyword arguments of the driver.

    Raises:
        ValueError: If the codec is not supported.

    Example:
        ```pycon
        >>> from persista.store import SQLiteStore
        >>> from persista.store.sql import SQLStore
        >>> issubclass(SQLiteStore, SQLStore)
        True

        ```
    """

    #: URI scheme of the backend, without the suffix of the codec.
    _scheme: ClassVar[str]

    #: Type of the key column.
    _key_type: ClassVar[str]

    #: Maximum number of keys in one statement, or ``None`` if unlimited.
    _max_variables: ClassVar[int | None] = None

    def __init__(
        self,
        database: Path | str,
        *,
        codec: Codec | None = None,
        read_only: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(codec=codec)
        check_sql_codec(self._codec)
        self._database = database
        self._read_only = read_only
        self._kwargs = kwargs
        # Held by every write, for a backend whose transactions alone do
        # not isolate the writers of one database.
        self._write_lock: contextlib.AbstractContextManager[Any] = contextlib.nullcontext()

    def filter_items(self, **field_filters: Any) -> dict[str, dict[str, Any]]:
        r"""Like :meth:`filter`, but keyed by the keys of the matching
        values.

        This lets callers that need to know which key each matching
        value belongs to (e.g. a record store layered on top) filter in
        SQL instead of reading every value.

        Args:
            **field_filters: The value that each field must be equal to.
                Calling with no arguments returns every pair.

        Returns:
            The matching values, keyed by their keys.

        Raises:
            RuntimeError: If the store is closed.
            ValueError: If a field name cannot be used in SQL (JSON codec
                only).
        """
        check_is_open(self)
        matches: dict[str, dict[str, Any]] = {}
        for batch in self._batches(self._filter_candidates, field_filters):
            matches.update(self._matching_items(batch, field_filters))
        return matches

    async def afilter_items(self, **field_filters: Any) -> dict[str, dict[str, Any]]:
        r"""Async equivalent of :meth:`filter_items`."""
        check_is_open(self)
        matches: dict[str, dict[str, Any]] = {}
        async with contextlib.aclosing(self._afilter_candidates(field_filters)) as batches:
            async for batch in batches:
                matches.update(self._matching_items(batch, field_filters))
        return matches

    def to_uri(self) -> str:
        return encode_sql_uri(self._scheme, self._database, self._codec)

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False, **kwargs: Any) -> Self:
        r"""Reconstruct a store from a URI produced by :meth:`to_uri`.

        The scheme of the URI gives the codec. The other arguments of the
        constructor are not part of the URI: pass them again.

        Args:
            uri: A URI produced by :meth:`to_uri`.
            read_only: Whether to open the database read-only.
            **kwargs: The other keyword arguments of the constructor.
                A ``codec`` must have the name of the codec of the scheme.

        Returns:
            A new store instance, not opened.

        Raises:
            ValueError: If the scheme of ``uri`` is not one of this class,
                or if ``codec`` does not match it.
        """
        database, codec = decode_sql_uri(uri, scheme=cls._scheme, codec=kwargs.pop("codec", None))
        kwargs = {**cls._uri_kwargs(database), **kwargs}
        return cls(database, codec=codec, read_only=read_only, **kwargs)

    @classmethod
    def _uri_kwargs(cls, database: str) -> dict[str, Any]:
        r"""Return the keyword arguments that the constructor needs to
        use the database of a URI.

        Args:
            database: The database decoded from the URI.

        Returns:
            The keyword arguments. The default is none.
        """
        del database
        return {}

    ##########################
    #     Backend access     #
    ##########################

    @abstractmethod
    def _fetch(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        r"""Run a query and read all its rows.

        Args:
            sql: The query.
            params: The values of its parameters.

        Returns:
            The rows.
        """

    @abstractmethod
    def _execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        r"""Run a statement that returns no row.

        Outside a transaction, the statement is committed.

        Args:
            sql: The statement.
            params: The values of its parameters.
        """

    @abstractmethod
    def _executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        r"""Run a statement once per row of parameters.

        It must be called inside a transaction.

        Args:
            sql: The statement.
            rows: The values of the parameters, one sequence per run.
        """

    @abstractmethod
    def _transaction(self) -> contextlib.AbstractContextManager[None]:
        r"""Run a block in a transaction.

        Returns:
            A context manager that commits if the block succeeds, and
            rolls back if it raises.
        """

    @abstractmethod
    def _table_columns(self) -> list[tuple[str, str, bool]]:
        r"""Describe the columns of the table of the store.

        Returns:
            The ``(name, type, is_primary_key)`` of each column, or an
            empty list if the table does not exist.
        """

    @abstractmethod
    def _filter_expr(self, field: str) -> str:
        r"""Build the SQL expression that reads a field of a JSON value.

        Args:
            field: The name of the field.

        Returns:
            The expression.

        Raises:
            ValueError: If ``field`` cannot be safely interpolated into
                SQL.
        """

    def _init_schema(self) -> None:
        r"""Create the table of the store if needed, and check that it
        matches the codec.

        Raises:
            ValueError: If the existing table does not match the codec,
                or if a read-only store has no table.
        """
        with self._write_lock:
            columns = self._table_columns()
            if not columns:
                if self._read_only:
                    msg = f"The database {str(self._database)!r} has no table 'store'"
                    raise ValueError(msg)
                self._execute(
                    "CREATE TABLE IF NOT EXISTS store ("
                    f"key {self._key_type} PRIMARY KEY, "
                    f"value {value_column_type(self._codec)} NOT NULL)"
                )
                # Read again: another writer may have created the table.
                columns = self._table_columns()
        check_table_layout(
            columns, codec=self._codec, key_type=self._key_type, database=self._database
        )

    ######################
    #     Primitives     #
    ######################

    def _get_many(self, keys: list[str]) -> dict[str, Payload]:
        # The shortest statement for the most frequent read.
        if len(keys) == 1:
            return dict(self._fetch(_SELECT_ONE, keys))
        payloads: dict[str, Payload] = {}
        for chunk in self._chunks(keys):
            placeholders = ", ".join("?" * len(chunk))
            payloads.update(self._fetch(f"{_SELECT_ALL} WHERE key IN ({placeholders})", chunk))
        return payloads

    def _contains_many(self, keys: list[str]) -> set[str]:
        found: set[str] = set()
        for chunk in self._chunks(keys):
            placeholders = ", ".join("?" * len(chunk))
            rows = self._fetch(f"{_SELECT_KEYS} WHERE key IN ({placeholders})", chunk)
            found.update(row[0] for row in rows)
        return found

    def _put_many(self, items: dict[str, Payload]) -> None:
        rows = list(items.items())
        with self._write_lock:
            # One statement is atomic without an explicit transaction.
            if len(rows) == 1:
                self._execute(_UPSERT, rows[0])
                return
            with self._transaction():
                self._executemany(_UPSERT, rows)

    def _update(self, keys: list[str], plan: Plan) -> None:
        with self._write_lock, self._transaction():
            if items := plan(self._get_many(keys)):
                self._executemany(_UPSERT, list(items.items()))

    def _delete_many(self, keys: list[str]) -> None:
        chunks = list(self._chunks(keys))
        with self._write_lock:
            if len(chunks) == 1:
                self._delete_chunk(chunks[0])
                return
            with self._transaction():
                for chunk in chunks:
                    self._delete_chunk(chunk)

    def _clear(self) -> None:
        with self._write_lock:
            self._execute(_DELETE_ALL)

    def _count(self) -> int:
        return self._fetch("SELECT COUNT(*) FROM store")[0][0]

    def _iter_batches(self, batch_size: int) -> Iterator[dict[str, Payload]]:
        # Keyset pagination: a row deleted or written between two batches
        # does not move the other rows, unlike with OFFSET.
        rows = self._fetch(_SELECT_FIRST_BATCH, [batch_size])
        while rows:
            yield dict(rows)
            if len(rows) < batch_size:
                return
            rows = self._fetch(_SELECT_NEXT_BATCH, [rows[-1][0], batch_size])

    def _iter_key_batches(self, batch_size: int) -> Iterator[list[str]]:
        # As _iter_batches, without reading the values.
        rows = self._fetch(_SELECT_FIRST_KEYS, [batch_size])
        while rows:
            yield [row[0] for row in rows]
            if len(rows) < batch_size:
                return
            rows = self._fetch(_SELECT_NEXT_KEYS, [rows[-1][0], batch_size])

    def _filter_candidates(self, fields: Mapping[str, Any]) -> Iterator[dict[str, Payload]]:
        if not self._filters_in_sql():
            return super()._filter_candidates(fields)
        return self._select_matches(fields)

    def _matching_values(
        self, batch: Mapping[str, Payload], fields: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        if not self._filters_in_sql():
            return super()._matching_values(batch, fields)
        # The rows were already selected by the database.
        decode = self._codec.decode
        return [decode(payload) for payload in batch.values()]

    ###########################
    #     Template helpers    #
    ###########################

    def _chunks(self, keys: list[str]) -> Iterator[list[str]]:
        r"""Split keys into the groups that one statement accepts.

        Args:
            keys: The keys to split.

        Yields:
            The groups of keys, in order.
        """
        if self._max_variables is None or len(keys) <= self._max_variables:
            yield keys
            return
        for chunk in batchify(keys, size=self._max_variables):
            yield list(chunk)

    def _delete_chunk(self, keys: list[str]) -> None:
        r"""Delete some keys with one statement.

        Args:
            keys: The keys to delete, at most ``_max_variables``.
        """
        placeholders = ", ".join("?" * len(keys))
        self._execute(f"{_DELETE_ALL} WHERE key IN ({placeholders})", keys)

    def _filters_in_sql(self) -> bool:
        r"""Indicate whether the database applies the filters.

        Returns:
            ``True`` if the codec is a
            :class:`~persista.store.JsonCodec`, whose payloads the database
            can read. Otherwise the filters are applied to the decoded
            values.
        """
        return type(self._codec) is JsonCodec

    def _select_matches(self, fields: Mapping[str, Any]) -> Iterator[dict[str, Payload]]:
        r"""Select with one query the rows that match a filter.

        Args:
            fields: The value that each field must be equal to.

        Yields:
            The matching pairs, in one batch, if there are any.

        Raises:
            ValueError: If a field name cannot be used in SQL.
        """
        where, params = build_where(fields, self._filter_expr)
        sql = f"{_SELECT_ALL} WHERE {where}" if where else _SELECT_ALL
        if rows := self._fetch(sql, params):
            yield dict(rows)

    def _matching_items(
        self, batch: Mapping[str, Payload], fields: Mapping[str, Any]
    ) -> dict[str, dict[str, Any]]:
        r"""Decode a batch of candidates and keep the pairs that match a
        filter.

        Args:
            batch: The payloads of the candidates, keyed by their key.
            fields: The value that each field must be equal to.

        Returns:
            The matching values, keyed by their key.
        """
        decode = self._codec.decode
        values = {key: decode(payload) for key, payload in batch.items()}
        if self._filters_in_sql():
            return values
        return {key: value for key, value in values.items() if self._matches(value, fields)}

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"database": self._database, "closed": self.closed}
        if self._codec.name != "json":
            kwargs["codec"] = self._codec
        if self._read_only:
            kwargs["read_only"] = True
        if not self.closed:
            kwargs["count"] = f"{self.count():,}"
        return kwargs | self._kwargs
