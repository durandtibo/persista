r"""Implement ready-to-use record stores backed by ``persista``
stores."""

from __future__ import annotations

__all__ = [
    "DuckDBRecordStore",
    "InMemoryRecordStore",
    "SQLiteRecordStore",
    "TypedDuckDBRecordStore",
    "TypedSQLiteRecordStore",
]

from typing import TYPE_CHECKING, Any, ClassVar

from persista.record.store.record import RecordStore
from persista.store import InMemoryStore, TypedDuckDBStore, TypedSQLiteStore

if TYPE_CHECKING:
    from pathlib import Path


class _UntypedRecordStore(RecordStore):
    r"""Base class for a :class:`~persista.record.store.RecordStore`
    backed by a SQL database, with record metadata stored as JSON.

    Subclasses only need to set ``_store_cls`` to the underlying typed
    SQL store class (e.g. :class:`persista.store.TypedDuckDBStore`);
    every metadata field is stored in that store's JSON overflow
    column, with no fixed schema. Use the corresponding ``Typed*``
    record store instead when metadata fields should be stored as
    their own SQL columns.

    Args:
        database: The path to the database file, or ``":memory:"``
            for an in-memory database.
        **kwargs: Additional keyword arguments passed to
            ``_store_cls``.
    """

    # Typed as `Any` rather than `type[BaseStore]`: subclasses of
    # BaseStore have varying constructor signatures (e.g. an optional
    # `value_schema` keyword), so a precise callable type here would
    # not usefully constrain subclasses anyway.
    _store_cls: ClassVar[Any]

    def __init__(self, database: Path | str = ":memory:", **kwargs: Any) -> None:
        super().__init__(self._store_cls(database, **kwargs))


