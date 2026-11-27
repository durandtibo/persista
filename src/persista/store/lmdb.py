r"""Provide an LMDB-backed implementation of ``BaseStore``."""

from __future__ import annotations

__all__ = ["LmdbStore"]

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify
from coola.utils.path import sanitize_path

from persista.store.base import BaseStore
from persista.store.uri import codec_uri_scheme, decode_codec_uri, encode_path_uri
from persista.utils.imports import check_lmdb, is_lmdb_available

if TYPE_CHECKING:
    from collections.abc import Iterator
    from os import PathLike
    from pathlib import Path
    from typing import Self

    from persista.store.codec import Codec
    from persista.store.types import Payload, Plan

if TYPE_CHECKING or is_lmdb_available():  # pragma: no cover
    import lmdb

logger: logging.Logger = logging.getLogger(__name__)

_DEFAULT_MAP_SIZE = 1024**3  # 1 GiB

# The URI scheme for each codec name.
_SCHEMES: dict[str, str] = {"json": "lmdb", "pickle": "lmdb+pickle"}

# The longest key, in bytes, that LMDB accepts as it is usually built.
_MAX_KEY_SIZE = 511


class LmdbStore(BaseStore, MultilineDisplayMixin):
    r"""An LMDB-backed key-value store.

    LMDB is an embedded, memory-mapped key-value database kept in a
    directory, so unlike Redis this store needs no server process. A
    value is kept as the payload of the codec: with the default
    :class:`~persista.store.JsonCodec`, as UTF-8 JSON that any LMDB
    client can read; with a :class:`~persista.store.PickleCodec`, as
    opaque bytes that keep Python types. :meth:`filter` reads and decodes
    every value, since LMDB cannot query inside the values.

    A key has 1 to 511 bytes once encoded in UTF-8, and must be valid
    Unicode (no lone surrogate). Every method that takes a key raises
    ``ValueError`` for another key, such as the empty string, before
    anything is read or written.

    A write runs in one LMDB write transaction, so a write of several
    keys is atomic, and a write with ``on_conflict`` set to ``"raise"``,
    ``"skip"`` or ``"merge"`` is atomic against the other writers of the
    environment, including other processes. A write waits, without time
    limit, for the write transaction of another process.

    An environment does not record its codec: reading it with the other
    codec raises a decoding error, so open it with the codec that wrote
    it.

    LMDB cannot open the same path twice in one process: opening a second
    store of a path raises ``lmdb.Error`` while the first one is open.
    Share one store instead.

    The async methods run in a worker thread of the store.

    Args:
        path: The directory of the LMDB environment. Opening the store
            creates it, with its parents, if it does not exist (unless
            ``read_only``).
        codec: The codec of the values, a
            :class:`~persista.store.JsonCodec` (default) or a
            :class:`~persista.store.PickleCodec`. Decoding a pickle
            payload can execute arbitrary code: only use it with a
            trusted environment.
        map_size: The maximum size in bytes of the memory map, i.e. the
            upper bound on the total size of the environment (keys and
            values combined). Passed to ``lmdb.open``.
        read_only: If ``True``, open an existing environment read-only.
            No file or directory is created: opening raises
            ``FileNotFoundError`` if the data file or the lock file is
            missing. An environment without a lock file (e.g. a copy) can
            be opened with ``lock=False``, if no process writes it.
        **kwargs: Additional keyword arguments to pass to
            ``lmdb.open``.

    Raises:
        RuntimeError: If the ``lmdb`` package is not installed.
        ValueError: If the codec is not supported, or if ``readonly`` or
            ``create`` is given (use ``read_only``).

    Example:
        ```pycon
        >>> import tempfile
        >>> from persista.store import LmdbStore
        >>> with tempfile.TemporaryDirectory() as tmpdir, LmdbStore(tmpdir) as store:
        ...     store.set_many(
        ...         {
        ...             "1": {
        ...                 "title": "Intro to Python",
        ...                 "author": "Alice",
        ...                 "category": "Programming",
        ...             },
        ...             "2": {
        ...                 "title": "Advanced Python",
        ...                 "author": "Alice",
        ...                 "category": "Programming",
        ...             },
        ...             "3": {"title": "History of Rome", "author": "Bob", "category": "History"},
        ...         }
        ...     )
        ...     len(store.filter(author="Alice"))
        ...
        2

        ```

        A pickle codec keeps Python types, and a read-only store reads an
        existing environment:

        ```pycon
        >>> import tempfile
        >>> from persista.store import LmdbStore, PickleCodec
        >>> with tempfile.TemporaryDirectory() as tmpdir:
        ...     with LmdbStore(tmpdir, codec=PickleCodec()) as store:
        ...         store.set("1", {"tags": {"python"}})
        ...     with LmdbStore(tmpdir, codec=PickleCodec(), read_only=True) as store:
        ...         store.get("1")
        ...
        {'tags': {'python'}}

        ```
    """

    def __init__(
        self,
        path: str | PathLike[str],
        *,
        codec: Codec | None = None,
        map_size: int = _DEFAULT_MAP_SIZE,
        read_only: bool = False,
        **kwargs: Any,
    ) -> None:
        check_lmdb()
        managed = sorted({"create", "readonly"} & kwargs.keys())
        if managed:
            msg = f"Use read_only: LmdbStore does not accept {managed}"
            raise ValueError(msg)
        super().__init__(codec=codec)
        self._scheme = codec_uri_scheme(self._codec, _SCHEMES)
        self._path = sanitize_path(path)
        self._map_size = map_size
        self._read_only = read_only
        self._kwargs = kwargs
        self._env: lmdb.Environment | None = None

    @property
    def path(self) -> Path:
        r"""The path of the LMDB environment."""
        return self._path

    @property
    def environment(self) -> lmdb.Environment:
        r"""Return the underlying LMDB environment.

        This is not part of the regular store API. It is meant for
        debugging or running specific commands. The store must be open.

        Raises:
            RuntimeError: If the store is not open.
        """
        if self._env is None:
            msg = f"{type(self).__name__} is not open."
            raise RuntimeError(msg)
        return self._env

    def to_uri(self) -> str:
        return encode_path_uri(self._scheme, str(self._path))

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False, **kwargs: Any) -> Self:
        r"""Reconstruct a store from a URI produced by :meth:`to_uri`.

        The scheme of the URI gives the codec. The other arguments of the
        constructor, such as ``map_size``, are not part of the URI: pass
        them again.

        Args:
            uri: A URI produced by :meth:`to_uri`.
            read_only: Whether to open the environment read-only.
            **kwargs: The other keyword arguments of the constructor. A
                ``codec`` must have the name of the codec of the scheme.

        Returns:
            A new store instance, not opened.

        Raises:
            ValueError: If the scheme of ``uri`` is not one of this class,
                or if ``codec`` does not match it.
        """
        path, codec = decode_codec_uri(uri, schemes=_SCHEMES, codec=kwargs.pop("codec", None))
        return cls(path, codec=codec, read_only=read_only, **kwargs)

    ######################
    #     Primitives     #
    ######################

    def _open(self) -> None:
        kwargs: dict[str, Any] = dict(self._kwargs)
        if self._read_only:
            _check_environment_files(
                self._path, subdir=kwargs.get("subdir", True), lock=kwargs.get("lock", True)
            )
            kwargs |= {"readonly": True, "create": False}
        elif kwargs.get("subdir", True):
            self._path.mkdir(parents=True, exist_ok=True)
        else:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._env = lmdb.open(str(self._path), map_size=self._map_size, **kwargs)

    def _close(self) -> None:
        if self._env is None:
            return
        logger.info("Closing LMDB environment at %s", self._path)
        self._env.close()
        self._env = None

    def _get_many(self, keys: list[str]) -> dict[str, Payload]:
        # The shortest path for the most frequent read.
        if len(keys) == 1:
            key = keys[0]
            raw_key = _encode_key(key)
            with self.environment.begin() as txn:
                payload = txn.get(raw_key)
            return {} if payload is None else {key: payload}
        # Every key is checked before the first one is read.
        raw_keys = _encode_keys(keys)
        with self.environment.begin() as txn:
            return {
                key: payload
                for key, payload in zip(keys, map(txn.get, raw_keys), strict=True)
                if payload is not None
            }

    def _put_many(self, items: dict[str, Payload]) -> None:
        # Encoded before the transaction, which blocks the other writers.
        rows = [(_encode_key(key), _encode_payload(payload)) for key, payload in items.items()]
        with self.environment.begin(write=True) as txn:
            for raw_key, raw in rows:
                txn.put(raw_key, raw)
        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    def _update(self, keys: list[str], plan: Plan) -> None:
        encoded = {key: _encode_key(key) for key in keys}
        # LMDB has one write transaction at a time, in every process, so
        # nothing can change the keys between the read and the write.
        with self.environment.begin(write=True) as txn:
            existing: dict[str, Payload] = {}
            for key, raw_key in encoded.items():
                if (payload := txn.get(raw_key)) is not None:
                    existing[key] = payload
            for key, payload in plan(existing).items():
                txn.put(encoded[key], _encode_payload(payload))

    def _delete_many(self, keys: list[str]) -> None:
        raw_keys = _encode_keys(keys)
        with self.environment.begin(write=True) as txn:
            for raw_key in raw_keys:
                txn.delete(raw_key)

    def _clear(self) -> None:
        env = self.environment
        database = env.open_db()
        with env.begin(write=True) as txn:
            txn.drop(database, delete=False)

    def _count(self) -> int:
        with self.environment.begin() as txn:
            return txn.stat()["entries"]

    def _contains_many(self, keys: list[str]) -> set[str]:
        encoded = [(key, _encode_key(key)) for key in keys]
        # A cursor finds a key without copying its value.
        with self.environment.begin() as txn, txn.cursor() as cursor:
            return {key for key, raw_key in encoded if cursor.set_key(raw_key)}

    def _iter_batches(self, batch_size: int) -> Iterator[dict[str, Payload]]:
        # No transaction is kept open between two batches: a transaction
        # belongs to its thread, and an old read transaction prevents LMDB
        # from reusing the space of the deleted values.
        for raw_keys in batchify(self._snapshot_keys(), size=batch_size):
            with self.environment.begin() as txn:
                # A key deleted since the snapshot is skipped.
                batch: dict[str, Payload] = {
                    raw_key.decode(): payload
                    for raw_key in raw_keys
                    if (payload := txn.get(raw_key)) is not None
                }
            if batch:
                yield batch

    def _iter_key_batches(self, batch_size: int) -> Iterator[list[str]]:
        # As _iter_batches, without reading the values.
        for raw_keys in batchify(self._snapshot_keys(), size=batch_size):
            with self.environment.begin() as txn, txn.cursor() as cursor:
                batch = [raw_key.decode() for raw_key in raw_keys if cursor.set_key(raw_key)]
            if batch:
                yield batch

    ###########################
    #     Template helpers    #
    ###########################

    def _snapshot_keys(self) -> list[bytes]:
        r"""Read all the keys of the environment.

        Returns:
            The keys as LMDB keeps them, in the order of their bytes.
        """
        with self.environment.begin() as txn, txn.cursor() as cursor:
            return list(cursor.iternext(values=False))

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"path": str(self._path), "closed": self.closed}
        if self._codec.name != "json":
            kwargs["codec"] = self._codec
        if self._read_only:
            kwargs["read_only"] = True
        if not self.closed:
            kwargs["count"] = f"{self.count():,}"
        return kwargs | self._kwargs


