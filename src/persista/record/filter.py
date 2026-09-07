r"""Provide filtering utilities for Record collections."""

from __future__ import annotations

__all__ = ["filter_by_metadata", "filter_by_metadata_range", "filter_by_metadata_values"]

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from persista.record.record import Record


def filter_by_metadata(
    records: list[Record],
    metadata_key: str,
    value: Any,
) -> list[Record]:
    """Filter a list of records by the value of a metadata key.

    Returns a new list containing only records whose metadata contains
    ``metadata_key`` with a value equal to ``value``.  Records missing
    ``metadata_key`` are excluded.

    Warning:
        Because the lookup uses ``dict.get`` with a default of
        ``None``, calling this with ``value=None`` also matches
        records that do not have ``metadata_key`` at all, not only
        records whose ``metadata_key`` is explicitly set to ``None``.

    Args:
        records: The list of :class:`~persista.record.Record` instances to
            filter.
        metadata_key: The metadata key to filter by.
        value: The value to match against.  Records whose
            ``metadata_key`` equals this value are kept.

    Returns:
        A new list of :class:`~persista.record.Record` instances whose metadata
        matches the filter.  The original list is not modified.

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
    return [r for r in records if r.metadata.get(metadata_key) == value]


def filter_by_metadata_range(
    records: list[Record],
    metadata_key: str,
    lower: Any = None,
    upper: Any = None,
) -> list[Record]:
    """Filter a list of records by a range of values for a metadata key.

    Returns a new list containing only records whose metadata contains
    ``metadata_key`` with a value within the specified range
    ``[lower, upper]`` (inclusive on both ends).  Either bound can be
    set to ``None`` to indicate no constraint on that side.  If both
    bounds are ``None``, all records that contain ``metadata_key`` are
    returned.  Records missing ``metadata_key`` are always excluded.

    Args:
        records: The list of :class:`~persista.record.Record` instances to
            filter.
        metadata_key: The metadata key to filter by.
        lower: The inclusive lower bound.  Pass ``None`` (the default)
            for no lower bound.
        upper: The inclusive upper bound.  Pass ``None`` (the default)
            for no upper bound.

    Returns:
        A new list of :class:`~persista.record.Record` instances whose
        ``metadata_key`` value falls within ``[lower, upper]``.  The
        original list is not modified.

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
        value = record.metadata.get(metadata_key)
        if value is None and metadata_key not in record.metadata:
            return False
        if lower is not None and value < lower:
            return False
        return not (upper is not None and value > upper)

    return [r for r in records if in_range(r)]


def filter_by_metadata_values(
    records: list[Record],
    metadata_key: str,
    values: set[Any],
) -> list[Record]:
    """Filter a list of records by checking if a metadata value is in a
    set.

    Returns a new list containing only records whose metadata contains
    ``metadata_key`` with a value that is a member of ``values``.
    Records missing ``metadata_key`` are excluded.

    Warning:
        Because the lookup uses ``dict.get`` with a default of
        ``None``, including ``None`` in ``values`` also matches
        records that do not have ``metadata_key`` at all, not only
        records whose ``metadata_key`` is explicitly set to ``None``.

    Args:
        records: The list of :class:`~persista.record.Record` instances to
            filter.
        metadata_key: The metadata key to filter by.
        values: The set of accepted values.  Records whose
            ``metadata_key`` is in this set are kept.

    Returns:
        A new list of :class:`~persista.record.Record` instances whose
        ``metadata_key`` value is in ``values``.  The original list is
        not modified.

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
    return [r for r in records if r.metadata.get(metadata_key) in values]
