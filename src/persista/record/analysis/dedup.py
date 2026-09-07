r"""Duplicate record detection."""

from __future__ import annotations

__all__ = ["find_duplicate_record_ids"]

from typing import TYPE_CHECKING, Any

from coola.hashing import hash_object

if TYPE_CHECKING:
    from collections.abc import Iterable

    from persista.record import Record


def find_duplicate_record_ids(records: Iterable[Record]) -> list[list[Any]]:
    r"""Group record ids that share exactly the same ``metadata``.

    Records are consumed one at a time, so this works with generators
    or other iterables whose full contents cannot fit in memory. Only a
    hash of each record's metadata is retained (rather than the full
    metadata itself), making this more memory-efficient for large
    corpora. The hash is computed via
    :func:`coola.hashing.hash_object` with ``ignore_unhashable=True``,
    so metadata containing values with no registered hasher is
    tolerated (grouped by a deterministic placeholder) rather than
    raising.

    Args:
        records: A list, generator, or other iterable of
            ``persista.record.Record`` objects. Consumed exactly once;
            if a generator/iterator is passed in, it will be exhausted
            by this call.

    Returns:
        A list of groups of record ``id``s whose ``metadata`` is
        identical. Each group contains two or more ids, in the order
        their records were encountered; groups are in the order their
        first member was encountered. Records with unique metadata are
        not included in the result.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.analysis import find_duplicate_record_ids
        >>> records = [
        ...     Record(id="a", metadata={"source": "a.pdf"}),
        ...     Record(id="b", metadata={"source": "a.pdf"}),
        ...     Record(id="c", metadata={"source": "b.pdf"}),
        ... ]
        >>> find_duplicate_record_ids(records)
        [['a', 'b']]

        ```

    See Also:
        ``count_approx_duplicate_records``: an approximate variant
        using a Bloom filter, with fixed (O(1)) memory usage, better
        suited to corpora too large for the exact hash groups above to
        fit in memory.
    """
    groups: dict[str, list[Any]] = {}
    for record in records:
        metadata_hash = hash_object(dict(record.metadata), ignore_unhashable=True)
        groups.setdefault(metadata_hash, []).append(record.id)
    return [group for group in groups.values() if len(group) > 1]
