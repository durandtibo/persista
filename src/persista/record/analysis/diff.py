r"""Diff two record snapshots by id."""

from __future__ import annotations

__all__ = ["diff_records"]

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from persista.record import Record


def diff_records(before: Iterable[Record], after: Iterable[Record]) -> dict[str, list[Any]]:
    r"""Diff two record snapshots (e.g. before/after a pipeline run) by
    ``id``.

    Useful for auditing what an ingestion or transformation step
    changed: which records were newly added, which disappeared, and
    which kept the same id but had their metadata altered.

    Both ``before`` and ``after`` are consumed one at a time and fully
    materialized internally (as ``id -> metadata`` maps), so this
    works with generators or other iterables, but memory usage is
    O(number of records in each snapshot) - unlike the single-pass
    analyses elsewhere in this package, a diff inherently needs both
    full snapshots available for comparison.

    Args:
        before: A list, generator, or other iterable of
            ``persista.record.Record`` objects representing the
            earlier snapshot. Consumed exactly once.
        after: A list, generator, or other iterable of
            ``persista.record.Record`` objects representing the later
            snapshot. Consumed exactly once.

    Returns:
        A dict with three keys:

        - ``added``: ids present in ``after`` but not ``before``, in
          the order encountered in ``after``.
        - ``removed``: ids present in ``before`` but not ``after``, in
          the order encountered in ``before``.
        - ``changed``: ids present in both snapshots whose metadata
          differs between them, in the order encountered in ``after``.

        Ids present in both snapshots with identical metadata are
        omitted entirely.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.analysis import diff_records
        >>> before = [
        ...     Record(id="a", metadata={"source": "a.pdf"}),
        ...     Record(id="b", metadata={"source": "b.pdf"}),
        ... ]
        >>> after = [
        ...     Record(id="a", metadata={"source": "a.pdf", "page": 1}),
        ...     Record(id="c", metadata={"source": "c.pdf"}),
        ... ]
        >>> diff_records(before, after)
        {'added': ['c'], 'removed': ['b'], 'changed': ['a']}

        ```
    """
    before_by_id = {record.id: record.metadata for record in before}
    after_by_id = {record.id: record.metadata for record in after}

    added = [rid for rid in after_by_id if rid not in before_by_id]
    removed = [rid for rid in before_by_id if rid not in after_by_id]
    changed = [
        rid for rid in after_by_id if rid in before_by_id and after_by_id[rid] != before_by_id[rid]
    ]

    return {"added": added, "removed": removed, "changed": changed}
