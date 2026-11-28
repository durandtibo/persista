r"""Provide a PostgreSQL-backed implementation of ``BaseStore``."""

from __future__ import annotations

__all__ = ["MAX_KEY_BYTES", "PostgresStore"]

import asyncio
import contextlib
import functools
import logging
import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote, urlencode

from coola.display import MultilineDisplayMixin
from coola.utils.imports import lazy_import

from persista.store.base import BaseStore
from persista.store.loop_clients import LoopClients
from persista.store.sql import build_where, can_push_down, check_sql_codec, check_table_layout
from persista.store.validation import check_is_open, validate_field_name, validate_table_name
from persista.utils.imports import check_psycopg

if TYPE_CHECKING:
    from collections.abc import (
        AsyncGenerator,
        Awaitable,
        Callable,
        Generator,
        Iterable,
        Iterator,
        Mapping,
        Sequence,
    )
    from typing import LiteralString, Self

    from persista.store.codec import Codec
    from persista.store.types import Payload, Plan

    # The named parameters of a query.
    _Params = dict[str, Any]

if TYPE_CHECKING:
    import psycopg
    import psycopg.conninfo
    from psycopg import sql
else:
    # Imported when the first store is opened, or when the repr or the URI
    # of a store needs the library to read the connection string.
    psycopg = lazy_import("psycopg")
    sql = lazy_import("psycopg.sql")

logger: logging.Logger = logging.getLogger(__name__)

# The longest key, in UTF-8 bytes. An entry of a B-tree index, such as the
# one of the primary key, takes at most 2704 bytes with the default page
# size of 8 kB, 12 of which are not the key. PostgreSQL compresses the
# long entries, so its index accepts some longer keys, depending on their
# content: they are rejected too.
MAX_KEY_BYTES = 2692

# The longest name that PostgreSQL does not truncate.
_MAX_TABLE_NAME_LENGTH = 63

# A write of more keys locks the whole table instead of each key. The
# server keeps its locks in a table of fixed size, sized for 64 locks per
# transaction (max_locks_per_transaction) by default.
_MAX_KEY_LOCKS = 64

# The first number of the advisory locks of the tables, and of the locks
# that serialize the creation of a table. A lock identified by two numbers
# never collides with the lock of a key, identified by one number.
_TABLE_LOCK_SPACE = 0x70657273
_CREATE_LOCK_SPACE = 0x70657274

# The statements that take the advisory locks of a write, as the FROM
# clause of a query, which no row of the query can precede. Every write
# first locks the table, then its keys in the order of the numbers of
# their locks (two keys can have the same number), so two transactions
# cannot wait for each other.
_LOCKS: dict[str, LiteralString] = {
    # One key. The columns are evaluated in order.
    "key": (
        "(SELECT pg_advisory_xact_lock_shared(%(space)s, to_regclass(%(table)s)::oid::int), "
        "pg_advisory_xact_lock("
        "hashtextextended(%(key)s::text, to_regclass(%(table)s)::oid::bigint))) AS locks"
    ),
    # Several keys. The lock of the table is taken to produce the rows that
    # are sorted before the first key is locked.
    "keys": (
        "(SELECT count(pg_advisory_xact_lock(id)) FROM ("
        "SELECT DISTINCT hashtextextended(name, to_regclass(%(table)s)::oid::bigint) AS id "
        "FROM (SELECT pg_advisory_xact_lock_shared("
        "%(space)s, to_regclass(%(table)s)::oid::int)) AS table_lock, "
        "unnest(%(keys)b::text[]) AS name ORDER BY id) AS ids) AS locks"
    ),
    # The whole table, which excludes every other write.
    "table": (
        "(SELECT pg_advisory_xact_lock(%(space)s, to_regclass(%(table)s)::oid::int)) AS locks"
    ),
}

# The isolation level of the statements that run outside a transaction.
_SET_ISOLATION = "SET default_transaction_isolation = 'read committed'"

# Number of keys that filter() and keys() read at a time.
_SCAN_BATCH_SIZE = 256

# The type of the value column for each codec name.
_VALUE_COLUMN_TYPES: dict[str, str] = {"json": "JSONB", "pickle": "BYTEA"}

_URL_SCHEMES = frozenset({"postgres", "postgresql"})

# How a JSON document writes a NUL character in a string.
_NUL_ESCAPE = chr(92) + "u0000"

# That escape, after an even number of backslashes: otherwise its backslash
# is itself escaped.
_JSON_NUL = re.compile(r"(?<!\\)(?:\\\\)*" + re.escape(_NUL_ESCAPE))

# A string of a JSON document, or a number written with a positive
# exponent. The strings are matched so that their content is skipped.
_JSON_STRING_OR_LARGE_NUMBER = re.compile(r'("[^"\\]*(?:\\.[^"\\]*)*")|(-?\d+(?:\.\d+)?e\+\d+)')


