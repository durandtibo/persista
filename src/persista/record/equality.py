r"""Define when two metadata values of records are equal.

The identifiers derived by :meth:`persista.record.Record.from_metadata`
and the analyses of :mod:`persista.record.analysis` use this equality. It
is the canonical encoding of :mod:`persista.utils.canonical`, with the
numbers encoded by their value:

- ``1``, ``"1"`` and ``True`` are three different values;
- ``1`` and ``1.0`` are equal, and so are ``0.0`` and ``-0.0``, as for the
  filters (:func:`persista.store.predicate.values_equal`);
- the order of the keys of a ``dict`` does not matter;
- a ``list`` and a ``tuple`` are different values, and so are a ``set`` and
  a ``frozenset``. The filters compare them as the arrays and the sets of
  JSON, which does not tell them apart;
- ``NaN`` is equal to nothing, so a value that contains it raises
  ``ValueError``;
- only ``None``, ``bool``, ``int``, ``float``, ``str``, ``bytes``, ``list``,
  ``tuple``, ``dict``, ``set`` and ``frozenset`` can be compared. Any other
  object, such as a ``datetime``, a ``Decimal`` or an instance of a
  subclass of these types, raises ``TypeError``.
"""

from __future__ import annotations

__all__ = ["encode_value", "hash_metadata"]

from typing import TYPE_CHECKING, Any

from coola.hashing import hash_bytes

from persista.utils.canonical import encode_canonical

if TYPE_CHECKING:
    from collections.abc import Mapping


def encode_value(value: Any) -> bytes:
    r"""Encode a metadata value, so that equal values have the same
    encoding.

    Args:
        value: The value to encode.

    Returns:
        The encoding. Two values are equal if and only if they have the
        same encoding.

    Raises:
        TypeError: If ``value`` is, or contains, an object of a type that
            cannot be compared.
        ValueError: If ``value`` contains ``NaN``, or contains itself.
        RecursionError: If ``value`` is nested too deeply for the
            recursion limit of Python.

    Example:
        ```pycon
        >>> from persista.record.equality import encode_value
        >>> encode_value([1]) == encode_value([1.0])
        True
        >>> encode_value(1) == encode_value(True)
        False

        ```
    """
    return encode_canonical(value, numbers_by_value=True)


def hash_metadata(metadata: Mapping[str, Any]) -> str:
    r"""Hash the metadata of a record, so that equal metadata have the
    same hash.

    Args:
        metadata: The metadata to hash. Any mapping is hashed as a
            ``dict`` with the same items, for example the read-only
            metadata of a record.

    Returns:
        The BLAKE2b hash of the encoding of the metadata (see
        :func:`encode_value`), as 64 hexadecimal characters.

    Raises:
        TypeError: If a value of ``metadata`` is, or contains, an object
            of a type that cannot be compared.
        ValueError: If ``metadata`` contains ``NaN``, or a value that
            contains itself.
        RecursionError: If ``metadata`` is nested too deeply for the
            recursion limit of Python.

    Example:
        ```pycon
        >>> from persista.record.equality import hash_metadata
        >>> hash_metadata({"page": 1}) == hash_metadata({"page": 1.0})
        True
        >>> hash_metadata({"page": 1}) == hash_metadata({"page": "1"})
        False

        ```
    """
    return hash_bytes(encode_value(dict(metadata)))
