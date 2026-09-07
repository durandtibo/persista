r"""Record metadata statistics."""

from __future__ import annotations

__all__ = ["MetadataStats", "compute_metadata_stats"]

from collections import Counter
from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from persista.record import Record


@dataclass
class MetadataStats:
    """Streaming record metadata health/stats.

    Accumulates statistics one record at a time via ``update``, so it
    can be fed from a list, a generator, or any other iterable without
    requiring the full corpus to be held in memory at once. Call
    ``to_dict`` at the end to compute the final report.

    Note:
        Once a key's sample of unique values has reached
        ``n_sample_values``, no further values for that key are added
        to the sample - the sample simply reflects the first
        ``n_sample_values`` distinct values encountered for that key,
        in record order. This makes the sample deterministic
        (independent of set iteration order) at the cost of not
        necessarily being a uniform sample over the whole corpus.

    Memory:
      - O(number of distinct metadata keys) for the per-key counters.
      - O(number of distinct keys x n_sample_values) for the sampled
        unique values, bounded by ``n_sample_values`` per key
        regardless of corpus size. If ``n_sample_values`` is ``None``,
        this becomes O(number of distinct keys x number of distinct
        values per key) instead, which can grow unbounded for
        high-cardinality keys (e.g. UUIDs).
    With a numeric ``n_sample_values``, this is effectively O(1) with
    respect to the number of records, so it scales to corpora too
    large to fit in memory.

    Attributes:
        n_sample_values: Max number of unique sample values retained
            per metadata key, or ``None`` to retain all unique values
            for every key (no cap).
        count: Total number of records processed.
        missing_metadata_count: Number of records whose ``metadata``
            is empty or falsy.
        total_keys: Sum of the number of metadata keys across all
            records processed.
        min_keys: Number of metadata keys on the record with the
            fewest keys seen so far, or ``None`` if no records have
            been processed yet.
        max_keys: Number of metadata keys on the record with the
            most keys seen so far, or ``None`` if no records have
            been processed yet.
    """

    n_sample_values: int | None = 3

    count: int = 0
    missing_metadata_count: int = 0
    total_keys: int = 0
    min_keys: int | None = None
    max_keys: int | None = None

    _key_counts: Counter[str] = field(default_factory=Counter)
    _key_none_counts: Counter[str] = field(default_factory=Counter)
    _key_types: dict[str, set[str]] = field(default_factory=dict)
    _key_values: dict[str, set[Any]] = field(default_factory=dict)
    _key_values_truncated: dict[str, bool] = field(default_factory=dict)

    def update(self, record: Record) -> None:
        """Fold a single record's metadata into the running statistics.

        Updates the record-level counters (count, missing metadata,
        keys-per-record min/max/total) as well as the per-key
        counters, value-type sets, none/empty counts, and unique-value
        samples.

        Args:
            record: The record to process. Its ``metadata`` is
                expected to be a mapping; a falsy/empty mapping is
                counted via ``missing_metadata_count`` and contributes
                zero keys.
        """
        metadata = record.metadata

        if not metadata:
            self.missing_metadata_count += 1

        n_keys = len(metadata)
        self.count += 1
        self.total_keys += n_keys

        if self.min_keys is None or n_keys < self.min_keys:
            self.min_keys = n_keys
        if self.max_keys is None or n_keys > self.max_keys:
            self.max_keys = n_keys

        for key, value in metadata.items():
            self._key_counts[key] += 1
            self._key_types.setdefault(key, set()).add(type(value).__name__)

            if value is None or value == "":
                self._key_none_counts[key] += 1

            if self._key_values_truncated.get(key, False):
                # Sample already capped for this key - do not add more values,
                # so the retained sample stays deterministic (first values seen).
                continue

            values = self._key_values.setdefault(key, set())
            if not isinstance(value, Hashable):
                # Unhashable value (e.g. a list or dict) -> stop sampling this key.
                self._key_values_truncated[key] = True
            elif (
                self.n_sample_values is not None
                and len(values) >= self.n_sample_values
                and value not in values
            ):
                # Sample is full and this is a new value -> cap it here.
                self._key_values_truncated[key] = True
            else:
                values.add(value)

    def to_dict(self) -> dict[str, Any]:
        """Compute the final statistics report from the accumulated
        state.

        Safe to call multiple times and at any point during
        accumulation; it does not mutate any state and always reflects
        everything processed via ``update`` so far.

        Returns:
            A dict with the following keys:

            - ``count``: Total number of records processed.
            - ``missing_metadata_count``: Number of records with
              empty/missing metadata.
            - ``avg_keys``: Mean number of metadata keys per record,
              or ``0`` if no records were processed.
            - ``min_keys`` / ``max_keys``: Fewest/most metadata keys
              seen on any single record, or ``None`` if empty.
            - ``distinct_keys_seen``: Number of distinct metadata keys
              observed across all records.
            - ``per_key``: A dict mapping each metadata key to a dict
              with:

              - ``present_in_records``: Number of records containing
                the key.
              - ``missing_in_records``: Number of records not
                containing the key.
              - ``value_types``: Sorted list of ``type(value).__name__``
                seen for the key.
              - ``none_or_empty_count``: Number of records where the
                key's value is ``None`` or the empty string.
              - ``unique_values_sample``: Sorted sample of unique
                values seen for the key, capped at ``n_sample_values``
                entries (or all of them, if ``n_sample_values`` is
                ``None``). Reflects the first distinct values
                encountered, in record order.
              - ``unique_values_sample_truncated``: ``True`` if not all
                unique values for the key could be retained (either
                because the sample cap was hit or because an
                unhashable value was encountered). Always ``False``
                when ``n_sample_values`` is ``None``, unless an
                unhashable value was seen.

            Percentages are intentionally omitted - compute them later
            from the raw counts (e.g. ``present_in_records / count``)
            since they are trivially derived from this report.
        """
        n = self.count
        avg_keys = self.total_keys / n if n else 0

        per_key: dict[str, Any] = {}
        for key in sorted(self._key_counts):
            present = self._key_counts[key]
            per_key[key] = {
                "present_in_records": present,
                "missing_in_records": n - present,
                "value_types": sorted(self._key_types.get(key, set())),
                "none_or_empty_count": self._key_none_counts.get(key, 0),
                "unique_values_sample": sorted(self._key_values.get(key, set()), key=str),
                "unique_values_sample_truncated": self._key_values_truncated.get(key, False),
            }

        return {
            "count": n,
            "missing_metadata_count": self.missing_metadata_count,
            "avg_keys": avg_keys,
            "min_keys": self.min_keys,
            "max_keys": self.max_keys,
            "distinct_keys_seen": len(self._key_counts),
            "per_key": per_key,
        }


