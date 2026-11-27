r"""Provide the codecs that turn the values of a store into payloads.

A store never keeps the objects it is given: it keeps the payload that
its codec builds from a value, and decodes a new object from it on each
read. The codec therefore defines which values a store accepts and what
a read returns.
"""

from __future__ import annotations

__all__ = ["Codec", "JsonCodec", "PickleCodec", "check_is_dict", "check_json_content"]

import json
import pickle
from typing import Any, Protocol

from coola.display import InlineDisplayMixin

# Reused by every encoding: json.dumps builds a new encoder on each call
# when an option, such as allow_nan, differs from its default.
_JSON_ENCODER = json.JSONEncoder(allow_nan=False)


def check_is_dict(value: Any) -> None:
    r"""Check that a value of a store is a ``dict``.

    Args:
        value: The value to check.

    Raises:
        TypeError: If ``value`` is not a ``dict``.

    Example:
        ```pycon
        >>> from persista.store.codec import check_is_dict
        >>> check_is_dict({"title": "Intro to Python"})
        >>> check_is_dict(["Intro to Python"])
        Traceback (most recent call last):
            ...
        TypeError: A value must be a dict, not list

        ```
    """
    if not isinstance(value, dict):
        msg = f"A value must be a dict, not {type(value).__name__}"
        raise TypeError(msg)


def check_json_content(value: dict[str, Any]) -> None:
    r"""Check that encoding a value as JSON loses no data.

    This function only checks what :func:`json.dumps` accepts without
    error: it assumes that ``value`` can be serialized by
    ``json.dumps(value, allow_nan=False)``, which rejects the other
    unsupported values, including a value that contains itself.

    Args:
        value: The value to check.

    Raises:
        TypeError: If a ``dict``, at any depth, has a key that is not a
            ``str``.
        ValueError: If a ``dict``, at any depth, has two keys that are the
            same JSON string, or if a string contains a lone surrogate.

    Example:
        ```pycon
        >>> from persista.store.codec import check_json_content
        >>> check_json_content({"tags": ["python"]})
        >>> check_json_content({"authors": [{1: "Alice"}]})
        Traceback (most recent call last):
            ...
        TypeError: dict keys must be str, not int: 1

        ```
    """
    # A stack instead of recursion: this runs for every value written.
    stack: list[Any] = [value]
    while stack:
        obj = stack.pop()
        if isinstance(obj, dict):
            _check_json_keys(obj)
            obj = obj.values()
        for item in obj:
            if isinstance(item, str):
                if not str.isascii(item):
                    _check_no_surrogate(item)
            elif isinstance(item, (dict, list, tuple)):
                stack.append(item)


def _check_json_keys(mapping: dict[Any, Any]) -> None:
    r"""Check that the keys of a ``dict`` are different JSON strings.

    Args:
        mapping: The ``dict`` whose keys are checked.

    Raises:
        TypeError: If a key is not a ``str``.
        ValueError: If two keys are the same JSON string, or if a key
            contains a lone surrogate.
    """
    has_str_subclass = False
    for key in mapping:
        if type(key) is not str:
            if not isinstance(key, str):
                msg = f"dict keys must be str, not {type(key).__name__}: {key!r}"
                raise TypeError(msg)
            has_str_subclass = True
        if not str.isascii(key):
            _check_no_surrogate(key)
    # A subclass of str can define its own equality, so two keys of the
    # dict can be one JSON string.
    if has_str_subclass and len({str.__str__(key) for key in mapping}) != len(mapping):
        msg = f"dict keys must be different JSON strings: {list(mapping)!r}"
        raise ValueError(msg)


def _check_no_surrogate(text: str) -> None:
    r"""Check that a string contains no lone surrogate.

    Args:
        text: The string to check.

    Raises:
        ValueError: If ``text`` contains a lone surrogate.
    """
    try:
        str.encode(text, "utf-8")
    except UnicodeEncodeError as exc:
        msg = f"A string must be valid Unicode, but it contains a lone surrogate: {text!r}"
        raise ValueError(msg) from exc


class Codec(Protocol):
    r"""Define the interface of the codec of a store.

    A codec turns a value (a ``dict``) into a payload (``str`` or
    ``bytes``) and back. A read of a store returns
    ``codec.decode(codec.encode(value))``.

    Example:
        ```pycon
        >>> from persista.store import Codec, JsonCodec
        >>> codec: Codec = JsonCodec()
        >>> codec.decode(codec.encode({"point": (1, 2)}))
        {'point': [1, 2]}

        ```
    """

    #: Name of the codec, such as ``"json"`` or ``"pickle"``. A SQL store
    #: uses it to select the type of its value column.
    name: str

    def encode(self, value: dict[str, Any]) -> str | bytes:
        r"""Turn a value into a payload.

        Args:
            value: The value to encode.

        Returns:
            The payload.

        Raises:
            TypeError: If ``value`` is not a ``dict``, or contains an
                object that the codec cannot encode.
            ValueError: If ``value`` cannot be encoded without losing
                data.
        """
        raise NotImplementedError

    def decode(self, payload: str | bytes) -> dict[str, Any]:
        r"""Turn a payload back into a value.

        Args:
            payload: A payload built by :meth:`encode`.

        Returns:
            A new value, which shares no object with the value that was
            encoded.
        """
        raise NotImplementedError