class PostgresStore(BaseStore, MultilineDisplayMixin):
    r"""A PostgreSQL-backed key-value store.

    The values are kept in a table with two columns: ``key``, a ``TEXT``
    primary key, and ``value``, whose type depends on the codec. With the
    default :class:`~persista.store.JsonCodec`, the column is ``JSONB``,
    which any PostgreSQL client can query, and :meth:`filter` uses it to
    read only the values that may match a condition on a string or an
    integer (see :func:`~persista.store.sql.select_push_down_fields`).
    With a :class:`~persista.store.PickleCodec`, it is ``BYTEA``: the
    values keep their Python types, and :meth:`filter` reads every
    value.

    Opening the store creates the table if it does not exist, in the first
    schema of the search path. It raises ``ValueError`` if an existing table
    does not have exactly the columns of the codec.

    Limits, which raise ``ValueError`` before anything is written:

    - a key must be valid Unicode without a NUL character, and have at
      most 2692 bytes in UTF-8, the largest size that the index of the
      primary key accepts whatever the content of the key (with the
      default page size). Every method that takes a key checks it;
    - with the JSON codec, a string of a value must not contain a NUL
      character, which ``JSONB`` cannot keep.

    ``JSONB`` also keeps the numbers as decimals, so ``-0.0`` is read back as
    ``0.0``, and it does not keep the order of the keys of a ``dict``.

    A write or a delete runs in one transaction, which first takes
    advisory locks: a shared lock of the table and an exclusive lock of
    each key, or, for more than 64 keys and for :meth:`clear`, an exclusive
    lock of the table, which makes the other writes of the table wait. So
    ``raise``, ``skip`` and ``merge`` are atomic against every other write and
    delete made by a ``PostgresStore``, in any process. Other programs that
    write to the table do not take these locks. The lock of a key is a
    64-bit hash of the key: two keys with the same hash only wait for each
    other. Reads take no lock.

    The sync methods use one connection, protected by the lock of the
    instance. The async methods use a ``psycopg.AsyncConnection``, without
    threads, which runs one operation at a time, so their transactions
    cannot nest. The async connection is created by the first async call
    in an event loop, belongs to that loop, and is only used by it:
    another event loop gets its own connection. It is closed by
    :meth:`aclose` in its loop, or when its loop shuts down its
    asynchronous generators, which ``asyncio.run`` does before it returns.
    :meth:`close` raises ``RuntimeError`` while an async connection is open:
    call ``await store.aclose()`` instead.

    An iteration reads the pairs in the order of the keys, with one query
    per batch, and keeps no transaction open between two batches. A pair
    written during the iteration may or may not be yielded.

    Args:
        conninfo: The connection string or URI passed to
            ``psycopg.connect`` (e.g.
            ``"postgresql://user:pass@localhost/dbname"``).
        codec: The codec of the values, a
            :class:`~persista.store.JsonCodec` (default) or a
            :class:`~persista.store.PickleCodec`. Decoding a pickle
            payload can execute arbitrary code: only use it with a
            trusted database.
        table: The name of the table of the store: letters, digits and
            underscores, not starting with a digit, at most 63 characters.
            Its case is significant.
        **kwargs: Additional keyword arguments of ``psycopg.connect`` and of
            its async equivalent, such as ``connect_timeout``.

    Raises:
        RuntimeError: If the ``psycopg`` package is not installed.
        ValueError: If the codec or the table name is not supported.

    Example:
        ```pycon
        >>> from persista.store import PostgresStore
        >>> with PostgresStore(  # doctest: +SKIP
        ...     "postgresql://user:pass@localhost/dbname"
        ... ) as store:
        ...     store.set_many(
        ...         {
        ...             "1": {"title": "Intro to Python", "author": "Alice"},
        ...             "2": {"title": "Advanced Python", "author": "Alice"},
        ...         }
        ...     )
        ...     len(store.filter(author="Alice"))
        ...
        2

        ```

        A pickle codec keeps Python types, in another table:

        ```pycon
        >>> from persista.store import PickleCodec, PostgresStore
        >>> with PostgresStore(  # doctest: +SKIP
        ...     "postgresql://user:pass@localhost/dbname", codec=PickleCodec(), table="tags"
        ... ) as store:
        ...     store.set("1", {"tags": {"python"}})
        ...     store.get("1")
        ...
        {'tags': {'python'}}

        ```
    """

    # No other task of the loop can create a new async connection between
    # the moment aclose() closes it and the moment it closes the store.
    _close_in_event_loop = True

    def __init__(
        self,
        conninfo: str,
        *,
        codec: Codec | None = None,
        table: str = "store",
        **kwargs: Any,
    ) -> None:
        check_psycopg()
        validate_table_name(table)
        if len(table) > _MAX_TABLE_NAME_LENGTH:
            msg = (
                f"Invalid table name: {table!r}. PostgreSQL keeps at most "
                f"{_MAX_TABLE_NAME_LENGTH} characters"
            )
            raise ValueError(msg)
        super().__init__(codec=codec)
        check_sql_codec(self._codec)
        self._conninfo = conninfo
        self._table = table
        self._kwargs = kwargs
        self._value_type = _VALUE_COLUMN_TYPES[self._codec.name]
        # The name of the table, as a SQL identifier.
        self._regclass = f'"{table}"'
        self._conn: psycopg.Connection | None = None
        self._aclients: LoopClients[_AsyncConnection] = LoopClients(
            self._create_async_connection,
            owner=type(self).__name__,
            abandon=_AsyncConnection.abandon,
        )

    @property
    def connection(self) -> psycopg.Connection:
        r"""Return the underlying sync psycopg connection.

        This is not part of the regular store API. It is meant for
        debugging or running specific commands. The store must be open.

        Raises:
            RuntimeError: If the store is not open.
        """
        if self._conn is None:
            msg = f"{type(self).__name__} is not open."
            raise RuntimeError(msg)
        return self._conn

    def to_uri(self) -> str:
        r"""Return a URI of the database.

        A connection string that is already a URI is returned as is, and
        a keyword/value connection string is turned into a URI. The URI
        contains the password if the connection string has one: treat it
        as a secret. It does not describe the table, the codec or the
        other arguments of the constructor.

        Returns:
            The URI.

        Raises:
            ValueError: If a keyword/value connection string cannot be
                read. The message does not quote it.
        """
        scheme, separator, _ = self._conninfo.partition("://")
        if separator and scheme.lower() in _URL_SCHEMES:
            return self._conninfo
        # The errors of the client library can quote the password.
        _check_conninfo(self._conninfo)
        return _conninfo_to_uri(self._conninfo)

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False, **kwargs: Any) -> Self:
        r"""Reconstruct a store from a URI produced by :meth:`to_uri`.

        The URI does not describe the table, the codec or the other
        arguments of the constructor: pass them again, otherwise the new
        store uses the table ``store`` and the
        :class:`~persista.store.JsonCodec`.

        Args:
            uri: A PostgreSQL connection URI.
            read_only: Ignored, since the store has no read-only mode.
            **kwargs: The keyword arguments of the constructor, such as
                ``codec`` or ``table``.

        Returns:
            A new store instance, not opened.
        """
        del read_only
        return cls(uri, **kwargs)

    ######################
    #     Primitives     #
    ######################

    def _open(self) -> None:
        check_psycopg()
        _check_conninfo(self._conninfo)
        self._build_queries()
        self._conn = psycopg.connect(self._conninfo, autocommit=True, **self._kwargs)
        # Each statement must see the writes committed before the locks of
        # its transaction were taken.
        self._conn.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
        self._conn.execute(_SET_ISOLATION)
        self._init_schema()

    def _close(self) -> None:
        if self._conn is None:
            return
        logger.info("Closing Postgres connection for table %s", self._table)
        self._conn.close()
        self._conn = None

    def _get_many(self, keys: list[str]) -> dict[str, Payload]:
        _check_keys(keys)
        return dict(self._fetch(*self._read_statement(keys)))

    def _put_many(self, items: dict[str, Payload]) -> None:
        _check_keys(list(items))
        # One statement, which is a transaction by itself: it takes the
        # locks before it writes, in one round trip.
        self.connection.execute(*self._write_statement(items))
        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    def _update(self, keys: list[str], plan: Plan) -> None:
        _check_keys(keys)
        with self._locked_transaction(keys) as connection:
            existing = dict(connection.execute(*self._read_statement(keys)).fetchall())
            if items := plan(existing):
                connection.execute(*self._write_statement(items))

    def _delete_many(self, keys: list[str]) -> None:
        _check_keys(keys)
        with self._locked_transaction(keys) as connection:
            connection.execute(self._delete, (keys,))

    def _clear(self) -> None:
        with self._locked_transaction(None) as connection:
            connection.execute(self._delete_all)

    def _count(self) -> int:
        return self._fetch(self._select_count)[0][0]

    def _contains_many(self, keys: list[str]) -> set[str]:
        _check_keys(keys)
        return {row[0] for row in self._fetch(self._select_keys, (keys,))}

    def _iter_batches(self, batch_size: int) -> Iterator[dict[str, Payload]]:
        # Keyset pagination: a row deleted or written between two batches
        # does not move the other rows, unlike with OFFSET.
        rows = self._fetch(self._select_first_batch, (batch_size,))
        while rows:
            yield dict(rows)
            if len(rows) < batch_size:
                return
            rows = self._fetch(self._select_next_batch, (rows[-1][0], batch_size))

    def _iter_key_batches(self, batch_size: int) -> Iterator[list[str]]:
        # As _iter_batches, without reading the values.
        rows = self._fetch(self._select_first_keys, (batch_size,))
        while rows:
            yield [row[0] for row in rows]
            if len(rows) < batch_size:
                return
            rows = self._fetch(self._select_next_keys, (rows[-1][0], batch_size))

    def _filter_candidates(self, fields: Mapping[str, Any]) -> Iterator[dict[str, Payload]]:
        if not can_push_down(self._codec):
            return super()._filter_candidates(fields)
        return self._select_candidates(fields)

    ############################
    #     Async primitives     #
    ############################

    async def _aget_many(self, keys: list[str]) -> dict[str, Payload]:
        _check_keys(keys)
        return dict(await self._afetch(*self._read_statement(keys)))

    async def _aput_many(self, items: dict[str, Payload]) -> None:
        _check_keys(list(items))
        statement = self._write_statement(items)
        async with self._async_connection() as connection:
            await connection.execute(*statement)
        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    async def _aupdate(self, keys: list[str], plan: Plan) -> None:
        _check_keys(keys)
        async with self._alocked_transaction(keys) as connection:
            cursor = await connection.execute(*self._read_statement(keys))
            if items := plan(dict(await cursor.fetchall())):
                await connection.execute(*self._write_statement(items))

    async def _adelete_many(self, keys: list[str]) -> None:
        _check_keys(keys)
        async with self._alocked_transaction(keys) as connection:
            await connection.execute(self._delete, (keys,))

    async def _aclear(self) -> None:
        async with self._alocked_transaction(None) as connection:
            await connection.execute(self._delete_all)

    async def _acount(self) -> int:
        return (await self._afetch(self._select_count))[0][0]

    async def _acontains_many(self, keys: list[str]) -> set[str]:
        _check_keys(keys)
        return {row[0] for row in await self._afetch(self._select_keys, (keys,))}

    async def _aiter_batches(self, batch_size: int) -> AsyncGenerator[dict[str, Payload]]:
        rows = await self._afetch(self._select_first_batch, (batch_size,))
        while rows:
            yield dict(rows)
            # The store may have been closed while the caller had the batch.
            check_is_open(self)
            if len(rows) < batch_size:
                return
            rows = await self._afetch(self._select_next_batch, (rows[-1][0], batch_size))

    async def _aiter_key_batches(self, batch_size: int) -> AsyncGenerator[list[str]]:
        rows = await self._afetch(self._select_first_keys, (batch_size,))
        while rows:
            yield [row[0] for row in rows]
            check_is_open(self)
            if len(rows) < batch_size:
                return
            rows = await self._afetch(self._select_next_keys, (rows[-1][0], batch_size))

    def _afilter_candidates(self, fields: Mapping[str, Any]) -> AsyncGenerator[dict[str, Payload]]:
        if not can_push_down(self._codec):
            return self._aiter_batches(_SCAN_BATCH_SIZE)
        return self._aselect_candidates(fields)

    async def _aclose(self) -> None:
        await self._aclients.aclose()

    def _check_close(self) -> None:
        self._aclients.check_none_open()

    ###########################
    #     Template helpers    #
    ###########################

    def _query(self, template: LiteralString, **parts: sql.Composable) -> sql.Composed:
        r"""Build a query on the table of the store.

        Args:
            template: The query, with a ``{table}`` placeholder and one
                placeholder per part.
            **parts: The SQL fragments of the other placeholders. They must
                not contain data given by a user.

        Returns:
            The query, with the quoted name of the table.
        """
        return sql.SQL(template).format(table=sql.Identifier(self._table), **parts)

    def _build_queries(self) -> None:
        r"""Build the queries of the table of the store, with the
        ``sql`` module of psycopg."""
        # JSONB is read as text, which the codec decodes.
        value: LiteralString = "value::text" if self._value_type == "JSONB" else "value"
        # The type of the array of the values of a write.
        array: LiteralString = "text[]" if self._value_type == "JSONB" else "bytea[]"
        value_type: LiteralString = "jsonb" if self._value_type == "JSONB" else "bytea"
        parts: dict[str, sql.Composable] = {
            "value": sql.SQL(value),
            "value_type": sql.SQL(value_type),
        }
        query = functools.partial(self._query, **parts)
        select: LiteralString = "SELECT key, {value} FROM {table}"
        self._create_table = query(
            "CREATE TABLE IF NOT EXISTS {table} (key TEXT PRIMARY KEY, value {value_type} NOT NULL)"
        )
        self._select = query(select)
        self._select_one = query(select + " WHERE key = %s")
        self._select_many = query(select + " WHERE key = ANY(%s)")
        self._select_first_batch = query(select + " ORDER BY key LIMIT %s")
        self._select_next_batch = query(select + " WHERE key > %s ORDER BY key LIMIT %s")
        self._select_keys = query("SELECT key FROM {table} WHERE key = ANY(%s)")
        self._select_first_keys = query("SELECT key FROM {table} ORDER BY key LIMIT %s")
        self._select_next_keys = query(
            "SELECT key FROM {table} WHERE key > %s ORDER BY key LIMIT %s"
        )
        # The lock of the table that PostgreSQL takes for a write.
        self._lock_relation = query("LOCK TABLE {table} IN ROW EXCLUSIVE MODE")
        self._delete = query("DELETE FROM {table} WHERE key = ANY(%s)")
        self._delete_all = query("DELETE FROM {table}")
        self._select_count = query("SELECT COUNT(*) FROM {table}")

        # The statements that take the locks of a write, and the statements
        # that add or replace pairs once they hold these locks, for each
        # kind of lock.
        rows: LiteralString = (
            "SELECT rows.key, rows.value::{value_type} FROM {locks}, "
            "unnest(%(keys)b::text[], %(values)b::{array}) AS rows (key, value)"
        )
        sources: dict[str, LiteralString] = {
            "key": "SELECT %(key)s::text, %(value)s::{value_type} FROM {locks}",
            "keys": rows,
            "table": rows,
        }
        self._lock_queries = {
            kind: query("SELECT 1 FROM {locks}", locks=sql.SQL(locks))
            for kind, locks in _LOCKS.items()
        }
        self._upsert_queries = {
            kind: query(
                "INSERT INTO {table} (key, value) {source} "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                source=sql.SQL(source).format(
                    locks=sql.SQL(_LOCKS[kind]),
                    value_type=sql.SQL(value_type),
                    array=sql.SQL(array),
                ),
            )
            for kind, source in sources.items()
        }

    def _init_schema(self) -> None:
        r"""Create the table of the store if needed, and check that it
        matches the codec.

        Raises:
            ValueError: If the existing table does not match the codec.
        """
        columns = self._table_columns()
        if not columns:
            # Two sessions that create the same table at the same time can
            # fail, even with IF NOT EXISTS: make them wait for each other.
            with self.connection.transaction():
                self.connection.execute(
                    "SELECT pg_advisory_xact_lock(%s, hashtext(%s))",
                    (_CREATE_LOCK_SPACE, self._table),
                )
                self.connection.execute(self._create_table)
            columns = self._table_columns()
        check_table_layout(
            columns,
            codec=self._codec,
            key_type="TEXT",
            database=_redact_conninfo(self._conninfo, self._kwargs),
            table=self._table,
            column_types=_VALUE_COLUMN_TYPES,
        )

    def _table_columns(self) -> list[tuple[str, str, bool]]:
        r"""Describe the columns of the table of the store.

        The table is the one that the queries of the store use, which
        depends on the search path.

        Returns:
            The ``(name, type, is_primary_key)`` of each column, or an
            empty list if the table does not exist.
        """
        return self._fetch(
            "SELECT a.attname::text, format_type(a.atttypid, a.atttypmod), "
            "COALESCE(a.attnum = ANY(i.indkey), FALSE) "
            "FROM pg_attribute AS a "
            "LEFT JOIN pg_index AS i ON i.indrelid = a.attrelid AND i.indisprimary "
            "WHERE a.attrelid = to_regclass(%s) AND a.attnum > 0 AND NOT a.attisdropped "
            "ORDER BY a.attnum",
            (self._regclass,),
        )

    def _fetch(
        self, query: LiteralString | sql.Composed, params: Sequence[Any] | None = None
    ) -> list[Any]:
        r"""Run a query and read all its rows.

        Args:
            query: The query.
            params: The values of its parameters.

        Returns:
            The rows.
        """
        return self.connection.execute(query, params).fetchall()

    async def _afetch(
        self, query: LiteralString | sql.Composed, params: Sequence[Any] | None = None
    ) -> list[Any]:
        r"""Async equivalent of :meth:`_fetch`.

        Args:
            query: The query.
            params: The values of its parameters.

        Returns:
            The rows.

        Raises:
            RuntimeError: If the store is closed or being closed.
        """
        holder = self._async_connection()
        async with holder as connection:
            cursor = await connection.execute(query, params)
            return await cursor.fetchall()

    def _read_statement(self, keys: list[str]) -> tuple[sql.Composed, tuple[Any, ...]]:
        r"""Build the statement that reads some keys.

        Args:
            keys: The keys to read. It must not be empty.

        Returns:
            The query and its parameters.
        """
        if len(keys) == 1:
            return self._select_one, (keys[0],)
        return self._select_many, (keys,)

    def _write_statement(self, items: Mapping[str, Payload]) -> tuple[sql.Composed, _Params]:
        r"""Build the statement that takes the locks of some pairs, then
        adds or replaces them.

        Args:
            items: The payloads to write, keyed by their unique key. It
                must not be empty.

        Returns:
            The query and its parameters.

        Raises:
            ValueError: If the table cannot keep a payload.
        """
        values: Iterable[Payload] = items.values()
        if self._value_type == "JSONB":
            values = map(_to_jsonb, values)
        keys = list(items)
        kind, params = self._lock_params(keys)
        if kind == "key":
            params["value"] = next(iter(values))
        else:
            params |= {"keys": keys, "values": list(values)}
        return self._upsert_queries[kind], params

    def _lock_statement(self, keys: list[str] | None) -> tuple[sql.Composed, _Params]:
        r"""Build the statement that takes the advisory locks of a write.

        The locks are released when the transaction ends.

        Args:
            keys: The keys that the transaction writes or deletes, or
                ``None`` for every key.

        Returns:
            The query and its parameters.
        """
        kind, params = self._lock_params(keys)
        return self._lock_queries[kind], params

    def _lock_params(self, keys: list[str] | None) -> tuple[str, _Params]:
        r"""Choose the locks of a write.

        Args:
            keys: The keys that the transaction writes or deletes, or
                ``None`` for every key. It must not be empty.

        Returns:
            The kind of lock (``"key"``, ``"keys"`` or ``"table"``) and
            the parameters of its statement.
        """
        params: _Params = {"space": _TABLE_LOCK_SPACE, "table": self._regclass}
        if keys is None or len(keys) > _MAX_KEY_LOCKS:
            return "table", params
        if len(keys) == 1:
            return "key", params | {"key": keys[0]}
        return "keys", params | {"keys": keys}

    @contextlib.contextmanager
    def _locked_transaction(self, keys: list[str] | None) -> Generator[psycopg.Connection]:
        r"""Run a block in a transaction that holds the locks of some
        keys.

        The statements are sent in a pipeline, if the client library
        supports it, so that they need fewer round trips.

        Args:
            keys: The keys that the block writes or deletes, or ``None``
                for every key.

        Yields:
            The connection of the transaction.
        """
        connection = self.connection
        with connection.transaction(), _pipeline(connection):
            # Before the advisory locks, as the statement of an upsert does:
            # otherwise a statement of another program that waits for the
            # table (CREATE INDEX) would make the writes wait for each other.
            connection.execute(self._lock_relation)
            connection.execute(*self._lock_statement(keys))
            yield connection

    @contextlib.asynccontextmanager
    async def _alocked_transaction(
        self, keys: list[str] | None
    ) -> AsyncGenerator[psycopg.AsyncConnection]:
        r"""Async equivalent of :meth:`_locked_transaction`, which also
        holds the async connection.

        Args:
            keys: The keys that the block writes or deletes, or ``None``
                for every key.

        Yields:
            The connection of the transaction.

        Raises:
            RuntimeError: If the store is closed or being closed.
        """
        holder = self._async_connection()
        async with (
            holder as connection,
            connection.transaction(),
            _pipeline(connection),
        ):
            await connection.execute(self._lock_relation)
            await connection.execute(*self._lock_statement(keys))
            yield connection

    @contextlib.asynccontextmanager
    async def _async_connection(self) -> AsyncGenerator[psycopg.AsyncConnection]:
        r"""Hold the async connection of the running event loop,
        connecting it if needed.

        The other calls of the loop that need it wait until the block ends,
        so the block must not ask for it again.

        Yields:
            The connection.

        Raises:
            RuntimeError: If the store is closed or being closed.
        """
        check_is_open(self)
        with await self._aclients.get() as client:
            async with client.exclusive() as connection:
                # The store may have been closed while the call was waiting.
                check_is_open(self)
                yield connection

    def _create_async_connection(self) -> _AsyncConnection:
        r"""Create the holder of the async connection of an event loop,
        which is not connected yet.

        Returns:
            A new holder.
        """
        return _AsyncConnection(self._connect_async)

    async def _connect_async(self) -> psycopg.AsyncConnection:
        r"""Open an async connection to the database.

        Returns:
            The connection.
        """
        connection = await psycopg.AsyncConnection.connect(
            self._conninfo, autocommit=True, **self._kwargs
        )
        try:
            await connection.set_isolation_level(psycopg.IsolationLevel.READ_COMMITTED)
            await connection.execute(_SET_ISOLATION)
        except BaseException:
            await connection.close()
            raise
        return connection

    def _filter_condition(self, field: str, value: str | int) -> tuple[str, list[Any]]:
        r"""Build the SQL condition that selects the rows whose JSON
        value may have a field equal to a value.

        A string is compared with the text of the field, which uses a
        B-tree index on ``(value->>'field')``. An integer is searched with
        the containment operator, which compares the ``JSONB`` numbers by
        their value, however they are written (``1`` or ``1.0``), and uses
        a GIN index on ``value``. It does not select a number that another
        program wrote with more digits than a float keeps (such as
        ``0.99999999999999999999``): ``PostgresStore`` writes none.

        Args:
            field: The name of the field.
            value: The value, as selected by
                :func:`~persista.store.sql.select_push_down_fields`.

        Returns:
            A condition that is true for every row whose field is equal to
            ``value``, and the values of its parameters.

        Raises:
            ValueError: If ``field`` cannot be safely interpolated into SQL.
        """
        validate_field_name(field)
        # The expressions of the documented indexes: they must not change.
        if isinstance(value, int):
            return "value @> %s::jsonb", [f'{{"{field}": {value}}}']
        return f"value->>'{field}' = %s::text", [value]

    def _filter_statement(self, fields: Mapping[str, Any]) -> tuple[sql.Composed, list[Any] | None]:
        r"""Build the query that selects the pairs that may match a
        filter.

        Args:
            fields: The value that each field must be equal to.

        Returns:
            The query and its parameters.
        """
        where, params = build_where(fields, self._filter_condition)
        if not where:
            return self._select, None
        # The field names are validated, and the values are parameters.
        condition = sql.SQL(cast("LiteralString", where))
        return sql.SQL(" WHERE ").join([self._select, condition]), params

    def _select_candidates(self, fields: Mapping[str, Any]) -> Iterator[dict[str, Payload]]:
        r"""Select with one query the pairs that may match a filter.

        Args:
            fields: The value that each field must be equal to.

        Yields:
            A superset of the matching pairs, in one batch, if it is not
            empty.
        """
        if rows := self._fetch(*self._filter_statement(fields)):
            yield dict(rows)

    async def _aselect_candidates(
        self, fields: Mapping[str, Any]
    ) -> AsyncGenerator[dict[str, Payload]]:
        r"""Async equivalent of :meth:`_select_candidates`.

        Args:
            fields: The value that each field must be equal to.

        Yields:
            A superset of the matching pairs, in one batch, if it is not
            empty.

        Raises:
            RuntimeError: If the store is closed during the iteration.
        """
        if rows := await self._afetch(*self._filter_statement(fields)):
            yield dict(rows)
            check_is_open(self)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "conninfo": _redact_conninfo(self._conninfo, self._kwargs),
            "table": self._table,
            "closed": self.closed,
        }
        if self._codec.name != "json":
            kwargs["codec"] = self._codec
        return kwargs