class _TypedRecordStore(RecordStore):
    r"""Base class for a :class:`~persista.record.store.RecordStore`
    backed by a SQL database, with each record metadata field stored as
    its own typed SQL column.

    Subclasses only need to set ``_store_cls`` to the underlying typed
    SQL store class (e.g. :class:`persista.store.TypedDuckDBStore`).
    Use this store when record metadata follows a known, fixed schema
    and individual metadata fields should be queryable as SQL columns.
    Use the corresponding untyped record store instead when records
    may have arbitrary or varying metadata.

    Args:
        database: The path to the database file, or ``":memory:"``
            for an in-memory database.
        metadata_schema: A mapping from metadata field name to its SQL
            column type declaration (e.g. ``{"author": "TEXT"}``).
            ``None`` is equivalent to an empty mapping, i.e. no
            metadata columns beyond the JSON overflow column.
        **kwargs: Additional keyword arguments passed to
            ``_store_cls``.
    """

    # Typed as `Any` rather than `type[BaseStore]`: subclasses of
    # BaseStore have varying constructor signatures (e.g. an optional
    # `value_schema` keyword), so a precise callable type here would
    # not usefully constrain subclasses anyway.
    _store_cls: ClassVar[Any]

    def __init__(
        self,
        database: Path | str = ":memory:",
        metadata_schema: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(self._store_cls(database, value_schema=metadata_schema, **kwargs))


class DuckDBRecordStore(_UntypedRecordStore):
    r"""Implement a :class:`~persista.record.store.RecordStore` backed by
    a DuckDB database, with record metadata stored as JSON.

    This is a convenience wrapper around
    :class:`persista.store.TypedDuckDBStore` with no fixed schema, so
    every metadata field is stored in the JSON overflow column. Use
    :class:`TypedDuckDBRecordStore` instead when metadata fields
    should be stored as their own SQL columns.

    Args:
        database: The path to the DuckDB database file, or
            ``":memory:"`` for an in-memory database.
        **kwargs: Additional keyword arguments passed to
            :class:`persista.store.TypedDuckDBStore`.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.store import DuckDBRecordStore
        >>> with DuckDBRecordStore() as store:
        ...     store.set_many([Record(id="1", metadata={"author": "Alice"})])
        ...     store.get("1")
        ...
        Record(id='1', metadata={'author': 'Alice'})

        ```
    """

    _store_cls = TypedDuckDBStore


class TypedDuckDBRecordStore(_TypedRecordStore):
    r"""Implement a :class:`~persista.record.store.RecordStore` backed by
    a DuckDB database, with each record metadata field stored as its own
    typed SQL column.

    This is a convenience wrapper around
    :class:`persista.store.TypedDuckDBStore` configured with one
    column per metadata field declared in ``metadata_schema``.

    Use this store when record metadata follows a known, fixed schema
    and individual metadata fields should be queryable as SQL columns.
    Use :class:`DuckDBRecordStore` instead when records may have
    arbitrary or varying metadata.

    Args:
        database: The path to the DuckDB database file, or
            ``":memory:"`` for an in-memory database.
        metadata_schema: A mapping from metadata field name to its SQL
            column type declaration (e.g. ``{"author": "TEXT"}``).
            ``None`` is equivalent to an empty mapping, i.e. no
            metadata columns beyond the JSON overflow column.
        **kwargs: Additional keyword arguments passed to
            :class:`persista.store.TypedDuckDBStore`.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.store import TypedDuckDBRecordStore
        >>> with TypedDuckDBRecordStore(metadata_schema={"author": "TEXT"}) as store:
        ...     store.set_many([Record(id="1", metadata={"author": "Alice"})])
        ...     store.get("1")
        ...
        Record(id='1', metadata={'author': 'Alice'})

        ```
    """

    _store_cls = TypedDuckDBStore


class InMemoryRecordStore(RecordStore):
    r"""Implement a :class:`~persista.record.store.RecordStore` backed by
    a plain in-memory dictionary store.

    This is a convenience wrapper around
    :class:`persista.store.InMemoryStore`, useful for tests, examples,
    and other scenarios where records do not need to be persisted
    across processes.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.store import InMemoryRecordStore
        >>> with InMemoryRecordStore() as store:
        ...     store.set_many([Record(id="1", metadata={"author": "Alice"})])
        ...     store.get("1")
        ...
        Record(id='1', metadata={'author': 'Alice'})

        ```
    """

    def __init__(self) -> None:
        super().__init__(InMemoryStore())


class SQLiteRecordStore(_UntypedRecordStore):
    r"""Implement a :class:`~persista.record.store.RecordStore` backed by
    a SQLite database, with record metadata stored as JSON.

    This is a convenience wrapper around
    :class:`persista.store.TypedSQLiteStore` with no fixed schema, so
    every metadata field is stored in the JSON overflow column. Use
    :class:`TypedSQLiteRecordStore` instead when metadata fields
    should be stored as their own SQL columns.

    Args:
        database: The path to the SQLite database file, or
            ``":memory:"`` for an in-memory database.
        **kwargs: Additional keyword arguments passed to
            :class:`persista.store.TypedSQLiteStore`.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.store import SQLiteRecordStore
        >>> with SQLiteRecordStore() as store:
        ...     store.set_many([Record(id="1", metadata={"author": "Alice"})])
        ...     store.get("1")
        ...
        Record(id='1', metadata={'author': 'Alice'})

        ```
    """

    _store_cls = TypedSQLiteStore


class TypedSQLiteRecordStore(_TypedRecordStore):
    r"""Implement a :class:`~persista.record.store.RecordStore` backed by
    a SQLite database, with each record metadata field stored as its own
    typed SQL column.

    This is a convenience wrapper around
    :class:`persista.store.TypedSQLiteStore` configured with one
    column per metadata field declared in ``metadata_schema``.

    Use this store when record metadata follows a known, fixed schema
    and individual metadata fields should be queryable as SQL columns.
    Use :class:`SQLiteRecordStore` instead when records may have
    arbitrary or varying metadata.

    Args:
        database: The path to the SQLite database file, or
            ``":memory:"`` for an in-memory database.
        metadata_schema: A mapping from metadata field name to its SQL
            column type declaration (e.g. ``{"author": "TEXT"}``).
            ``None`` is equivalent to an empty mapping, i.e. no
            metadata columns beyond the JSON overflow column.
        **kwargs: Additional keyword arguments passed to
            :class:`persista.store.TypedSQLiteStore`.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.store import TypedSQLiteRecordStore
        >>> with TypedSQLiteRecordStore(metadata_schema={"author": "TEXT"}) as store:
        ...     store.set_many([Record(id="1", metadata={"author": "Alice"})])
        ...     store.get("1")
        ...
        Record(id='1', metadata={'author': 'Alice'})

        ```
    """

    _store_cls = TypedSQLiteStore