def _encode_key(key: str) -> bytes:
    r"""Encode a key as LMDB keeps it.

    Args:
        key: The key.

    Returns:
        The key in UTF-8.

    Raises:
        ValueError: If the key contains a lone surrogate, or if it does not
            have 1 to 511 bytes.
    """
    try:
        encoded = key.encode()
    except UnicodeEncodeError as exc:
        msg = f"A key of LmdbStore must be valid Unicode, but it has a lone surrogate: {key!r}"
        raise ValueError(msg) from exc
    if not 0 < len(encoded) <= _MAX_KEY_SIZE:
        msg = (
            f"A key of LmdbStore must have 1 to {_MAX_KEY_SIZE} UTF-8 bytes, "
            f"not {len(encoded)}: {key[:50]!r}"
        )
        raise ValueError(msg)
    return encoded


def _encode_keys(keys: list[str]) -> list[bytes]:
    r"""Encode several keys as LMDB keeps them.

    Args:
        keys: The keys.

    Returns:
        The keys in UTF-8, in the same order.

    Raises:
        ValueError: If a key contains a lone surrogate, or if it does not
            have 1 to 511 bytes.
    """
    # Fast path: encode and check all the keys at once.
    with contextlib.suppress(UnicodeEncodeError):
        encoded = list(map(str.encode, keys))
        if all(encoded) and max(map(len, encoded), default=0) <= _MAX_KEY_SIZE:
            return encoded
    # A key is invalid: encode them one by one to report it.
    return [_encode_key(key) for key in keys]