class _AsyncConnection:
    r"""Hold the async connection of one event loop, which one operation
    at a time can use.

    Args:
        connect: A function that opens a connection. It is called by the
            first operation, and again after a connection was discarded.
    """

    def __init__(self, connect: Callable[[], Awaitable[psycopg.AsyncConnection]]) -> None:
        self._connect = connect
        self._connection: psycopg.AsyncConnection | None = None
        self._lock = asyncio.Lock()

    @contextlib.asynccontextmanager
    async def exclusive(self) -> AsyncGenerator[psycopg.AsyncConnection]:
        r"""Use the connection while no other operation uses it.

        A connection that is broken, or still in a transaction, when the
        block ends (e.g. after a network error) is closed, and the next
        operation opens a new one.

        Yields:
            The open connection.
        """
        # The lock is what keeps two transactions from being nested.
        lock = self._lock
        async with lock:
            if self._connection is None or self._connection.closed:
                self._connection = await self._connect()
            connection = self._connection
            try:
                yield connection
            finally:
                if (
                    connection.closed
                    or connection.info.transaction_status != psycopg.pq.TransactionStatus.IDLE
                ):
                    self._connection = None
                    await connection.close()

    async def aclose(self) -> None:
        r"""Close the connection, if it is open."""
        connection, self._connection = self._connection, None
        if connection is not None:
            await connection.close()

    def abandon(self) -> None:
        r"""Close the socket of the connection without an event loop,
        for a connection whose event loop is closed."""
        connection, self._connection = self._connection, None
        if connection is not None:
            connection.pgconn.finish()


