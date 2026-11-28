r"""Provide a canonical encoding of Python values.

Two values have the same encoding only if they are equal and have the
same types, at every depth, and the encoding does not depend on the
process that computes it. It is therefore a safe input of a hash that
identifies a value, such as the key of a memoized call.
"""

from __future__ import annotations

__all__ = ["encode_canonical", "hash_canonical"]

import math
import struct
from typing import Any

from coola.hashing import hash_bytes

_FLOAT = struct.Struct(">d")
# The tag of each type of collection.
_TAGS: dict[type, bytes] = {list: b"l", tuple: b"t", dict: b"d", set: b"S", frozenset: b"z"}
# The encodings of the values that are alone of their kind.
_CONSTANTS: dict[bool | None, bytes] = {None: b"N", True: b"T", False: b"F"}
# Every NaN is encoded as this one: the sign and the payload of a NaN
# depend on the platform and on the operation that produced it.
_NAN = bytes.fromhex("7ff8000000000000")


def encode_canonical(value: Any) -> bytes:
    r"""Encode a value in a canonical form.

    The encoding covers ``None``, ``bool``, ``int``, ``float``,
    ``str``, ``bytes``, ``list``, ``tuple``, ``dict``, ``set`` and
    ``frozenset``, nested at any depth. Each value is written with a
    tag of its type, and with its length when it has no fixed size, so
    two different values never have the same encoding:

    - the types are kept apart: ``1``, ``1.0``, ``True`` and ``"1"`` have
      four encodings, and so have a list and a tuple, or a set and a
      frozenset;
    - the order of the items of a ``dict``, a ``set`` or a ``frozenset``
      does not change the encoding: they are sorted by their encodings;
    - ``-0.0`` and ``0.0`` have different encodings, because they are
      different values, although they compare equal;
    - every ``NaN`` has the same encoding, although ``NaN`` is not equal
      to itself;
    - an ``int`` of any size can be encoded (the limit of
      ``sys.set_int_max_str_digits`` does not apply);
    - a ``str`` with a lone surrogate can be encoded;
    - an object that appears several times is encoded by value, like
      copies of it.

    Only the exact types are accepted: an instance of a subclass (for
    example a ``str`` enum, a named tuple or an ``OrderedDict``) raises,
    because it can differ from an instance of the built-in type in ways
    that the encoding would lose.

    Args:
        value: The value to encode.

    Returns:
        The encoding.

    Raises:
        TypeError: If ``value`` is, or contains, an object of another type.
        ValueError: If ``value`` contains itself.
        RecursionError: If ``value`` is nested too deeply for the
            recursion limit of Python.

    Example:
        ```pycon
        >>> from persista.utils.canonical import encode_canonical
        >>> encode_canonical([1, "1"])
        b'l2:i1:\x01s1:1'
        >>> encode_canonical({"a": 1, "b": 2}) == encode_canonical({"b": 2, "a": 1})
        True
        >>> encode_canonical((1, 2)) == encode_canonical([1, 2])
        False

        ```
    """
    return _encode(value, set())


def hash_canonical(value: Any) -> str:
    r"""Hash the canonical encoding of a value.

    Args:
        value: The value to hash. See :func:`encode_canonical` for the
            accepted values.

    Returns:
        The BLAKE2b hash of the encoding, as 64 hexadecimal characters.

    Raises:
        TypeError: If ``value`` is, or contains, an object that cannot be
            encoded.
        ValueError: If ``value`` contains itself.
        RecursionError: If ``value`` is nested too deeply for the
            recursion limit of Python.

    Example:
        ```pycon
        >>> from persista.utils.canonical import hash_canonical
        >>> len(hash_canonical({"title": "Intro to Python"}))
        64
        >>> hash_canonical(1) == hash_canonical("1")
        False

        ```
    """
    return hash_bytes(encode_canonical(value))


def _encode(value: Any, parents: set[int]) -> bytes:
    r"""Encode a value that can be in a collection.

    Args:
        value: The value to encode.
        parents: The identifiers of the collections that contain
            ``value``. It is the same after a successful call.

    Returns:
        The encoding.

    Raises:
        TypeError: If ``value`` is, or contains, an object that cannot be
            encoded.
        ValueError: If ``value`` contains itself.
    """
    # The exact type: a subclass is rejected.
    kind = type(value)
    if kind is str:
        # "surrogatepass" gives every str, also with a lone surrogate, its
        # own bytes.
        data = value.encode("utf-8", "surrogatepass")
        return b"s%d:%s" % (len(data), data)
    if kind is int:
        # Two's complement bytes, with room for the sign bit. Unlike
        # str(value), this has no limit on the size of the integer.
        data = value.to_bytes(value.bit_length() // 8 + 1, "big", signed=True)
        return b"i%d:%s" % (len(data), data)
    if value is None or kind is bool:
        return _CONSTANTS[value]
    if kind is float:
        return b"f" + (_NAN if math.isnan(value) else _FLOAT.pack(value))
    if kind is bytes:
        return b"b%d:%s" % (len(value), value)
    return _encode_collection(value, parents)


def _encode_collection(value: Any, parents: set[int]) -> bytes:
    r"""Encode a ``list``, a ``tuple``, a ``dict``, a ``set`` or a
    ``frozenset``.

    Args:
        value: The collection to encode.
        parents: The identifiers of the collections that contain
            ``value``. It is the same after a successful call.

    Returns:
        The encoding: the tag of the type, the number of items, and the
        encodings of the items.

    Raises:
        TypeError: If ``value`` is of another type, or if an object in it
            cannot be encoded.
        ValueError: If ``value`` is, or contains, one of its parents or
            itself.
    """
    kind = type(value)
    tag = _TAGS.get(kind)
    if tag is None:
        msg = f"Cannot encode an object of type {kind.__module__}.{kind.__qualname__}"
        raise TypeError(msg)
    marker = id(value)
    if marker in parents:
        msg = f"Cannot encode a {kind.__name__} that contains itself"
        raise ValueError(msg)
    parents.add(marker)
    if kind is dict:
        # Sorted by the encoding of the key, then of the value: two
        # different NaN objects are two keys with the same encoding.
        pairs = sorted(
            (_encode(key, parents), _encode(item, parents)) for key, item in value.items()
        )
        items = [key + item for key, item in pairs]
    else:
        items = [_encode(item, parents) for item in value]
        if kind is set or kind is frozenset:
            items.sort()
    parents.remove(marker)
    return b"%s%d:%s" % (tag, len(items), b"".join(items))
