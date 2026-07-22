r"""Provide shared URI encode/decode helpers used by the path-based
store families (file, SQLite, DuckDB, LMDB) to implement
``to_uri``/``from_uri``."""

from __future__ import annotations

__all__ = ["decode_path_uri", "encode_path_uri"]

from urllib.parse import quote, unquote, urlsplit, urlunsplit


def encode_path_uri(scheme: str, path: str) -> str:
    """Encode a path/identifier as a URI under the given scheme.

    Args:
        scheme: The URI scheme (e.g. ``"sqlite"``, ``"file+json"``).
        path: The path or identifier to encode (e.g. a filesystem
            path, or the SQLite/DuckDB ``":memory:"`` sentinel).

    Returns:
        A URI string that :func:`decode_path_uri` can invert.
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
    """
    parsed = urlsplit(uri)
    if parsed.scheme != expected_scheme:
        msg = f"Invalid scheme for {uri!r}: expected {expected_scheme!r}, got {parsed.scheme!r}"
        raise ValueError(msg)
    return unquote(parsed.netloc + parsed.path)
