r"""Provide a file-based implementation of ``BaseStore``, one file per
value.

The name of a file is the key, percent-encoded, followed by the
extension of the codec. The upper-case letters of a key are also
percent-encoded, so two keys never differ only by the case of their file
names, which some file systems ignore.
"""

from __future__ import annotations

__all__ = ["FileStore"]

import contextlib
import logging
import os
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote
from uuid import uuid4

from coola.display import MultilineDisplayMixin
from coola.utils.batching import batchify
from coola.utils.path import sanitize_path

from persista.store.base import BaseStore
from persista.store.uri import codec_uri_scheme, decode_codec_uri, encode_path_uri

if TYPE_CHECKING:
    from collections.abc import Iterator
    from os import PathLike
    from pathlib import Path
    from typing import Self

    from persista.store.codec import Codec
    from persista.store.types import Payload, Plan

logger: logging.Logger = logging.getLogger(__name__)

# The URI scheme and the file extension for each codec name.
_SCHEMES: dict[str, str] = {"json": "file+json", "pickle": "file+pickle"}
_EXTENSIONS: dict[str, str] = {"json": ".json", "pickle": ".pkl"}

# The longest file name, in bytes, that the common file systems accept.
# The names are ASCII, so it is also a number of characters.
_MAX_FILE_NAME_LENGTH = 255

# An escape of a quoted key (group 1 empty), or an upper-case letter.
_ESCAPE_OR_UPPER = re.compile(r"%..|([A-Z])")

# A name with an upper-case letter outside the escapes.
_HAS_UPPER = re.compile(r"(?:%..|[^%A-Z])*[A-Z]")


