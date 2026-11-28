r"""Provide the code shared by the stores that keep their values in a SQL
table.

The table is named ``store`` and has two columns: ``key``, its primary
key, and ``value``, whose type depends on the codec of the store.
"""

from __future__ import annotations

__all__ = [
    "MAX_PUSH_DOWN_INT",
    "SQLStore",
    "build_where",
    "can_push_down",
    "check_sql_codec",
    "check_table_layout",
    "decode_sql_uri",
    "encode_sql_uri",
    "select_push_down_fields",
    "value_column_type",
]

import contextlib
from abc import abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

from coola.utils.batching import batchify

from persista.store.base import BaseStore
from persista.store.codec import JsonCodec
from persista.store.uri import decode_codec_uri, encode_path_uri
from persista.store.validation import is_valid_field_name

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping, Sequence
    from pathlib import Path
    from typing import Self

    from persista.store.codec import Codec
    from persista.store.types import Payload, Plan

#: The largest integer, in absolute value, that a filter selects in the
#: database: every integer up to it is exact as a floating-point number.
MAX_PUSH_DOWN_INT = 2**53 - 1

# The largest number of conditions of a filter that a query applies. The
# databases limit the size of a query, and the others are applied in Python.
_MAX_PUSH_DOWN_CONDITIONS = 100

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
    table: str = "store",
    column_types: Mapping[str, str] | None = None,
) -> None:
    r"""Check that an existing table can be used with a codec.

    Args:
        columns: The ``(name, type, is_primary_key)`` of every column of
            the table. The names and types are compared ignoring case.
        codec: The codec of the store.
        key_type: The expected type of the ``key`` column.
        database: The database of the table, used in the error message.
            It must not contain credentials.
        table: The name of the table, used in the error message.
        column_types: The type of the ``value`` column for each codec name,
            for a database whose types differ from those of
            :func:`value_column_type`.

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
    if column_types is None:
        value_type = value_column_type(codec)
    else:
        check_sql_codec(codec)
        value_type = column_types[codec.name]
    expected = [("key", key_type.upper(), True), ("value", value_type, False)]
    actual = sorted((name.lower(), dtype.upper(), bool(pk)) for name, dtype, pk in columns)
    if actual != expected:
        found = ", ".join(
            f"{name} {dtype}{' PRIMARY KEY' if pk else ''}" for name, dtype, pk in columns
        )
        msg = (
            f"The table {table!r} of {str(database)!r} does not match the codec {codec.name!r}: "
            f"expected the columns (key {key_type} PRIMARY KEY, value {value_type}), "
            f"found ({found})"
        )
        raise ValueError(msg)


def can_push_down(codec: Codec) -> bool:
    r"""Indicate whether a database can read the payloads of a codec, to
    select the candidates of a filter.

    Args:
        codec: The codec of the store.

    Returns:
        ``True`` for a :class:`~persista.store.JsonCodec`. A subclass of it
        can encode the values in another way, so it is ``False``.

    Example:
        ```pycon
        >>> from persista.store import JsonCodec, PickleCodec
        >>> from persista.store.sql import can_push_down
        >>> can_push_down(JsonCodec()), can_push_down(PickleCodec())
        (True, False)

        ```
    """
    return type(codec) is JsonCodec


def select_push_down_fields(fields: Mapping[str, Any]) -> dict[str, str | int]:
    r"""Select the conditions of a filter that a database can apply to
    JSON values without excluding a match.

    A condition is selected if the name of its field can be safely
    interpolated into SQL (see
    :func:`~persista.store.validation.is_valid_field_name`), and if its
    value is:

    - a ``str`` without a NUL character or a lone surrogate, which the
      databases cannot all compare; or
    - an ``int`` (not a ``bool``) between ``-MAX_PUSH_DOWN_INT`` and
      ``MAX_PUSH_DOWN_INT`` (``2**53 - 1``). The databases do not all read
      a larger number of a JSON value without rounding it.

    Args:
        fields: The expected value of each field.

    At most 100 conditions are selected, because the databases limit the
    size of a query.

    Returns:
        The selected conditions, in the order of ``fields``. An instance of
        a subclass of ``str`` or ``int`` is converted to the built-in type.

    Example:
        ```pycon
        >>> from persista.store.sql import select_push_down_fields
        >>> select_push_down_fields({"author": "Alice", "year": None, "user-id": 1, "page": 2})
        {'author': 'Alice', 'page': 2}

        ```
    """
    selected: dict[str, str | int] = {}
    for name, value in fields.items():
        if len(selected) == _MAX_PUSH_DOWN_CONDITIONS:
            break
        if not is_valid_field_name(name):
            continue
        # The conversions use the methods of the built-in types, which a
        # subclass cannot change.
        if isinstance(value, str):
            text = str.__str__(value)
            if chr(0) not in text and _is_unicode(text):
                selected[str.__str__(name)] = text
        elif isinstance(value, int) and not isinstance(value, bool):
            number = int.__int__(value)
            if -MAX_PUSH_DOWN_INT <= number <= MAX_PUSH_DOWN_INT:
                selected[str.__str__(name)] = number
    return selected


def _is_unicode(text: str) -> bool:
    r"""Indicate whether a string is valid Unicode.

    Args:
        text: The string to check.

    Returns:
        ``False`` if ``text`` contains a lone surrogate.
    """
    try:
        text.encode()
    except UnicodeEncodeError:
        return False
    return True


def build_where(
    fields: Mapping[str, Any],
    condition: Callable[[str, str | int], tuple[str, Sequence[Any]]],
) -> tuple[str, list[Any]]:
    r"""Build the ``WHERE`` clause that selects the candidates of a filter.

    Only the conditions given by :func:`select_push_down_fields` are in the
    clause, so the rows that it selects are a superset of the matches.

    Args:
        fields: The expected value of each field.
        condition: A function that returns the SQL condition of a field
            and its parameters. The condition must be true for every row
            whose field is equal to the value. The function must raise if
            the field name cannot be safely interpolated into SQL.

    Returns:
        The condition, without ``WHERE`` (empty if no condition is
        selected), and the values of its parameters.

    Example:
        ```pycon
        >>> from persista.store.sql import build_where
        >>> build_where(
        ...     {"author": "Alice", "year": None}, lambda name, value: (f"{name} = ?", [value])
        ... )
        ('author = ?', ['Alice'])

        ```
    """
    conditions: list[str] = []
    params: list[Any] = []
    for name, value in select_push_down_fields(fields).items():
        text, values = condition(name, value)
        conditions.append(text)
        params.extend(values)
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
    ``_filter_condition``, and sets ``_scheme`` and ``_key_type``.

    With a :class:`~persista.store.JsonCodec`, the candidates of
    :meth:`filter` are selected with one query, whose ``WHERE`` clause
    applies the conditions on strings and integers (see
    :func:`select_push_down_fields`). The filter is then applied to the
    decoded values, as in every store. With another codec, every value is
    read.

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

    def to_uri(self) -> str:
        return encode_sql_uri(self._scheme, self._database, self._codec)

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False, **kwargs: Any) -> Self:
        r"""Reconstruct a store from a URI produced by :meth:`to_uri`.

        The scheme of the URI gives the codec. The other arguments of the
        constructor, such as the arguments of the driver, are not part of
        the URI: pass them again. The URI of a ``":memory:"`` database gives
        a new, empty database. A database file is an absolute path, so its
        URI is only valid on a machine with the same files (a SQLite
        ``file:`` URI is kept as it was given).

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
    def _filter_condition(self, field: str, value: str | int) -> tuple[str, list[Any]]:
        r"""Build the SQL condition that selects the rows whose JSON
        value may have a field equal to a value.

        Args:
            field: The name of the field.
            value: The value, as selected by
                :func:`select_push_down_fields`.

        Returns:
            A condition that is true for every row whose field is equal to
            ``value``, and the values of its parameters.

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
                    msg = f"The database {str(self._safe_database())!r} has no table 'store'"
                    raise ValueError(msg)
                self._execute(
                    "CREATE TABLE IF NOT EXISTS store ("
                    f"key {self._key_type} PRIMARY KEY, "
                    f"value {value_column_type(self._codec)} NOT NULL)"
                )
                # Read again: another writer may have created the table.
                columns = self._table_columns()
        check_table_layout(
            columns, codec=self._codec, key_type=self._key_type, database=self._safe_database()
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
        if not can_push_down(self._codec):
            return super()._filter_candidates(fields)
        return self._select_candidates(fields)

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

    def _select_candidates(self, fields: Mapping[str, Any]) -> Iterator[dict[str, Payload]]:
        r"""Select with one query the rows that may match a filter.

        Args:
            fields: The value that each field must be equal to.

        Yields:
            A superset of the matching pairs, in one batch, if it is not
            empty.
        """
        where, params = build_where(fields, self._filter_condition)
        sql = f"{_SELECT_ALL} WHERE {where}" if where else _SELECT_ALL
        if rows := self._fetch(sql, params):
            yield dict(rows)

    def _safe_database(self) -> Path | str:
        r"""Return the location of the database as a repr, a log message
        or an error can show it.

        Returns:
            The database. A subclass removes what could be secret.
        """
        return self._database

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"database": self._safe_database(), "closed": self.closed}
        if self._codec.name != "json":
            kwargs["codec"] = self._codec
        if self._read_only:
            kwargs["read_only"] = True
        # The arguments of the driver are left out: they could hold secrets.
        return kwargs
