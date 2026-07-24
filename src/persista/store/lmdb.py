r"""Provide LMDB-backed implementations of ``BaseStore``."""

from __future__ import annotations

__all__ = ["BaseLmdbStore", "LmdbStore", "PickleLmdbStore"]

import json
import logging
import pickle
from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify

from persista.store._threaded import ThreadedAsyncStoreMixin
from persista.store.base import BaseStore
from persista.store.uri import decode_path_uri, encode_path_uri
from persista.store.validation import (
    normalize_on_conflict,
    resolve_conflicts,
    validate_batch_size,
)
from persista.utils.imports import check_lmdb, is_lmdb_available

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Mapping
    from os import PathLike
    from typing import Self

    from persista.store.types import OnConflict

if is_lmdb_available():  # pragma: no cover
    import lmdb

logger: logging.Logger = logging.getLogger(__name__)

_DEFAULT_MAP_SIZE = 1024**3  # 1 GiB


class BaseLmdbStore(ThreadedAsyncStoreMixin, BaseStore, MultilineDisplayMixin):
    r"""Define a base class for LMDB-backed key-value stores.

    LMDB is an embedded, memory-mapped key-value store backed by a
    single-directory environment on disk, so unlike Redis this store
    needs no separate server process and no explicit tracking of keys:
    the environment's own B+tree already provides ordered iteration,
    membership checks, and a cheap entry count. :meth:`filter` is
    still implemented client-side by scanning every value in the
    store, since LMDB has no query language for matching on the
    content of a value.

    Subclasses only need to implement :meth:`_encode` and
    :meth:`_decode`, which control how a value is serialized to and
    from what is stored in LMDB (see :class:`LmdbStore` for a JSON
    encoding and :class:`PickleLmdbStore` for a pickle encoding).

    Args:
        path: The directory where the LMDB environment is stored.
            Created automatically if it does not already exist.
        map_size: The maximum size in bytes of the memory map, i.e.
            the upper bound on the total size of the environment
            (keys and values combined). Passed to ``lmdb.open``.
        **kwargs: Additional keyword arguments to pass to
            ``lmdb.open``.
    """

    #: URI scheme used by :meth:`to_uri`/:meth:`from_uri`.
    _scheme: str = "lmdb"

    def __init__(
        self, path: str | PathLike[str], map_size: int = _DEFAULT_MAP_SIZE, **kwargs: Any
    ) -> None:
        check_lmdb()
        self._path = str(path)
        self._map_size = map_size
        self._kwargs = kwargs
        self._closed = False
        Path(self._path).mkdir(parents=True, exist_ok=True)
        self._env = lmdb.open(self._path, map_size=map_size, **kwargs)

    @abstractmethod
    def _encode(self, value: dict[str, Any]) -> bytes:
        """Serialize a value to what gets stored in LMDB."""

    @abstractmethod
    def _decode(self, raw: bytes) -> dict[str, Any]:
        """Deserialize a value read back from LMDB."""

    @staticmethod
    def _key_bytes(key: str) -> bytes:
        return key.encode()

    @staticmethod
    def _key_str(key: bytes) -> str:
        return key.decode()

    def close(self) -> None:
        if self._closed:
            return
        logger.info("Closing LMDB environment at %s", self._path)
        self._env.close()
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def get(self, key: str) -> dict[str, Any] | None:
        with self._env.begin() as txn:
            raw = txn.get(self._key_bytes(key))
        return self._decode(raw) if raw is not None else None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        if not keys:
            return []
        with self._env.begin() as txn:
            raws = [txn.get(self._key_bytes(key)) for key in keys]
        return [self._decode(raw) if raw is not None else None for raw in raws]

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

        to_write = resolve_conflicts(items, on_conflict, self.contains_many, self.get)
        self._set_many(to_write)

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        if items:
            with self._env.begin(write=True) as txn:
                for key, value in items.items():
                    txn.put(self._key_bytes(key), self._encode(value))
        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        return [
            value
            for value in self.values()
            if all(value.get(name) == expected for name, expected in field_filters.items())
        ]

    def delete(self, key: str) -> None:
        with self._env.begin(write=True) as txn:
            txn.delete(self._key_bytes(key))

    def delete_many(self, keys: list[str]) -> None:
        if not keys:
            return
        with self._env.begin(write=True) as txn:
            for key in keys:
                txn.delete(self._key_bytes(key))

    def clear(self) -> None:
        with self._env.begin(write=True) as txn:
            db = self._env.open_db()
            txn.drop(db, delete=False)

    def contains(self, key: str) -> bool:
        with self._env.begin() as txn:
            return txn.get(self._key_bytes(key)) is not None

    def contains_many(self, keys: list[str]) -> list[bool]:
        if not keys:
            return []
        with self._env.begin() as txn:
            return [txn.get(self._key_bytes(key)) is not None for key in keys]

    def keys(self) -> Iterator[str]:
        with self._env.begin() as txn, txn.cursor() as cursor:
            yield from (self._key_str(key) for key in cursor.iternext(values=False))

    def iter_batches(
        self, batch_size: int = 32
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        validate_batch_size(batch_size)
        with self._env.begin() as txn, txn.cursor() as cursor:
            all_items = [(self._key_str(key), self._decode(raw)) for key, raw in cursor.iternext()]
        for batch in batchify(all_items, size=batch_size):
            yield dict(batch)

    def count(self) -> int:
        with self._env.begin() as txn:
            return txn.stat()["entries"]

    def to_uri(self) -> str:
        return encode_path_uri(self._scheme, self._path)

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:
        path = decode_path_uri(uri, expected_scheme=cls._scheme)
        return cls(path, readonly=read_only)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"path": self._path, "closed": self._closed}
        if not self._closed:
            kwargs["count"] = self.count()
        return kwargs | self._kwargs

    def __enter__(self) -> Self:
        if self._closed:
            Path(self._path).mkdir(parents=True, exist_ok=True)
            self._env = lmdb.open(self._path, map_size=self._map_size, **self._kwargs)
            self._closed = False
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class LmdbStore(BaseLmdbStore):
    """An LMDB-backed key-value store.

    Persists values to an LMDB environment and supports adding,
    retrieving, filtering, and deleting key-value pairs. Each value
    is stored as a JSON-encoded string, which provides flexibility
    for arbitrary value fields without requiring a fixed schema and
    can be read back by any LMDB client regardless of language. This
    means only JSON-compatible value fields (str, int, float, bool,
    None, list, dict) are supported; use :class:`PickleLmdbStore` if
    you need to persist arbitrary Python objects.

    Args:
        path: The directory where the LMDB environment is stored.
            Created automatically if it does not already exist.
        map_size: The maximum size in bytes of the memory map, i.e.
            the upper bound on the total size of the environment
            (keys and values combined). Passed to ``lmdb.open``.
        **kwargs: Additional keyword arguments to pass to
            ``lmdb.open``.

    Example:
        ```pycon
        >>> from persista.store import LmdbStore
        >>> store = LmdbStore("/tmp/lmdb_store")  # doctest: +SKIP
        >>> store.set_many(
        ...     {
        ...         "1": {"title": "Intro to Python", "author": "Alice", "category": "Programming"},
        ...         "2": {"title": "Advanced Python", "author": "Alice", "category": "Programming"},
        ...         "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
        ...     }
        ... )  # doctest: +SKIP
        >>> len(store.filter(author="Alice"))  # doctest: +SKIP
        2

        ```
    """

    def _encode(self, value: dict[str, Any]) -> bytes:
        return json.dumps(value).encode()

    def _decode(self, raw: bytes) -> dict[str, Any]:
        return json.loads(raw)


