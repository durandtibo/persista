r"""Provide generic ``BaseStore``/``AsyncBaseStore`` dispatchers that
reconstruct a store from a URI without knowing its concrete class
upfront."""

from __future__ import annotations

__all__ = [
    "async_store_from_uri",
    "register_async_scheme",
    "register_scheme",
    "store_from_uri",
]

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from persista.store.async_postgres import AsyncPostgresStore
from persista.store.async_redis import AsyncRedisStore
from persista.store.duckdb import DuckDBStore, TypedDuckDBStore
from persista.store.file import JsonFileStore, PickleFileStore
from persista.store.in_memory import InMemoryStore
from persista.store.lmdb import LmdbStore, PickleLmdbStore
from persista.store.null import NullStore
from persista.store.postgres import PostgresStore
from persista.store.redis import RedisStore
from persista.store.sqlite import PickleSQLiteStore, SQLiteStore, TypedSQLiteStore

if TYPE_CHECKING:
    from persista.store.base import AsyncBaseStore, BaseStore

_SYNC_SCHEMES: dict[str, type[BaseStore]] = {
    "memory": InMemoryStore,
    "null": NullStore,
    "file+json": JsonFileStore,
    "file+pickle": PickleFileStore,
    "sqlite": SQLiteStore,
    "sqlite+pickle": PickleSQLiteStore,
    "sqlite+typed": TypedSQLiteStore,
    "duckdb": DuckDBStore,
    "duckdb+typed": TypedDuckDBStore,
    "lmdb": LmdbStore,
    "lmdb+pickle": PickleLmdbStore,
    "postgresql": PostgresStore,
    "postgres": PostgresStore,
    "redis": RedisStore,
    "rediss": RedisStore,
}

_ASYNC_SCHEMES: dict[str, type[AsyncBaseStore]] = {
    "postgresql": AsyncPostgresStore,
    "postgres": AsyncPostgresStore,
    "redis": AsyncRedisStore,
    "rediss": AsyncRedisStore,
}


def register_scheme(scheme: str, store_cls: type[BaseStore]) -> None:
    """Register a store class for a URI scheme used by
    :func:`store_from_uri`.

    Args:
        scheme: The URI scheme to associate with ``store_cls``, e.g.
            ``"memory"``. Overwrites any class already registered for
            this scheme.
        store_cls: The ``BaseStore`` subclass to dispatch to for
            ``scheme``. Must implement ``from_uri``.
    """
    _SYNC_SCHEMES[scheme] = store_cls


def register_async_scheme(scheme: str, store_cls: type[AsyncBaseStore]) -> None:
    """Register a store class for a URI scheme used by
    :func:`async_store_from_uri`.

    Args:
        scheme: The URI scheme to associate with ``store_cls``, e.g.
            ``"memory"``. Overwrites any class already registered for
            this scheme.
        store_cls: The ``AsyncBaseStore`` subclass to dispatch to for
            ``scheme``. Must implement ``from_uri``.
    """
    _ASYNC_SCHEMES[scheme] = store_cls


def store_from_uri(uri: str, *, read_only: bool = False) -> BaseStore:
    """Reconstruct a :class:`~persista.store.base.BaseStore` from a URI.

    Dispatches on ``uri``'s scheme to the matching store class's
    :meth:`~persista.store.base.BaseStore.from_uri`. Store classes
    whose scheme is shared with another class (``TypedPostgresStore``
    reuses ``PostgresStore``'s native ``postgresql://`` scheme,
    ``PickleRedisStore`` reuses ``RedisStore``'s native ``redis://``
    scheme) aren't reachable through this dispatcher -- call
    ``TheClass.from_uri(uri)`` directly for those.

    Args:
        uri: A URI produced by some ``BaseStore`` subclass's
            ``to_uri()``.
        read_only: Forwarded to the matched class's ``from_uri``.

    Returns:
        A new store instance.

    Raises:
        ValueError: If ``uri``'s scheme is not registered.
    """
    scheme = urlsplit(uri).scheme
    store_cls = _SYNC_SCHEMES.get(scheme)
    if store_cls is None:
        msg = f"No store registered for scheme {scheme!r} (from {uri!r})"
        raise ValueError(msg)
    return store_cls.from_uri(uri, read_only=read_only)


def async_store_from_uri(uri: str, *, read_only: bool = False) -> AsyncBaseStore:
    """Reconstruct an :class:`~persista.store.base.AsyncBaseStore` from
    a URI.

    Mirrors :func:`store_from_uri`, dispatching to the async store
    classes instead.

    Args:
        uri: A URI produced by some ``AsyncBaseStore`` subclass's
            ``to_uri()``.
        read_only: Forwarded to the matched class's ``from_uri``.

    Returns:
        A new store instance.

    Raises:
        ValueError: If ``uri``'s scheme is not registered.
    """
    scheme = urlsplit(uri).scheme
    store_cls = _ASYNC_SCHEMES.get(scheme)
    if store_cls is None:
        msg = f"No async store registered for scheme {scheme!r} (from {uri!r})"
        raise ValueError(msg)
    return store_cls.from_uri(uri, read_only=read_only)