def _pipeline(connection: Any) -> Any:
    r"""Return the context manager that sends the statements of a block
    in a pipeline.

    Args:
        connection: A sync or async connection.

    Returns:
        The pipeline of the connection, or a context manager that does
        nothing if the client library does not support pipelines.
    """
    if psycopg.Pipeline.is_supported():
        return connection.pipeline()
    return contextlib.nullcontext()


def _check_keys(keys: list[str]) -> None:
    r"""Check that the table can keep some keys.

    Args:
        keys: The keys.

    Raises:
        ValueError: If a key contains a NUL character or a lone surrogate,
            or has more than :data:`MAX_KEY_BYTES` bytes in UTF-8.
    """
    for key in keys:
        try:
            size = len(key.encode())
        except UnicodeEncodeError as exc:
            msg = (
                "A key of PostgresStore must be valid Unicode, but it has a lone surrogate: "
                f"{key!r}"
            )
            raise ValueError(msg) from exc
        if size > MAX_KEY_BYTES:
            msg = (
                f"A key of PostgresStore has at most {MAX_KEY_BYTES} bytes in UTF-8, but a key "
                f"has {size} bytes: {key[:50]!r}..."
            )
            raise ValueError(msg)
        if chr(0) in key:
            msg = f"A key of PostgresStore cannot contain a NUL character: {key!r}"
            raise ValueError(msg)


