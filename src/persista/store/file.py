r"""Provide file-based implementations of ``BaseStore``, one file per
value."""

from __future__ import annotations

__all__ = ["BaseFileStore", "JsonFileStore", "PickleFileStore"]

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify
from coola.utils.path import sanitize_path
from iden.io import load_json, load_pickle, save_json, save_pickle

from persista.store._threaded import ThreadedAsyncStoreMixin
from persista.store.base import BaseStore
from persista.store.uri import decode_path_uri, encode_path_uri
from persista.store.validation import (
    normalize_on_conflict,
    resolve_conflicts,
    validate_batch_size,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator, Mapping
    from os import PathLike
    from pathlib import Path
    from typing import Self

    from persista.store.types import OnConflict

logger: logging.Logger = logging.getLogger(__name__)


class BaseFileStore(ThreadedAsyncStoreMixin, BaseStore, MultilineDisplayMixin):
    r"""Define a base class for file-based key-value stores.

    Each value is persisted as its own file in a directory, using
    :mod:`iden.io` to read and write files. Keys are mapped to
    filenames with ``urllib.parse.quote``, so keys containing
    characters like ``/`` or ``..`` cannot escape the store's
    directory. There is no index of keys beyond the directory
    listing itself, so :meth:`keys`, :meth:`filter`, and
    :meth:`iter_batches` all work by scanning the directory.

    Subclasses only need to set :attr:`extension` and implement
    :meth:`_save` and :meth:`_load`, which control how a value is
    serialized to and from a file (see :class:`JsonFileStore` for a
    JSON encoding and :class:`PickleFileStore` for a pickle
    encoding).

    Args:
        path: The directory where value files are stored. Created
            automatically if it does not already exist.
        **kwargs: Additional keyword arguments to pass to the
            underlying ``iden.io`` save function.
    """

    def __init__(self, path: str | PathLike[str], **kwargs: Any) -> None:
        if not self.extension:
            msg = (
                "extension must be a non-empty string: an empty extension would let a "
                "key like '..' escape the store's directory."
            )
            raise ValueError(msg)
        self._path = sanitize_path(path)
        if self._path.exists() and not self._path.is_dir():
            msg = f"path must be a directory: {self._path}"
            raise NotADirectoryError(msg)
        self._kwargs = kwargs
        self._closed = False
        self._path.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        """The directory where value files are stored."""
        return self._path

    @property
    @abstractmethod
    def extension(self) -> str:
        """File extension (including the leading dot) used for value
        files."""

    #: URI scheme used by :meth:`to_uri`/:meth:`from_uri`.
    scheme: str

    @abstractmethod
    def _save(self, path: Path, value: dict[str, Any]) -> None:
        """Serialize ``value`` and write it to ``path``."""

    @abstractmethod
    def _load(self, path: Path) -> dict[str, Any]:
        """Read and deserialize the value stored at ``path``."""

    def _key_to_path(self, key: str) -> Path:
        return self._path / f"{quote(key, safe='')}{self.extension}"

    def _path_to_key(self, path: Path) -> str:
        return unquote(path.name[: -len(self.extension)] if self.extension else path.name)

    def close(self) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def _check_open(self) -> None:
        if self._closed:
            msg = "Cannot operate on a closed store."
            raise ValueError(msg)

    def get(self, key: str) -> dict[str, Any] | None:
        self._check_open()
        file_path = self._key_to_path(key)
        return self._load(file_path) if file_path.is_file() else None

    def get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        return [self.get(key) for key in keys]

    def set(self, key: str, value: dict[str, Any], on_conflict: OnConflict = "overwrite") -> None:
        self.set_many({key: value}, on_conflict=on_conflict)

    def set_many(
        self, items: Mapping[str, dict[str, Any]], on_conflict: OnConflict = "overwrite"
    ) -> None:
        self._check_open()
        if not items:
            return
        on_conflict = normalize_on_conflict(on_conflict)
        if on_conflict == "overwrite":
            self._set_many(items)
            return

        to_write = resolve_conflicts(items, on_conflict, self.contains_many, self.get)
        self._set_many(to_write)

    def _set_many(self, items: Mapping[str, dict[str, Any]]) -> None:
        for key, value in items.items():
            self._save(self._key_to_path(key), value)
        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    def filter(self, **field_filters: Any) -> list[dict[str, Any]]:
        return [
            value
            for value in self.values()
            if all(value.get(name) == expected for name, expected in field_filters.items())
        ]

    def delete(self, key: str) -> None:
        self._check_open()
        self._key_to_path(key).unlink(missing_ok=True)

    def delete_many(self, keys: list[str]) -> None:
        for key in keys:
            self.delete(key)

    def clear(self) -> None:
        self._check_open()
        for file_path in self._iter_files():
            file_path.unlink(missing_ok=True)

    def contains(self, key: str) -> bool:
        self._check_open()
        return self._key_to_path(key).is_file()

    def contains_many(self, keys: list[str]) -> list[bool]:
        return [self.contains(key) for key in keys]

    def _iter_files(self) -> Iterator[Path]:
        return (
            file_path
            for file_path in self._path.iterdir()
            if file_path.is_file() and file_path.suffix == self.extension
        )

    def keys(self) -> Iterator[str]:
        self._check_open()
        yield from (self._path_to_key(file_path) for file_path in self._iter_files())

    def iter_batches(
        self, batch_size: int = 32
    ) -> Generator[dict[str, dict[str, Any]], None, None]:
        validate_batch_size(batch_size)
        self._check_open()
        items = (
            (self._path_to_key(file_path), self._load(file_path))
            for file_path in self._iter_files()
        )
        for batch in batchify(items, size=batch_size):
            yield dict(batch)

    def count(self) -> int:
        self._check_open()
        return sum(1 for _ in self._iter_files())

    def to_uri(self) -> str:
        return encode_path_uri(self.scheme, str(self._path))

    @classmethod
    def from_uri(cls, uri: str, *, read_only: bool = False) -> Self:  # noqa: ARG003
        return cls(decode_path_uri(uri, expected_scheme=cls.scheme))

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"path": str(self._path), "closed": self._closed}
        if not self._closed:
            kwargs["count"] = self.count()
        return kwargs | self._kwargs

    def __enter__(self) -> Self:
        self._closed = False
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    async def __aenter__(self) -> Self:
        self._closed = False
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()