class PickleLmdbStore(BaseLmdbStore):
    """An LMDB-backed key-value store that serializes values with
    ``pickle`` instead of JSON.

    Unlike :class:`LmdbStore`, this store can persist arbitrary
    Python objects within a value's fields (tuples, sets, custom
    classes, etc.), not just JSON-compatible types. The tradeoff is
    that values are opaque binary blobs from outside Python (not
    human-readable, not inspectable from non-Python LMDB clients),
    and, since :func:`pickle.loads` can execute arbitrary code, this
    store must never be pointed at an LMDB environment that isn't
    fully trusted.

    Args:
        path: The directory where the LMDB environment is stored.
            Created automatically if it does not already exist.
        map_size: The maximum size in bytes of the memory map, i.e.
            the upper bound on the total size of the environment
            (keys and values combined). Passed to ``lmdb.open``.
        **kwargs: Additional keyword arguments to pass to
            ``lmdb.open``.

    Example:
        ```pycon
        >>> from persista.store import PickleLmdbStore
        >>> store = PickleLmdbStore("/tmp/lmdb_store")  # doctest: +SKIP
        >>> store.set(
        ...     "1", {"title": "Intro to Python", "tags": {"python", "intro"}}
        ... )  # doctest: +SKIP
        >>> store.get("1")  # doctest: +SKIP
        {'title': 'Intro to Python', 'tags': {'python', 'intro'}}

        ```
    """

    _scheme = "lmdb+pickle"

    def _encode(self, value: dict[str, Any]) -> bytes:
        return pickle.dumps(value)

    def _decode(self, raw: bytes) -> dict[str, Any]:
        return pickle.loads(raw)  # noqa: S301