def _to_jsonb(payload: Payload) -> str:
    r"""Adapt a JSON document to a ``JSONB`` column.

    ``JSONB`` keeps a number as a decimal, and writes it back without an
    exponent: a large float such as ``1e+22`` would be read back as an
    integer. Such a number is therefore written in full, with a decimal
    point.

    Args:
        payload: A JSON document, as a ``str`` or as UTF-8 ``bytes``.

    Returns:
        The document to write.

    Raises:
        ValueError: If a string of the document contains a NUL character.
    """
    if isinstance(payload, bytes):
        payload = payload.decode()
    # The fast tests first: most documents need no change.
    if chr(92) in payload and _NUL_ESCAPE in payload and _JSON_NUL.search(payload):
        msg = "PostgresStore cannot keep a NUL character in a string of a value with a JSON codec"
        raise ValueError(msg)
    # A single character is found much faster than two.
    if "+" in payload and "e+" in payload:
        payload = _JSON_STRING_OR_LARGE_NUMBER.sub(_expand_number, payload)
    return payload


def _expand_number(match: re.Match[str]) -> str:
    r"""Write a number of a JSON document without an exponent.

    Args:
        match: A match of a string, or of a number with an exponent.

    Returns:
        The string unchanged, or the number written in full with a decimal
        point.
    """
    string, number = match.groups()
    if string is not None:
        return string
    return f"{Decimal(number):f}.0"