class JsonFileStore(BaseFileStore):
    """A file-based key-value store that serializes each value to its
    own JSON file.

    Values are stored in human-readable form and can be read by any
    JSON-compatible tool, but only JSON-compatible value fields (str,
    int, float, bool, None, list, dict) are supported; use
    :class:`PickleFileStore` if you need to persist arbitrary Python
    objects.

    Args:
        path: The directory where value files are stored. Created
            automatically if it does not already exist.
        **kwargs: Additional keyword arguments to pass to
            ``iden.io.save_json``.

    Example:
        ```pycon
        >>> from persista.store import JsonFileStore
        >>> store = JsonFileStore("/tmp/file_store")  # doctest: +SKIP
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

    scheme = "file+json"

    @property
    def extension(self) -> str:
        return ".json"

    def _save(self, path: Path, value: dict[str, Any]) -> None:
        save_json(value, path, exist_ok=True)

    def _load(self, path: Path) -> dict[str, Any]:
        return load_json(path)


class PickleFileStore(BaseFileStore):
    """A file-based key-value store that serializes each value to its
    own pickle file.

    Unlike :class:`JsonFileStore`, this store can persist arbitrary
    Python objects within a value's fields (tuples, sets, custom
    classes, etc.), not just JSON-compatible types. The tradeoff is
    that value files are opaque binary blobs (not human-readable),
    and, since :func:`pickle.loads` can execute arbitrary code, this
    store must never be pointed at a directory that isn't fully
    trusted.

    Args:
        path: The directory where value files are stored. Created
            automatically if it does not already exist.
        **kwargs: Additional keyword arguments to pass to
            ``iden.io.save_pickle``.

    Example:
        ```pycon
        >>> from persista.store import PickleFileStore
        >>> store = PickleFileStore("/tmp/file_store")  # doctest: +SKIP
        >>> store.set(
        ...     "1", {"title": "Intro to Python", "tags": {"python", "intro"}}
        ... )  # doctest: +SKIP
        >>> store.get("1")  # doctest: +SKIP
        {'title': 'Intro to Python', 'tags': {'python', 'intro'}}

        ```
    """

    scheme = "file+pickle"

    @property
    def extension(self) -> str:
        return ".pkl"

    def _save(self, path: Path, value: dict[str, Any]) -> None:
        save_pickle(value, path, exist_ok=True, **self._kwargs)

    def _load(self, path: Path) -> dict[str, Any]:
        return load_pickle(path)
