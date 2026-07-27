r"""Provide a generic ``BaseStore`` dispatcher that reconstructs a store
from a URI without knowing its concrete class upfront."""

from __future__ import annotations

__all__ = ["register_scheme", "store_from_uri"]

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from persista.store.duckdb import DuckDBStore, TypedDuckDBStore
from persista.store.file import JsonFileStore, PickleFileStore
from persista.store.in_memory import InMemoryStore
from persista.store.lmdb import LmdbStore, PickleLmdbStore
from persista.store.null import NullStore
from persista.store.postgres import PostgresStore
from persista.store.redis import RedisStore
from persista.store.sqlite import PickleSQLiteStore, SQLiteStore, TypedSQLiteStore

if TYPE_CHECKING:
    from persista.store.base import BaseStore

_SCHEMES: dict[str, type[BaseStore]] = {
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


def register_scheme(scheme: str, store_cls: type[BaseStore]) -> None:
    """Register a store class for a URI scheme used by
    :func:`store_from_uri`.

    Args:
        scheme: The URI scheme to associate with ``store_cls``, e.g.
            ``"memory"``. Overwrites any class already registered for
            this scheme.
        store_cls: The ``BaseStore`` subclass to dispatch to for
            ``scheme``. Must implement ``from_uri``.

    Example:
        ```pycon
        >>> from persista.store import InMemoryStore
        >>> from persista.store.registry import register_scheme
        >>> register_scheme("memory", InMemoryStore)

        ```
    """
    _SCHEMES[scheme] = store_cls


def store_from_uri(uri: str, *, read_only: bool = False) -> BaseStore:
    """Reconstruct a :class:`~persista.store.BaseStore` from a URI.

    Dispatches on ``uri``'s scheme to the matching store class's
    :meth:`~persista.store.base.BaseStore.from_uri`. The returned
    store supports both sync and async access. Store classes whose
    scheme is shared with another class (``TypedPostgresStore`` reuses
    ``PostgresStore``'s native ``postgresql://`` scheme,
    ``PickleRedisStore`` reuses ``RedisStore``'s native ``redis://``
    scheme) aren't reachable through this dispatcher -- call
    ``TheClass.from_uri(uri)`` directly for those.

    Args:
        uri: A URI produced by some ``BaseStore`` subclass's
            ``to_uri()``.
        read_only: Forwarded to the matched class's ``from_uri``.

    Returns:
        A new, already-open store instance.

    Raises:
        ValueError: If ``uri``'s scheme is not registered.

    Example:
        ```pycon
        >>> import tempfile
        >>> from persista.store import JsonFileStore, store_from_uri
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     with JsonFileStore(tmpdir) as store:
        ...         store.set("key", {"value": 1})
        ...         uri = store.to_uri()
        ...
        ...     with store_from_uri(uri) as restored:
        ...         print(restored.get("key"))
        ...
        {'value': 1}

        ```
    """
    scheme = urlsplit(uri).scheme
    store_cls = _SCHEMES.get(scheme)
    if store_cls is None:
        msg = f"No store registered for scheme {scheme!r} (from {uri!r})"
        raise ValueError(msg)
    store = store_cls.from_uri(uri, read_only=read_only)
    store.open()
    return store
