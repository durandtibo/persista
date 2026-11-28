r"""Per-key value frequency and cardinality."""

from __future__ import annotations

__all__ = ["compute_value_frequency"]

from collections import Counter
from typing import TYPE_CHECKING, Any

from persista.record.equality import encode_value

if TYPE_CHECKING:
    from collections.abc import Iterable

    from persista.record import Record


def compute_value_frequency(
    records: Iterable[Record], *, top_k: int = 5
) -> dict[str, dict[str, Any]]:
    r"""Compute, for each metadata key, its most common values and its
    number of distinct values.

    This complements ``compute_metadata_stats``, whose
    ``unique_values_sample`` is a small, arbitrary (first-seen) sample
    rather than a ranked top-K, and does not report cardinality.
    Frequency counts help spot near-constant keys (a single value
    dominates) or skewed distributions; cardinality helps spot keys
    unsuitable for grouping/joins because of excessive uniqueness
    (e.g. UUIDs, timestamps).

    The counts are exact. Two values are counted together if they are
    equal as defined by :mod:`persista.record.equality`: ``1``, ``"1"``
    and ``True`` are three values, and ``1`` and ``1.0`` are one.

    Records are consumed one at a time, so this works with generators
    or other iterables whose full contents cannot fit in memory.
    Memory usage is O(number of distinct keys x number of distinct
    values per key), which is unbounded for high-cardinality keys.

    Args:
        records: A list, generator, or other iterable of
            ``persista.record.Record`` objects. Consumed exactly once;
            if a generator/iterator is passed in, it will be exhausted
            by this call.
        top_k: Number of most common values to report per key. Must not
            be negative.

    Returns:
        A dict mapping each metadata key to a dict with:

        - ``top_values``: A list of ``(value, count)`` tuples for the
          ``top_k`` most common values, most common first (values with
          the same count are in the order they were first encountered).
          Each value is the first one encountered among the equal ones.
          It is the object of the record, not a copy.
        - ``distinct_count``: The number of distinct values of the key.

    Raises:
        TypeError: If a metadata value contains an object that cannot be
            compared (see :mod:`persista.record.equality`).
        ValueError: If ``top_k`` is negative, or if a metadata value
            contains ``NaN`` or itself.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.analysis import compute_value_frequency
        >>> records = [
        ...     Record(id="a", metadata={"lang": "en"}),
        ...     Record(id="b", metadata={"lang": "en"}),
        ...     Record(id="c", metadata={"lang": "fr"}),
        ... ]
        >>> compute_value_frequency(records)
        {'lang': {'top_values': [('en', 2), ('fr', 1)], 'distinct_count': 2}}

        ```
    """
    if top_k < 0:
        msg = f"'top_k' must be non-negative, got {top_k}"
        raise ValueError(msg)
    counters: dict[str, Counter[bytes]] = {}
    # For each key, the first value of each encoding.
    values: dict[str, dict[bytes, Any]] = {}
    for record in records:
        for key, value in record.metadata.items():
            encoding = encode_value(value)
            counters.setdefault(key, Counter())[encoding] += 1
            values.setdefault(key, {}).setdefault(encoding, value)

    return {
        key: {
            "top_values": [
                (values[key][encoding], count) for encoding, count in counter.most_common(top_k)
            ],
            "distinct_count": len(counter),
        }
        for key, counter in counters.items()
    }
