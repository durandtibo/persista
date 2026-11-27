r"""Provide shared URI encode/decode helpers used by the path-based store
families (file, SQLite, DuckDB, LMDB) to implement
``to_uri``/``from_uri``.

The URI of a store that takes a codec carries the name of the codec in
its scheme.
"""

from __future__ import annotations

__all__ = ["codec_uri_scheme", "decode_codec_uri", "decode_path_uri", "encode_path_uri"]

from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from persista.store.codec import JsonCodec, PickleCodec

if TYPE_CHECKING:
    from collections.abc import Mapping

    from persista.store.codec import Codec


def encode_path_uri(scheme: str, path: str) -> str:
    """Encode a path/identifier as a URI under the given scheme.

    Args:
        scheme: The URI scheme (e.g. ``"sqlite"``, ``"file+json"``).
        path: The path or identifier to encode (e.g. a filesystem
            path, or the SQLite/DuckDB ``":memory:"`` sentinel).

    Returns:
        A URI string that :func:`decode_path_uri` can invert.

    Example:
        ```pycon
        >>> from persista.store.uri import encode_path_uri
        >>> encode_path_uri("sqlite", "/tmp/data.db")
        'sqlite:/tmp/data.db'

        ```
    """
    return urlunsplit((scheme, "", quote(path, safe="/"), "", ""))


def decode_path_uri(uri: str, *, expected_scheme: str) -> str:
    """Decode a URI produced by :func:`encode_path_uri`.

    Args:
        uri: The URI to decode.
        expected_scheme: The scheme ``uri`` must have.

    Returns:
        The decoded path/identifier.

    Raises:
        ValueError: If ``uri``'s scheme does not match
            ``expected_scheme``.

    Example:
        ```pycon
        >>> from persista.store.uri import decode_path_uri
        >>> decode_path_uri("sqlite:///tmp/data.db", expected_scheme="sqlite")
        '/tmp/data.db'

        ```
    """
    parsed = urlsplit(uri)
    if parsed.scheme != expected_scheme:
        msg = f"Invalid scheme for {uri!r}: expected {expected_scheme!r}, got {parsed.scheme!r}"
        raise ValueError(msg)
    return unquote(parsed.netloc + parsed.path)


def codec_uri_scheme(codec: Codec, schemes: Mapping[str, str]) -> str:
    """Return the URI scheme of a store for its codec.

    A store whose URI carries its codec calls this function to reject, in
    its constructor, a codec that no URI can describe.

    Args:
        codec: The codec of the store.
        schemes: The URI scheme of the store for each codec name that it
            supports.

    Returns:
        The scheme of the name of ``codec``.

    Raises:
        ValueError: If the name of ``codec`` is not in ``schemes``.

    Example:
        ```pycon
        >>> from persista.store import PickleCodec
        >>> from persista.store.uri import codec_uri_scheme
        >>> codec_uri_scheme(PickleCodec(), {"json": "lmdb", "pickle": "lmdb+pickle"})
        'lmdb+pickle'

        ```
    """
    if codec.name not in schemes:
        msg = f"The store needs a codec named {sorted(schemes)}, not {codec.name!r}"
        raise ValueError(msg)
    return schemes[codec.name]


def decode_codec_uri(
    uri: str, *, schemes: Mapping[str, str], codec: Codec | None = None
) -> tuple[str, Codec]:
    """Decode the URI of a store whose scheme carries its codec.

    Args:
        uri: A URI produced by :func:`encode_path_uri`.
        schemes: The URI scheme of the store for each codec name that it
            supports. The names are ``"json"`` and ``"pickle"``.
        codec: The codec to use instead of the default codec of the
            scheme of ``uri``. It must have the same name.

    Returns:
        The path/identifier and the codec.

    Raises:
        ValueError: If the scheme of ``uri`` is not in ``schemes``, or
            if the name of ``codec`` does not match the scheme.

    Example:
        ```pycon
        >>> from persista.store.uri import decode_codec_uri
        >>> decode_codec_uri(
        ...     "lmdb+pickle:/tmp/data", schemes={"json": "lmdb", "pickle": "lmdb+pickle"}
        ... )
        ('/tmp/data', PickleCodec())

        ```
    """
    scheme = urlsplit(uri).scheme
    names = {value: name for name, value in schemes.items()}
    if scheme not in names:
        msg = f"Invalid scheme for {uri!r}: expected one of {sorted(names)}, got {scheme!r}"
        raise ValueError(msg)
    location = decode_path_uri(uri, expected_scheme=scheme)
    default: Codec = PickleCodec() if names[scheme] == "pickle" else JsonCodec()
    if codec is None:
        return location, default
    if codec.name != default.name:
        msg = (
            f"The codec {codec.name!r} does not match the scheme of {uri!r}, "
            f"which is for the codec {default.name!r}"
        )
        raise ValueError(msg)
    return location, codec
