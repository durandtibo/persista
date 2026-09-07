r"""Per-key value frequency and cardinality estimation."""

from __future__ import annotations

__all__ = ["compute_value_frequency"]

import hashlib
import math
from collections import Counter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from persista.record import Record


class _HyperLogLog:
    r"""Minimal HyperLogLog cardinality estimator.

    Estimates the number of distinct values added to it using
    O(2 ** precision) memory, regardless of how many values (or
    duplicates thereof) are added - unlike tracking a full ``set`` of
    seen values, which grows with the number of *distinct* values.

    Args:
        precision: Number of bits used to select one of ``2 **
            precision`` registers. Higher values trade memory for
            accuracy; the standard error is approximately
            ``1.04 / sqrt(2 ** precision)``.
    """

    def __init__(self, precision: int = 12) -> None:
        self._precision = precision
        self._m = 1 << precision
        self._registers = [0] * self._m

    def add(self, value: Any) -> None:
        """Add a value to the estimator.

        Args:
            value: The value to add. Hashed via ``str(value)`` and
                SHA-256, so any value is accepted regardless of
                hashability.

        Warning:
            Because hashing goes through ``str(value)``, distinct
            values that stringify the same way (e.g. the int ``1``
            and the str ``"1"``) are treated as one value for
            cardinality estimation purposes, unlike the ``top_values``
            counters in ``compute_value_frequency``, which key
            unhashable values by their ``str()`` form but otherwise
            key hashable values by their real ``(type, value)`` pair.
        """
        digest = hashlib.sha256(str(value).encode()).digest()
        h = int.from_bytes(digest[:8], "big")
        index = h & (self._m - 1)
        remaining = h >> self._precision

        # Length of the leading run of zero bits (+1) among the
        # remaining bits, capped so it always fits in the 64 -
        # precision bits available.
        max_rank = 64 - self._precision
        rank = 1
        while remaining and not (remaining & 1) and rank < max_rank:
            rank += 1
            remaining >>= 1
        self._registers[index] = max(self._registers[index], rank)

    def estimate(self) -> int:
        """Estimate the number of distinct values added so far.

        Returns:
            The estimated cardinality, rounded to the nearest integer.
        """
        m = self._m
        alpha = 0.7213 / (1 + 1.079 / m) if m >= 128 else 0.5 * m
        raw = alpha * m * m / sum(2.0 ** (-r) for r in self._registers)

        zero_registers = self._registers.count(0)
        if raw <= 2.5 * m and zero_registers:
            # Small-range correction (linear counting).
            return round(m * math.log(m / zero_registers))
        return round(raw)


def compute_value_frequency(
    records: Iterable[Record], *, top_k: int = 5, hll_precision: int = 12
) -> dict[str, dict[str, Any]]:
    r"""Compute, for each metadata key, its most common values and an
    approximate cardinality (number of distinct values).

    This complements ``compute_metadata_stats``, whose
    ``unique_values_sample`` is a small, arbitrary (first-seen) sample
    rather than a ranked top-K, and does not report cardinality.
    Frequency counts help spot near-constant keys (a single value
    dominates) or skewed distributions; cardinality helps spot keys
    unsuitable for grouping/joins because of excessive uniqueness
    (e.g. UUIDs, timestamps).

    Records are consumed one at a time, so this works with generators
    or other iterables whose full contents cannot fit in memory.
    Memory usage is O(number of distinct keys x number of distinct
    values per key) for the frequency counters (unbounded for
    high-cardinality keys), plus a fixed O(2 ** hll_precision) per key
    for the cardinality estimator.

    Args:
        records: A list, generator, or other iterable of
            ``persista.record.Record`` objects. Consumed exactly once;
            if a generator/iterator is passed in, it will be exhausted
            by this call.
        top_k: Number of most common values to report per key.
        hll_precision: Precision passed to the internal HyperLogLog
            cardinality estimator for each key. Higher values give a
            more accurate estimate at the cost of more memory per key.

    Returns:
        A dict mapping each metadata key to a dict with:

        - ``top_values``: A list of ``(value, count)`` tuples for the
          ``top_k`` most common values, most common first.
        - ``distinct_count_estimate``: The approximate number of
          distinct values seen for the key.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.analysis import compute_value_frequency
        >>> records = [
        ...     Record(id="a", metadata={"lang": "en"}),
        ...     Record(id="b", metadata={"lang": "en"}),
        ...     Record(id="c", metadata={"lang": "fr"}),
        ... ]
        >>> result = compute_value_frequency(records)
        >>> result["lang"]["top_values"]
        [('en', 2), ('fr', 1)]

        ```
    """
    counters: dict[str, Counter[Any]] = {}
    estimators: dict[str, _HyperLogLog] = {}

    for record in records:
        for key, value in record.metadata.items():
            try:
                counters.setdefault(key, Counter())[value] += 1
            except TypeError:
                # Unhashable value (list/dict) - fall back to its str form.
                counters.setdefault(key, Counter())[str(value)] += 1
            estimators.setdefault(key, _HyperLogLog(precision=hll_precision)).add(value)

    return {
        key: {
            "top_values": counters[key].most_common(top_k),
            "distinct_count_estimate": estimators[key].estimate(),
        }
        for key in counters
    }
