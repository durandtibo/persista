r"""Provide the predicate of the filters: the equality of the top-level
fields of a value, with the types of JSON.

:meth:`persista.store.BaseStore.filter` applies it to the decoded
values, with every backend and every codec.
"""

from __future__ import annotations

__all__ = ["matches_filter", "values_equal"]

from numbers import Number
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence, Set as AbstractSet


def matches_filter(value: Mapping[str, Any], fields: Mapping[str, Any]) -> bool:
    r"""Indicate whether a value matches a filter.

    Only the top-level fields of the value are compared: a name such as
    ``"a.b"`` is the name of a field, not a path.

    Args:
        value: A value of a store.
        fields: The expected value of each field. An expected ``None``
            matches a field that is ``None`` or absent.

    Returns:
        ``True`` if every field of ``value`` is equal to the expected one,
        as defined by :func:`values_equal`, including when ``fields`` is
        empty.

    Example:
        ```pycon
        >>> from persista.store.predicate import matches_filter
        >>> matches_filter({"author": "Alice", "year": 2024}, {"year": 2024.0})
        True
        >>> matches_filter({"year": "2024"}, {"year": 2024})
        False
        >>> matches_filter({"author": "Alice"}, {"year": None})
        True

        ```
    """
    # A loop is much faster than all() for the few fields of a filter,
    # which matters because every candidate is checked.
    for name, expected in fields.items():
        if not values_equal(value.get(name), expected):
            break
    else:
        return True
    return False


def values_equal(first: Any, second: Any) -> bool:
    r"""Indicate whether two values are equal, with the types of JSON.

    The values are compared as follows, at any depth:

    - ``None`` is only equal to ``None``;
    - a ``bool`` is only equal to the same ``bool``: ``True`` is not ``1``;
    - two numbers are equal if they have the same exact value: ``1`` is
      equal to ``1.0``, and ``2**53 + 1`` is not equal to
      ``float(2**53)``. ``NaN`` is equal to nothing, not even to itself;
    - a ``str`` is only equal to a ``str`` with the same characters (no
      Unicode normalization): ``"1"`` is not ``1``;
    - a ``list`` and a ``tuple`` are arrays: they are equal if they have
      the same length and equal items, in the same order;
    - two ``dict`` are equal if they have equal keys with equal values, in
      any order. A key that is absent is not equal to a key whose value is
      ``None``;
    - two ``set`` or ``frozenset`` are equal if they have equal items;
    - any other object, which only a codec such as
      :class:`~persista.store.PickleCodec` can keep, is equal to an object
      of the same class (or of a subclass) that compares equal with
      ``==``.

    An instance of a subclass of a JSON type, such as a ``str`` enum or a
    named tuple, is compared as the JSON type.

    Args:
        first: A value.
        second: Another value.

    Returns:
        ``True`` if the two values are equal.

    Raises:
        RecursionError: If both values are nested a few hundred levels
            deep, or contain themselves.

    Example:
        ```pycon
        >>> from persista.store.predicate import values_equal
        >>> values_equal([1, {"a": (2, 3)}], (1.0, {"a": [2, 3]}))
        True
        >>> values_equal([1], [True])
        False

        ```
    """
    # The most frequent comparisons first.
    kind = type(first)
    if kind is type(second) and (kind is str or kind is int or kind is float):
        return first == second
    if first is None or second is None:
        return first is second
    # bool is a subclass of int, so it is checked before the numbers.
    if isinstance(first, bool) or isinstance(second, bool):
        return isinstance(first, bool) and isinstance(second, bool) and first == second
    if isinstance(first, str) or isinstance(second, str):
        # str.__eq__ ignores the equality that a subclass can define.
        return isinstance(first, str) and isinstance(second, str) and str.__eq__(first, second)
    if isinstance(first, Number) or isinstance(second, Number):
        # Python compares an int and a float exactly, without rounding.
        return isinstance(first, Number) and isinstance(second, Number) and bool(first == second)
    return _containers_equal(first, second)


def _containers_equal(first: Any, second: Any) -> bool:
    r"""Compare two values that are not ``None``, booleans, strings or
    numbers, as :func:`values_equal` does.

    Args:
        first: A value.
        second: Another value.

    Returns:
        ``True`` if the two values are equal.
    """
    for kinds, equal in _CONTAINERS:
        if isinstance(first, kinds) or isinstance(second, kinds):
            return isinstance(first, kinds) and isinstance(second, kinds) and equal(first, second)
    if not (isinstance(first, type(second)) or isinstance(second, type(first))):
        return False
    return bool(first == second)


def _arrays_equal(first: Sequence[Any], second: Sequence[Any]) -> bool:
    r"""Compare two arrays as :func:`values_equal` does.

    Args:
        first: A ``list`` or a ``tuple``.
        second: Another ``list`` or ``tuple``.

    Returns:
        ``True`` if the two arrays have equal items in the same order.
    """
    return len(first) == len(second) and all(map(values_equal, first, second))


def _dicts_equal(first: dict[Any, Any], second: dict[Any, Any]) -> bool:
    r"""Compare two ``dict`` as :func:`values_equal` does.

    Args:
        first: A ``dict``.
        second: Another ``dict``.

    Returns:
        ``True`` if the two ``dict`` have equal keys with equal values.
    """
    return _sets_equal(first.keys(), second.keys()) and all(
        values_equal(value, second[key]) for key, value in first.items()
    )


def _sets_equal(first: AbstractSet[Any], second: AbstractSet[Any]) -> bool:
    r"""Compare the items of two sets as :func:`values_equal` does.

    Args:
        first: A set, or the keys of a ``dict``.
        second: Another set, or the keys of a ``dict``.

    Returns:
        ``True`` if each item of one set is equal to an item of the other.
    """
    if len(first) != len(second):
        return False
    # The set operations of Python find the item that it considers equal
    # (such as 1 for True), which values_equal then compares with its type.
    items = {item: item for item in second}
    return all(item in items and values_equal(item, items[item]) for item in first)


# The types that are compared item by item, and the function that compares
# them.
_CONTAINERS: tuple[tuple[tuple[type, ...], Callable[[Any, Any], bool]], ...] = (
    ((list, tuple), _arrays_equal),
    ((dict,), _dicts_equal),
    ((set, frozenset), _sets_equal),
)
