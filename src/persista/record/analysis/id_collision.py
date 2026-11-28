r"""Record id collision detection."""

from __future__ import annotations

__all__ = ["find_id_collisions"]

from typing import TYPE_CHECKING, Any

from persista.record.equality import hash_metadata

if TYPE_CHECKING:
    from collections.abc import Iterable

    from persista.record import Record


def find_id_collisions(records: Iterable[Record]) -> dict[Any, list[dict[str, Any]]]:
    r"""Find record ids that are reused across records with different
    metadata.

    ``find_duplicate_record_ids`` groups *different* ids that share
    identical metadata. This is the complementary check: it flags the
    *same* id appearing more than once with *different* metadata,
    which usually indicates an id-generation bug (e.g. a non-unique or
    colliding hash) rather than a legitimate duplicate.

    An id that appears multiple times with equal metadata (see
    :mod:`persista.record.equality`) each time is not considered a collision - it is treated as the
    same record encountered more than once.

    Records are consumed one at a time, so this works with generators
    or other iterables whose full contents cannot fit in memory.
    Memory usage is O(number of distinct ids x number of distinct
    metadata variants per id).

    Args:
        records: A list, generator, or other iterable of
            ``persista.record.Record`` objects. Consumed exactly once;
            if a generator/iterator is passed in, it will be exhausted
            by this call.

    Returns:
        A dict mapping each colliding record ``id`` to the list of
        distinct ``metadata`` values observed for it (copied into a
        ``dict``; the first one of each set of equal metadata), in the
        order they were first encountered. Ids observed with only one
        distinct metadata value (whether seen once or many times) are
        not included.

    Raises:
        TypeError: If the metadata of a record contains an object that
            cannot be compared (see :mod:`persista.record.equality`).
        ValueError: If the metadata of a record contains ``NaN``, or a
            value that contains itself.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.analysis import find_id_collisions
        >>> records = [
        ...     Record(id="a", metadata={"source": "x.pdf"}),
        ...     Record(id="a", metadata={"source": "y.pdf"}),
        ...     Record(id="b", metadata={"source": "z.pdf"}),
        ...     Record(id="b", metadata={"source": "z.pdf"}),
        ... ]
        >>> find_id_collisions(records)
        {'a': [{'source': 'x.pdf'}, {'source': 'y.pdf'}]}

        ```
    """
    # For each id, the first metadata of each hash.
    variants: dict[Any, dict[str, dict[str, Any]]] = {}
    for record in records:
        metadata = dict(record.metadata)
        variants.setdefault(record.id, {}).setdefault(hash_metadata(metadata), metadata)
    return {rid: list(metas.values()) for rid, metas in variants.items() if len(metas) > 1}
