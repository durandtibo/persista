r"""Provide sorting utilities for Record collections."""

from __future__ import annotations

__all__ = ["sort_by_metadata"]

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from persista.record.record import Record


def sort_by_metadata(
    records: list[Record],
    metadata_key: str,
    *,
    keep_missing: bool = True,
    reverse: bool = False,
) -> list[Record]:
    """Sort a list of records by the value of a metadata key.

    Records are sorted in ascending order by the value of
    ``metadata_key`` by default, or descending order if
    ``reverse=True``.  Records that do not contain ``metadata_key``
    in their metadata are placed at the end of the result by default,
    or removed entirely if ``keep_missing=False``.

    Args:
        records: The list of :class:`~persista.record.Record` instances to sort.
        metadata_key: The metadata key to sort by.
        keep_missing: If ``True`` (the default), records without
            ``metadata_key`` in their metadata are kept and placed at
            the end of the result.  If ``False``, they are excluded
            from the result entirely.
        reverse: If ``True``, the result is sorted in descending order.
            Defaults to ``False``, matching the behaviour of
            :func:`sorted`.

    Returns:
        A new sorted list of :class:`~persista.record.Record` instances.  The
        original list is not modified.

    Raises:
        TypeError: If the metadata values for ``metadata_key`` are not
            mutually comparable (e.g. mixing ``str`` and ``int``).

    Example:
        ```pycon
        >>> from persista.record import Record, sort_by_metadata
        >>> records = [
        ...     Record(id="b", metadata={"source": "b.txt"}),
        ...     Record(id="a", metadata={"source": "a.txt"}),
        ...     Record(id="c"),
        ... ]
        >>> sorted_records = sort_by_metadata(records, "source")
        >>> [r.metadata.get("source") for r in sorted_records]
        ['a.txt', 'b.txt', None]
        >>> sorted_records = sort_by_metadata(records, "source", reverse=True)
        >>> [r.metadata.get("source") for r in sorted_records]
        ['b.txt', 'a.txt', None]
        >>> sorted_records = sort_by_metadata(records, "source", keep_missing=False)
        >>> [r.metadata.get("source") for r in sorted_records]
        ['a.txt', 'b.txt']

        ```
    """
    _missing = object()

    def sort_key(record: Record) -> tuple:
        value = record.metadata.get(metadata_key, _missing)
        return (value is _missing, value if value is not _missing else None)

    if not keep_missing:
        records = [r for r in records if metadata_key in r.metadata]
        return sorted(records, key=sort_key, reverse=reverse)

    present = [r for r in records if metadata_key in r.metadata]
    missing = [r for r in records if metadata_key not in r.metadata]
    return sorted(present, key=sort_key, reverse=reverse) + missing