def _parse_location(conninfo: str, kwargs: Mapping[str, Any]) -> tuple[str, str, str] | None:
    r"""Read the host, the port and the database of a connection.

    Args:
        conninfo: A connection string or URI.
        kwargs: The keyword arguments of the connection, which take
            precedence over the string.

    Returns:
        The host, the port and the database name, each possibly empty, or
        ``None`` if the string cannot be read, or if it seems to contain
        credentials that are not percent-encoded.
    """
    try:
        params: dict[str, Any] = dict(psycopg.conninfo.conninfo_to_dict(conninfo))
    except psycopg.ProgrammingError:
        return None
    names = ("host", "port", "dbname")
    params.update({name: kwargs[name] for name in names if name in kwargs})
    host, port, dbname = (str(params.get(name) or "") for name in names)
    # An "@" inside the host (a leading one names a Unix socket) or in the
    # path of a URI, or a port that is not a number, means that a password is
    # not percent-encoded.
    _, _, location = conninfo.partition("://")
    path = location.partition("/")[2].partition("?")[0]
    if "@" in host[1:] or "@" in path or not re.fullmatch(r"[0-9,]*", port):
        return None
    return host, port, dbname


def _check_conninfo(conninfo: str) -> None:
    r"""Check that a connection string can be read and gives a plausible
    location.

    The errors of the client library for a malformed string can quote the
    password, which this error does not.

    Args:
        conninfo: A connection string or URI.

    Raises:
        ValueError: If ``conninfo`` cannot be read, or if its host or its
            port looks like a part of the credentials.
    """
    if _parse_location(conninfo, {}) is None:
        msg = (
            "Invalid PostgreSQL connection string: it cannot be read. In a URI, "
            "percent-encode the special characters of the username and of the password; in "
            "a keyword/value string, quote the values that contain spaces"
        )
        raise ValueError(msg)


