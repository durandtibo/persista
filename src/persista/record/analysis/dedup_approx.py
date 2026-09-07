r"""Approximate duplicate record detection, using fixed (O(1)) memory
regardless of corpus size."""

from __future__ import annotations

__all__ = ["count_approx_duplicate_records"]

from typing import TYPE_CHECKING

from coola.utils.bloom_filter import BloomFilter

from persista.record.analysis._hashing import hash_metadata

if TYPE_CHECKING:
    from collections.abc import Iterable

    from persista.record import Record


def count_approx_duplicate_records(
    records: Iterable[Record],
    *,
    expected_record_count: int = 1_000_000,
    fp_rate: float = 0.01,
) -> int:
    r"""Count records whose ``metadata`` has probably already been seen
    earlier in the stream, using a Bloom filter.

    Records are consumed one at a time, so this works with iterators
    or generators whose full contents cannot fit in memory. Unlike
    ``find_duplicate_record_ids``, memory usage here is fixed up front
    from ``expected_record_count`` and does not grow with the number of
    records processed, at the cost of a tunable false-positive rate: a
    record may occasionally be counted as a duplicate when it is not,
    but a true duplicate is never missed.

    Args:
        records: A list, generator, or other iterable of
            ``persista.record.Record`` objects. Consumed exactly once;
            if a generator/iterator is passed in, it will be exhausted
            by this call.
        expected_record_count: Rough estimate of the total number of
            records (or, more precisely, unique metadata values) that
            will be processed. Used to size the Bloom filter for the
            requested ``fp_rate``. Safe to overestimate; underestimating
            causes the effective false-positive rate to rise above
            ``fp_rate`` as more records are processed than planned for.
        fp_rate: Target false-positive probability, once approximately
            ``expected_record_count`` unique metadata values have been
            added.

    Returns:
        The approximate number of records whose ``metadata`` duplicates
        an earlier record's, as reported by the Bloom filter. Never
        undercounts by much; may slightly overcount due to the
        filter's false-positive rate.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.analysis import count_approx_duplicate_records
        >>> records = [
        ...     Record(id="a", metadata={"source": "a.pdf"}),
        ...     Record(id="b", metadata={"source": "a.pdf"}),
        ...     Record(id="c", metadata={"source": "b.pdf"}),
        ... ]
        >>> count_approx_duplicate_records(records, expected_record_count=1000)
        1

        ```

    See Also:
        ``find_duplicate_record_ids``: an exact variant using a hash
        map to group duplicate ids, with memory usage that grows with
        corpus size but produces exact (non-approximate) results.
    """
    bloom = BloomFilter(expected_items=expected_record_count, fp_rate=fp_rate)
    duplicate_count = 0
    for record in records:
        metadata_hash = hash_metadata(record.metadata or {})
        if bloom.add_and_check(metadata_hash):
            duplicate_count += 1
    return duplicate_count
