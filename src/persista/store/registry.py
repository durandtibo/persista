r"""Provide a generic ``BaseStore`` dispatcher that reconstructs a store
from a URI without knowing its concrete class upfront."""

from __future__ import annotations

__all__ = ["register_scheme", "store_from_uri"]

from typing import TYPE_CHECKING

from persista.store.duckdb import DuckDBStore
from persista.store.file import FileStore
from persista.store.in_memory import InMemoryStore
from persista.store.lmdb import LmdbStore
from persista.store.null import NullStore
from persista.store.postgres import PostgresStore
from persista.store.redis import RedisStore
from persista.store.sqlite import SQLiteStore
from persista.store.uri import split_uri

if TYPE_CHECKING:
    from persista.store.base import BaseStore

_SCHEMES: dict[str, type[BaseStore]] = {
    "memory": InMemoryStore,
    "null": NullStore,
    "file+json": FileStore,
    "file+pickle": FileStore,
    "sqlite": SQLiteStore,
    "sqlite+pickle": SQLiteStore,
    "duckdb": DuckDBStore,
    "duckdb+pickle": DuckDBStore,
    "lmdb": LmdbStore,
    "lmdb+pickle": LmdbStore,
    "postgresql": PostgresStore,
    "postgres": PostgresStore,
    "redis": RedisStore,
    "rediss": RedisStore,
    "unix": RedisStore,
}


def register_scheme(scheme: str, store_cls: type[BaseStore]) -> None:
    """Register a store class for a URI scheme used by
    :func:`store_from_uri`.

    Args:
        scheme: The URI scheme to associate with ``store_cls``, e.g.
            ``"memory"``. Its case is ignored, as in a URI. Overwrites
            any class already registered for this scheme.
        store_cls: The ``BaseStore`` subclass to dispatch to for
            ``scheme``. Must implement ``from_uri``.

    Example:
        ```pycon
        >>> from persista.store import InMemoryStore
        >>> from persista.store.registry import register_scheme
        >>> register_scheme("memory", InMemoryStore)

        ```
    """
    # urlsplit lowercases the scheme of a URI.
    _SCHEMES[scheme.lower()] = store_cls


def store_from_uri(uri: str, *, read_only: bool = False) -> BaseStore:
    """Reconstruct a :class:`~persista.store.BaseStore` from a URI.

    Dispatches on ``uri``'s scheme to the matching store class's
    :meth:`~persista.store.base.BaseStore.from_uri`. The returned
    store supports both sync and async access.

    The store has the default options of its class, since a URI says
    where the data is, not how the store was configured: a ``redis://``
    URI gives a :class:`~persista.store.RedisStore` with the default
    codec and namespace, and a ``postgresql://`` URI a
    :class:`~persista.store.PostgresStore` with the default codec and
    table. For other options, call the ``from_uri`` method of the class,
    such as ``RedisStore.from_uri(uri, codec=..., namespace=...)``. See
    :meth:`~persista.store.base.BaseStore.from_uri` for the other
    limitations of the URIs.

    The built-in schemes are ``memory``, ``null``, ``file+json``,
    ``file+pickle``, ``sqlite``, ``sqlite+pickle``, ``duckdb``,
    ``duckdb+pickle``, ``lmdb``, ``lmdb+pickle``, ``postgresql``,
    ``postgres``, ``redis``, ``rediss`` and ``unix`` (a Redis server on
    a Unix socket).

    Args:
        uri: A URI produced by some ``BaseStore`` subclass's
            ``to_uri()``.
        read_only: Forwarded to the matched class's ``from_uri``.
            Honored by the SQLite, DuckDB and LMDB stores, and ignored
            by the others.

    Returns:
        A new, already-open store instance.

    Raises:
        ValueError: If ``uri`` cannot be parsed or its scheme is not
            registered, or if the matched class rejects ``uri`` or
            ``read_only``. The messages of persista do not quote the URI,
            which can contain a password.

    An error of ``open``, for example because a server cannot be
    reached, is raised as it is.

    Example:
        ```pycon
        >>> import tempfile
        >>> from persista.store import FileStore, store_from_uri
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     with FileStore(tmpdir) as store:
        ...         store.set("key", {"value": 1})
        ...         uri = store.to_uri()
        ...     with store_from_uri(uri) as restored:
        ...         print(restored.get("key"))
        ...
        {'value': 1}

        ```
    """
    scheme = split_uri(uri).scheme
    store_cls = _SCHEMES.get(scheme)
    if store_cls is None:
        # The URI is not quoted: it can contain a password.
        msg = f"No store registered for scheme {scheme!r}"
        raise ValueError(msg)
    store = store_cls.from_uri(uri, read_only=read_only)
    store.open()
    return store