def _redact_conninfo(conninfo: str, kwargs: Mapping[str, Any]) -> str:
    r"""Return the location of a connection, without its credentials.

    Only the host, the port and the database name are kept.

    Args:
        conninfo: A connection string or URI.
        kwargs: The keyword arguments of the connection.

    Returns:
        The location as a ``postgresql://`` URI, or a placeholder if it
        cannot be read safely.

    Example:
        ```pycon
        >>> from persista.store.postgres import _redact_conninfo
        >>> _redact_conninfo("postgresql://user:secret@localhost:5432/db", {})
        'postgresql://localhost:5432/db'

        ```
    """
    location = _parse_location(conninfo, kwargs)
    # A database name that is itself a connection string can contain a
    # password.
    if location is None or any(text in location[2] for text in ("=", "://", "@")):
        return "<hidden PostgreSQL conninfo>"
    host, port, dbname = location
    netloc = f"{host}:{port}" if port else host
    return f"postgresql://{netloc}/{dbname}"


def _conninfo_to_uri(conninfo: str) -> str:
    r"""Turn a keyword/value connection string into a URI.

    Args:
        conninfo: A connection string such as ``"dbname=foo host=bar"``.

    Returns:
        The equivalent ``postgresql://`` URI, with the special characters
        percent-encoded.

    Example:
        ```pycon
        >>> from persista.store.postgres import _conninfo_to_uri
        >>> _conninfo_to_uri("host=localhost dbname=db user=ann password=p@ss")
        'postgresql://ann:p%40ss@localhost/db'

        ```
    """
    params = {
        name: str(value) for name, value in psycopg.conninfo.conninfo_to_dict(conninfo).items()
    }
    user = params.pop("user", None)
    password = params.pop("password", None)
    host = params.pop("host", "")
    port = params.pop("port", "")
    dbname = params.pop("dbname", "")
    netloc = ""
    if "," in host or "," in port:
        # The hosts and ports of several servers cannot be written in the
        # location of a URI.
        params |= {name: value for name, value in (("host", host), ("port", port)) if value}
    else:
        # A colon is part of an IPv6 address, written between brackets.
        netloc = f"[{host}]" if ":" in host else quote(host, safe="")
        if port:
            netloc = f"{netloc}:{port}"
    if user or password:
        auth = quote(user or "", safe="")
        if password:
            auth = f"{auth}:{quote(password, safe='')}"
        netloc = f"{auth}@{netloc}"
    query = urlencode(params, quote_via=quote)
    uri = f"postgresql://{netloc}/{quote(dbname, safe='')}"
    return f"{uri}?{query}" if query else uri