class FileStore(BaseStore, MultilineDisplayMixin):
    r"""A key-value store that keeps each value in its own file of a
    directory.

    With the default :class:`~persista.store.JsonCodec`, a file holds
    JSON and has the extension ``.json``, so any JSON tool can read it.
    With a :class:`~persista.store.PickleCodec`, it holds opaque bytes,
    which keep Python types, and has the extension ``.pkl``. The stores
    of the two codecs ignore the files of each other.

    The name of a file is the key encoded with
    :func:`urllib.parse.quote`, so keys containing characters like ``/``
    or ``..`` cannot escape the directory. The upper-case ASCII letters
    are encoded too (``User:1`` is kept in ``%55ser%3A1.json``), so two
    keys never differ only by the case of their file names.

    The name of a file, with its extension, has at most 255 characters,
    and every method that takes a key raises ``ValueError`` for a key
    whose name is longer, before anything is read or written. With JSON,
    this allows 250 characters among ``a-z``, ``0-9`` and ``_.-~``, but
    only 83 upper-case letters or 41 ``é``, since an encoded byte takes 3
    characters. A key must also be valid Unicode (no lone surrogate). A
    file system with a lower limit raises ``OSError``.

    Only the files whose name is the encoding of a key belong to the
    store: the other files of the directory are never listed, counted or
    deleted. This includes the files that earlier versions wrote for keys
    with upper-case letters. On a file system that ignores case, such a
    file (e.g. ``User.json``) occupies the name of another key
    (``user``): the store reads that key as missing, and raises
    ``ValueError`` if it is written.

    Each file is written to a temporary file first, and then renamed, so
    a reader never sees a partial value. A write of several keys is atomic
    per file only. A write with ``on_conflict`` set to ``"raise"``,
    ``"skip"`` or ``"merge"`` is atomic against the other calls on the
    same instance only: not against another instance or process that
    writes the same directory.

    The async methods run in a worker thread of the store.

    Args:
        path: The directory where the files are kept. Opening the store
            creates it, with its parents, if it does not exist.
        codec: The codec of the values, a
            :class:`~persista.store.JsonCodec` (default) or a
            :class:`~persista.store.PickleCodec`. Decoding a pickle
            payload can execute arbitrary code: only use it with a
            trusted directory.

    Raises:
        NotADirectoryError: If ``path`` exists and is not a directory.
        ValueError: If the codec is not supported.

    Example:
        ```pycon
        >>> import tempfile
        >>> from persista.store import FileStore
        >>> with tempfile.TemporaryDirectory() as tmpdir, FileStore(tmpdir) as store:
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

        A pickle codec keeps Python types:

        ```pycon
        >>> import tempfile
        >>> from persista.store import FileStore, PickleCodec
        >>> with (
        ...     tempfile.TemporaryDirectory() as tmpdir,
        ...     FileStore(tmpdir, codec=PickleCodec()) as store,
        ... ):
        ...     store.set("1", {"tags": ("python", "intro")})
        ...     store.get("1")
        ...
        {'tags': ('python', 'intro')}

        ```
    """

    def __init__(self, path: str | PathLike[str], *, codec: Codec | None = None) -> None:
        super().__init__(codec=codec)
        self._scheme = codec_uri_scheme(self._codec, _SCHEMES)
        self._extension = _EXTENSIONS[self._codec.name]
        self._path = sanitize_path(path)
        if self._path.exists() and not self._path.is_dir():
            msg = f"path must be a directory: {self._path}"
            raise NotADirectoryError(msg)
        # The names that a file of another store occupied when the store
        # was opened.
        self._shadowed: set[str] = set()

    @property
    def path(self) -> Path:
        r"""The directory where the files are kept."""
        return self._path

    def to_uri(self) -> str:
        return encode_path_uri(self._scheme, str(self._path))

    @classmethod
    def from_uri(
        cls,
        uri: str,
        *,
        read_only: bool = False,  # noqa: ARG003
        **kwargs: Any,
    ) -> Self:
        r"""Reconstruct a store from a URI produced by :meth:`to_uri`.

        The scheme of the URI gives the codec. The path is absolute, so
        the URI is only valid on a machine with the same files.

        Args:
            uri: A URI produced by :meth:`to_uri`.
            read_only: Ignored: the store has no read-only mode.
            **kwargs: The keyword arguments of the constructor. A
                ``codec`` must have the name of the codec of the scheme.

        Returns:
            A new store instance, not opened.

        Raises:
            ValueError: If the scheme of ``uri`` is not one of this class,
                or if ``codec`` does not match it.
        """
        path, codec = decode_codec_uri(uri, schemes=_SCHEMES, codec=kwargs.pop("codec", None))
        return cls(path, codec=codec, **kwargs)

    ######################
    #     Primitives     #
    ######################

    def _open(self) -> None:
        self._path.mkdir(parents=True, exist_ok=True)
        self._shadowed = _find_shadowed_names(self._path, self._extension)

    def _close(self) -> None:
        self._shadowed = set()

    def _get_many(self, keys: list[str]) -> dict[str, Payload]:
        payloads: dict[str, Payload] = {}
        # Every name is built, and so checked, before a file is read.
        for key, name in self._file_names(keys).items():
            if self._is_shadowed(name):
                continue
            file_path = os.path.join(self._path, name)  # noqa: PTH118
            try:
                with open(file_path, "rb") as file:  # noqa: PTH123
                    payloads[key] = file.read()
            except OSError:
                # A missing file, or a directory, is a missing key.
                if os.path.isfile(file_path):  # noqa: PTH113
                    raise
        return payloads

    def _put_many(self, items: dict[str, Payload]) -> None:
        names = self._file_names(list(items))
        self._check_not_shadowed(names)
        for key, payload in items.items():
            _write_file(self._path / names[key], payload)
        logger.debug("Added/replaced %d key-value pair(s)", len(items))

    def _update(self, keys: list[str], plan: Plan) -> None:
        # Atomic against this instance only, because the base holds its
        # lock. The names are checked first, so that a key that cannot be
        # written is reported before a conflict.
        self._check_not_shadowed(self._file_names(keys))
        if items := plan(self._get_many(keys)):
            self._put_many(items)

    def _delete_many(self, keys: list[str]) -> None:
        for name in self._file_names(keys).values():
            if not self._is_shadowed(name):
                (self._path / name).unlink(missing_ok=True)

    def _clear(self) -> None:
        for key in self._list_keys():
            (self._path / _encode_file_name(key, self._extension)).unlink(missing_ok=True)

    def _count(self) -> int:
        return len(self._list_keys())

    def _contains_many(self, keys: list[str]) -> set[str]:
        return {key for key, name in self._file_names(keys).items() if self._is_file_of_key(name)}

    def _iter_batches(self, batch_size: int) -> Iterator[dict[str, Payload]]:
        # A snapshot of the file names: the directory can change between
        # two batches.
        for keys in batchify(self._list_keys(), size=batch_size):
            # A key deleted since the snapshot is skipped.
            if batch := self._get_many(list(keys)):
                yield batch

    def _iter_key_batches(self, batch_size: int) -> Iterator[list[str]]:
        # As _iter_batches, without reading the files.
        for keys in batchify(self._list_keys(), size=batch_size):
            found = self._contains_many(list(keys))
            if batch := [key for key in keys if key in found]:
                yield batch

    ###########################
    #     Template helpers    #
    ###########################

    def _file_names(self, keys: list[str]) -> dict[str, str]:
        r"""Return the file name of each key.

        Args:
            keys: The keys. It can contain duplicates.

        Returns:
            The file name of each key, in the order of the keys.

        Raises:
            ValueError: If a key cannot be a file name.
        """
        return {key: _encode_file_name(key, self._extension) for key in keys}

    def _list_keys(self) -> list[str]:
        r"""List the keys of the files of the directory.

        Returns:
            The keys, in the order of the directory.
        """
        with os.scandir(self._path) as entries:
            return [
                key
                for entry in entries
                if (key := _decode_file_name(entry.name, self._extension)) is not None
                and entry.is_file()
            ]

    def _is_file_of_key(self, name: str) -> bool:
        r"""Indicate whether the directory has the file of a key.

        Args:
            name: The file name of the key.

        Returns:
            ``True`` if the file exists and belongs to the store.
        """
        return os.path.isfile(os.path.join(self._path, name)) and not self._is_shadowed(  # noqa: PTH113, PTH118
            name
        )

    def _is_shadowed(self, name: str) -> bool:
        r"""Indicate whether the file of another store occupies a file
        name, on a file system that ignores case.

        Args:
            name: The file name of a key.

        Returns:
            ``True`` if the name leads to a file that has another name.
        """
        # The directory is listed only for the names found by _open.
        return (
            name in self._shadowed
            and (self._path / name).exists()
            and name not in os.listdir(self._path)  # noqa: PTH208
        )

    def _check_not_shadowed(self, names: dict[str, str]) -> None:
        r"""Check that no file of another store occupies the names of
        some keys.

        Args:
            names: The file name of each key.

        Raises:
            ValueError: If a name is occupied.
        """
        for key, name in names.items():
            if self._is_shadowed(name):
                msg = (
                    f"The key {key!r} cannot be written: a file of {str(self._path)!r} has the "
                    f"name {name!r} in another case, which this file system does not "
                    "distinguish. Rename or delete that file."
                )
                raise ValueError(msg)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"path": str(self._path), "closed": self.closed}
        if self._codec.name != "json":
            kwargs["codec"] = self._codec
        return kwargs