def compute_metadata_stats(
    records: Iterable[Record], n_sample_values: int | None = 3
) -> dict[str, Any]:
    """Compute metadata health/statistics over a stream of records.

    Streaming health/stat check over a list, generator, or any iterable
    of Records. Records are consumed one at a time, so this works
    with iterators or generators whose full contents cannot fit in
    memory — only per-key aggregates are retained (see
    ``RecordMetadataStats`` for the memory profile).

    Args:
        records: A list, generator, or other iterable of
            ``zenpyre.records.Record`` objects. Consumed exactly once;
            if a generator/iterator is passed in, it will be exhausted
            by this call.
        n_sample_values: Max number of unique sample values to retain
            per metadata key. Defaults to 3. Pass ``None`` to track
            every unique value for every key instead of a bounded
            sample - useful for smaller corpora or low-cardinality
            metadata, but memory usage is then unbounded with respect
            to the number of distinct values per key.

    Returns:
        A dict of statistics as described in
        ``RecordMetadataStats.to_dict``. For an empty input, returns a
        report with ``count`` of ``0`` and ``None``/``0``/empty values
        for the remaining fields.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.analysis import compute_metadata_stats
        >>> records = [
        ...     Record(id="a", metadata={"source": "a.pdf"}),
        ...     Record(id="b", metadata={"source": "b.pdf", "page": 1}),
        ... ]
        >>> stats = compute_metadata_stats(records)
        >>> stats["count"]
        2

        ```
    """
    stats = MetadataStats(n_sample_values=n_sample_values)
    for record in records:
        stats.update(record)
    return stats.to_dict()
