r"""Metadata schema shape clustering."""

from __future__ import annotations

__all__ = ["compute_schema_shapes"]

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from persista.record import Record


def compute_schema_shapes(records: Iterable[Record]) -> dict[tuple[str, ...], list[Any]]:
    r"""Group record ids by the *shape* of their metadata, i.e. the set
    of keys present, ignoring the keys' values.

    This complements ``compute_metadata_stats``, which reports
    per-key statistics across the whole corpus but does not show which
    *combinations* of keys co-occur. A corpus with schema drift (e.g.
    some records carrying an extra field added later, or missing one
    dropped later) shows up here as multiple distinct shapes.

    Records are consumed one at a time, so this works with generators
    or other iterables whose full contents cannot fit in memory.
    Memory usage is O(number of distinct shapes), which is typically
    small even for large corpora since most pipelines only produce a
    handful of distinct metadata schemas.

    Args:
        records: A list, generator, or other iterable of
            ``persista.record.Record`` objects. Consumed exactly once;
            if a generator/iterator is passed in, it will be exhausted
            by this call.

    Returns:
        A dict mapping each distinct shape (a tuple of metadata keys,
        sorted alphabetically) to the list of record ``id``s having
        that shape, in the order their records were encountered. Keys
        are in the order their shape was first encountered. A record
        with no metadata has the shape ``()``.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.analysis import compute_schema_shapes
        >>> records = [
        ...     Record(id="a", metadata={"source": "a.pdf", "page": 1}),
        ...     Record(id="b", metadata={"source": "b.pdf", "page": 2}),
        ...     Record(id="c", metadata={"source": "c.pdf"}),
        ... ]
        >>> compute_schema_shapes(records)
        {('page', 'source'): ['a', 'b'], ('source',): ['c']}

        ```
    """
    shapes: dict[tuple[str, ...], list[Any]] = {}
    for record in records:
        shape = tuple(sorted((record.metadata or {}).keys()))
        shapes.setdefault(shape, []).append(record.id)
    return shapes
