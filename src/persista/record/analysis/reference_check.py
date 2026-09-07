r"""Broken-reference (orphan) detection between records."""

from __future__ import annotations

__all__ = ["find_orphan_references"]

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from persista.record import Record


def find_orphan_references(records: Iterable[Record], reference_key: str) -> list[Any]:
    r"""Find records whose metadata references another record id that
    does not exist in the corpus.

    Some corpora encode relationships between records via a metadata
    field holding another record's ``id`` (e.g. a ``"parent_id"`` for
    a chunk pointing back at the document it was split from). This
    detects dangling references: values of ``reference_key`` that do
    not match any ``id`` present in ``records``.

    This requires two passes over ``records`` (once to collect all
    ids, once to check references). ``records`` is materialized into a
    list up front if it is not already one, so a single-use generator
    or iterator works too, at the cost of holding all records in
    memory at once.

    Args:
        records: A list, tuple, generator, or other iterable of
            ``persista.record.Record`` objects.
        reference_key: The metadata key holding the referenced record
            id. Records missing this key, or whose value is ``None``,
            are not considered orphans (there is nothing to check).

    Returns:
        A list of record ``id``s whose ``reference_key`` metadata
        value does not match any record id in the corpus, in the
        order their records were encountered.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.analysis import find_orphan_references
        >>> records = [
        ...     Record(id="doc1", metadata={}),
        ...     Record(id="chunk1", metadata={"parent_id": "doc1"}),
        ...     Record(id="chunk2", metadata={"parent_id": "missing_doc"}),
        ...     Record(id="chunk3", metadata={}),
        ... ]
        >>> find_orphan_references(records, reference_key="parent_id")
        ['chunk2']

        ```
    """
    records = list(records)
    ids = {record.id for record in records}
    orphans = []
    for record in records:
        if reference_key not in record.metadata:
            continue
        referenced_id = record.metadata[reference_key]
        if referenced_id is None:
            continue
        if referenced_id not in ids:
            orphans.append(record.id)
    return orphans