def _encode_payload(payload: Payload) -> bytes:
    r"""Return the bytes of a payload.

    Args:
        payload: A payload of a codec.

    Returns:
        The payload. A ``str`` is encoded in UTF-8.
    """
    return payload.encode() if isinstance(payload, str) else payload


def _check_environment_files(path: Path, *, subdir: bool, lock: bool) -> None:
    r"""Check that opening an LMDB environment would create no file.

    LMDB creates a missing lock file, even for a read-only environment.

    Args:
        path: The path of the environment.
        subdir: Whether ``path`` is the directory of the environment. If
            not, it is its data file.
        lock: Whether the environment uses its lock file.

    Raises:
        FileNotFoundError: If the data file is missing, or if the lock
            file is used and missing.
    """
    if subdir:
        data_file, lock_file = path / "data.mdb", path / "lock.mdb"
    else:
        data_file, lock_file = path, path.with_name(f"{path.name}-lock")
    if not data_file.is_file():
        msg = f"No LMDB environment to read: {str(data_file)!r} does not exist"
        raise FileNotFoundError(msg)
    if lock and not lock_file.is_file():
        msg = (
            f"The lock file {str(lock_file)!r} does not exist, and a read-only store does not "
            "create it. Pass lock=False if no process writes the environment."
        )
        raise FileNotFoundError(msg)
