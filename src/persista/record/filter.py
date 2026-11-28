r"""Provide filtering utilities for Record collections.

The equality filters compare the values with the predicate of the stores
(:mod:`persista.store.predicate`), so they select the same records as
:meth:`persista.record.store.RecordStore.filter`.
"""

from __future__ import annotations

__all__ = ["filter_by_metadata", "filter_by_metadata_range", "filter_by_metadata_values"]

from itertools import chain
from typing import TYPE_CHECKING, Any

from persista.store.predicate import matches_filter, values_equal

if TYPE_CHECKING:
    from collections.abc import Iterable

    from persista.record.record import Record

# Sentinel used to distinguish "metadata key absent" from "metadata key
# present with a value of None" in the range filter below.
_MISSING = object()


def filter_by_metadata(
    records: Iterable[Record],
    metadata_key: str,
    value: Any,
) -> list[Record]:
    """Filter records by the value of a metadata key.

    Returns a new list containing only the records whose
    ``metadata_key`` is equal to ``value``, with the equality of the
    filters of the stores (see
    :func:`persista.store.predicate.values_equal`): ``True`` is not
    ``1``, ``"1"`` is not ``1``, ``1`` is ``1.0`` and ``NaN`` matches
    nothing. ``value=None`` matches a record whose ``metadata_key`` is
    ``None`` or absent. Any other value excludes the records without
    ``metadata_key``.

    Args:
        records: The :class:`~persista.record.Record` instances to
            filter. Any iterable is accepted; it is consumed once.
        metadata_key: The metadata key to filter by.
        value: The value to match against.

    Returns:
        A new list of the :class:`~persista.record.Record` instances that
        match the filter, in their order.  The input is not modified.

    Example:
        ```pycon
        >>> from persista.record import Record, filter_by_metadata
        >>> records = [
        ...     Record(id="a", metadata={"category": "Science"}),
        ...     Record(id="b", metadata={"category": "Cooking"}),
        ...     Record(id="c", metadata={"category": "Science"}),
        ... ]
        >>> result = filter_by_metadata(records, "category", "Science")
        >>> [r.id for r in result]
        ['a', 'c']

        ```
    """
    fields = {metadata_key: value}
    return [r for r in records if matches_filter(r.metadata, fields)]


def filter_by_metadata_range(
    records: Iterable[Record],
    metadata_key: str,
    lower: Any = None,
    upper: Any = None,
) -> list[Record]:
    """Filter records by a range of values for a metadata key.

    Returns a new list containing only records whose metadata contains
    ``metadata_key`` with a value within the specified range
    ``[lower, upper]`` (inclusive on both ends).  Either bound can be
    set to ``None`` to indicate no constraint on that side.  If both
    bounds are ``None``, all records that contain ``metadata_key`` are
    returned.  Records missing ``metadata_key`` are always excluded.

    The bounds are compared with the order of Python (``<`` and ``>``),
    not with the equality of the filters: for example, ``True`` is
    ordered as ``1``.

    Args:
        records: The :class:`~persista.record.Record` instances to
            filter. Any iterable is accepted; it is consumed once.
        metadata_key: The metadata key to filter by.
        lower: The inclusive lower bound.  Pass ``None`` (the default)
            for no lower bound.
        upper: The inclusive upper bound.  Pass ``None`` (the default)
            for no upper bound.

    Returns:
        A new list of :class:`~persista.record.Record` instances whose
        ``metadata_key`` value falls within ``[lower, upper]``.  The
        input is not modified.

    Raises:
        TypeError: If the metadata values are not comparable with the
            provided bounds (e.g. comparing ``str`` with ``int``).

    Example:
        ```pycon
        >>> from persista.record import Record, filter_by_metadata_range
        >>> records = [
        ...     Record(id="a", metadata={"page": 1}),
        ...     Record(id="b", metadata={"page": 5}),
        ...     Record(id="c", metadata={"page": 10}),
        ... ]
        >>> result = filter_by_metadata_range(records, "page", lower=2, upper=8)
        >>> [r.id for r in result]
        ['b']
        >>> result = filter_by_metadata_range(records, "page", lower=5)
        >>> [r.id for r in result]
        ['b', 'c']
        >>> result = filter_by_metadata_range(records, "page", upper=5)
        >>> [r.id for r in result]
        ['a', 'b']

        ```
    """

    def in_range(record: Record) -> bool:
        value = record.metadata.get(metadata_key, _MISSING)
        if value is _MISSING:
            return False
        if lower is not None and value < lower:
            return False
        return not (upper is not None and value > upper)

    return [r for r in records if in_range(r)]


def filter_by_metadata_values(
    records: Iterable[Record],
    metadata_key: str,
    values: Iterable[Any],
) -> list[Record]:
    """Filter records by checking if a metadata value is one of the
    accepted values.

    Returns a new list containing only the records whose
    ``metadata_key`` is equal to one of ``values``, with the equality of
    :func:`filter_by_metadata`. A ``None`` in ``values`` matches a record
    whose ``metadata_key`` is ``None`` or absent.

    Args:
        records: The :class:`~persista.record.Record` instances to
            filter. Any iterable is accepted; it is consumed once.
        metadata_key: The metadata key to filter by.
        values: The accepted values, in any iterable, consumed once.
            Python itself merges ``1`` and ``True`` in a set: use a list
            to accept both.

    Returns:
        A new list of the :class:`~persista.record.Record` instances
        whose ``metadata_key`` is one of ``values``, in their order.  The
        inputs are not modified.

    Example:
        ```pycon
        >>> from persista.record import Record, filter_by_metadata_values
        >>> records = [
        ...     Record(id="a", metadata={"category": "Science"}),
        ...     Record(id="b", metadata={"category": "Cooking"}),
        ...     Record(id="c", metadata={"category": "Technology"}),
        ...     Record(id="d", metadata={"category": "Science"}),
        ... ]
        >>> result = filter_by_metadata_values(records, "category", {"Science", "Technology"})
        >>> sorted(r.id for r in result)
        ['a', 'c', 'd']

        ```
    """
    index, others = _index_values(values)
    return [r for r in records if _is_member(r.metadata.get(metadata_key), index, others)]


def _index_values(values: Iterable[Any]) -> tuple[dict[Any, list[Any]], list[Any]]:
    r"""Index values to find quickly the ones that can be equal to
    another value.

    Args:
        values: The values to index.

    Returns:
        The hashable values, grouped under a value that Python considers
        equal to them (``1``, ``1.0`` and ``True`` are in one group), and the
        values that cannot be hashed.
    """
    index: dict[Any, list[Any]] = {}
    others: list[Any] = []
    for value in values:
        try:
            index.setdefault(value, []).append(value)
        except TypeError:
            others.append(value)
    return index, others


def _is_member(value: Any, index: dict[Any, list[Any]], others: list[Any]) -> bool:
    r"""Indicate whether a value is equal to one of the indexed values.

    Args:
        value: The value to look for.
        index: The hashable values, as built by ``_index_values``.
        others: The values that cannot be hashed.

    Returns:
        ``True`` if ``value`` is equal to one of the values, as defined by
        :func:`persista.store.predicate.values_equal`.
    """
    try:
        # Among the hashable values, only one that Python considers equal
        # can be equal.
        bucket = index.get(value, ())
    except TypeError:
        # An unhashable value, such as a list, can be equal to a hashable
        # one, such as a tuple.
        candidates = chain(others, *index.values())
    else:
        # Most values match nothing: return without comparing them.
        if not bucket and not others:
            return False
        candidates = chain(bucket, others)
    return any(values_equal(value, candidate) for candidate in candidates)