class JsonCodec(InlineDisplayMixin):
    r"""Implement a codec that encodes values as JSON.

    This is the default codec of the stores. A payload is a ``str``.

    A value that JSON cannot represent without losing data is rejected.
    The other differences between a value and the value read back only
    widen a type:

    - a tuple is read back as a list;
    - an instance of a subclass of ``str``, ``int``, ``float``, ``list``
      or ``dict`` (for example a ``str`` enum or a named tuple) is read
      back as an instance of the built-in type.

    The following values are rejected, at any depth:

    - a ``dict`` key that is not a ``str`` (``TypeError``): JSON would turn
      ``1`` into ``"1"``, and could merge two entries into one;
    - two keys of a ``dict`` that are the same JSON string, which is only
      possible with a subclass of ``str`` (``ValueError``);
    - ``NaN`` and infinity (``ValueError``), which are not valid JSON;
    - a string with a lone surrogate (``ValueError``), which is not valid
      Unicode and which some databases reject;
    - an object of another type, such as a ``set`` or ``bytes``
      (``TypeError``);
    - a value that contains itself (``ValueError``).

    Example:
        ```pycon
        >>> from persista.store import JsonCodec
        >>> codec = JsonCodec()
        >>> codec.encode({"title": "Intro to Python", "tags": ("python",)})
        '{"title": "Intro to Python", "tags": ["python"]}'
        >>> codec.encode({1: "one"})
        Traceback (most recent call last):
            ...
        TypeError: dict keys must be str, not int: 1

        ```
    """

    name: str = "json"

    def encode(self, value: dict[str, Any]) -> str:
        r"""Turn a value into a JSON string.

        Args:
            value: The value to encode.

        Returns:
            The JSON string.

        Raises:
            TypeError: If ``value`` is not a ``dict``, contains a ``dict``
                key that is not a ``str``, or contains an object that JSON
                cannot represent.
            ValueError: If ``value`` contains ``NaN``, infinity, a lone
                surrogate, duplicate JSON keys, or itself.
        """
        check_is_dict(value)
        # The encoder runs first: it rejects a value that contains itself,
        # so the walk below always ends.
        payload = _JSON_ENCODER.encode(value)
        check_json_content(value)
        return payload

    def decode(self, payload: str | bytes) -> dict[str, Any]:
        r"""Turn a JSON string back into a value.

        Args:
            payload: A JSON object, as a ``str`` or as UTF-8 ``bytes``.

        Returns:
            The value.

        Raises:
            ValueError: If ``payload`` is not valid JSON.
        """
        return json.loads(payload)

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {}


class PickleCodec(InlineDisplayMixin):
    r"""Implement a codec that encodes values with :mod:`pickle`.

    A payload is ``bytes``. A value is read back with its types, so this
    codec accepts any ``dict`` that can be pickled, including tuples,
    sets, ``bytes``, non-``str`` keys, and instances of classes that can
    be imported.

    .. warning::
        Decoding a payload can execute arbitrary code. Only use this
        codec with data from trusted sources.

    Example:
        ```pycon
        >>> from persista.store import PickleCodec
        >>> codec = PickleCodec()
        >>> codec.decode(codec.encode({"point": (1, 2), 3: {4}}))
        {'point': (1, 2), 3: {4}}

        ```
    """

    name: str = "pickle"

    def encode(self, value: dict[str, Any]) -> bytes:
        r"""Pickle a value.

        Args:
            value: The value to encode.

        Returns:
            The pickled value.

        Raises:
            TypeError: If ``value`` is not a ``dict``.
            Exception: Any error that :func:`pickle.dumps` raises for an
                object that cannot be pickled, such as ``TypeError`` or
                ``pickle.PicklingError``.
        """
        check_is_dict(value)
        return pickle.dumps(value)

    def decode(self, payload: str | bytes) -> dict[str, Any]:
        r"""Unpickle a value.

        Args:
            payload: A payload built by :meth:`encode`.

        Returns:
            The value.

        Raises:
            TypeError: If ``payload`` is a ``str``.
        """
        if isinstance(payload, str):
            msg = "A pickle payload must be bytes, not str"
            raise TypeError(msg)
        return pickle.loads(payload)  # noqa: S301

    def _get_repr_kwargs(self) -> dict[str, Any]:
        return {}