def _encode_file_name(key: str, extension: str) -> str:
    r"""Return the name of the file of a key.

    Args:
        key: The key.
        extension: The extension of the file, with its dot.

    Returns:
        The percent-encoded key, whose only upper-case letters are the
        hexadecimal digits of the escapes, followed by the extension.

    Raises:
        ValueError: If the key contains a lone surrogate, or if the name
            is longer than 255 characters.
    """
    try:
        quoted = quote(key, safe="")
    except UnicodeEncodeError as exc:
        msg = f"A key of FileStore must be valid Unicode, but it has a lone surrogate: {key!r}"
        raise ValueError(msg) from exc
    name = _ESCAPE_OR_UPPER.sub(_escape_upper, quoted) + extension
    if len(name) > _MAX_FILE_NAME_LENGTH:
        msg = (
            f"The key is too long for FileStore: its file name would have {len(name)} "
            f"characters, more than {_MAX_FILE_NAME_LENGTH}: {key[:50]!r}..."
        )
        raise ValueError(msg)
    return name


def _escape_upper(match: re.Match[str]) -> str:
    r"""Percent-encode an upper-case letter, and keep an escape.

    Args:
        match: A match of an escape, or of an upper-case letter (in the
            first group).

    Returns:
        The escape of the letter, or the matched escape.
    """
    letter = match[1]
    return match[0] if letter is None else f"%{ord(letter):02X}"


def _decode_file_name(name: str, extension: str) -> str | None:
    r"""Return the key of a file name.

    Args:
        name: The name of a file.
        extension: The extension of the files of the store, with its dot.

    Returns:
        The key, or ``None`` if the name is not the name of the file of a
        key.
    """
    if not name.endswith(extension):
        return None
    key = unquote(name.removesuffix(extension))
    # Only one name per key: a name with another encoding is not listed.
    with contextlib.suppress(ValueError):
        if _encode_file_name(key, extension) == name:
            return key
    return None


def _find_shadowed_names(directory: Path, extension: str) -> set[str]:
    r"""Find the file names of keys that lead to a file with another
    name, which only happens on a file system that ignores case.

    Only the files whose name has an upper-case letter outside its escapes
    are considered, such as the files that earlier versions wrote for keys
    with upper-case letters.

    Args:
        directory: The directory of the store.
        extension: The extension of the files of the store, with its dot.

    Returns:
        The names that are occupied.
    """
    names = set(os.listdir(directory))  # noqa: PTH208
    shadowed: set[str] = set()
    for name in names:
        # The name of the file of a key has no upper-case letter outside
        # its escapes: this check is cheap, unlike the others.
        if not name.endswith(extension) or not _HAS_UPPER.match(name.removesuffix(extension)):
            continue
        key = unquote(name.removesuffix(extension).lower())
        with contextlib.suppress(ValueError):
            other = _encode_file_name(key, extension)
            if (
                other.lower() == name.lower()
                and other not in names
                and (directory / other).exists()
            ):
                shadowed.add(other)
    return shadowed


def _write_file(path: Path, payload: Payload) -> None:
    r"""Write a file atomically: a reader sees the old content or the new
    one.

    Args:
        path: The file to write.
        payload: The content. A ``str`` is written in UTF-8.

    Raises:
        OSError: If the file cannot be written. The old content is kept.
    """
    data = payload.encode() if isinstance(payload, str) else payload
    # Not derived from the name of the file, whose length can be at the
    # limit, and without the extension of a store, so it is never listed.
    temporary = path.with_name(f".{uuid4().hex}.tmp")
    try:
        with open(temporary, "xb") as file:  # noqa: PTH123
            file.write(data)
        os.replace(temporary, path)  # noqa: PTH105
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
