r"""Near-duplicate record detection using MinHash/LSH."""

from __future__ import annotations

__all__ = ["find_near_duplicate_record_ids"]

import hashlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from persista.record import Record


def _base_hash(item: str, seed: int) -> int:
    """Hash a single metadata ``"key=value"`` item with a given seed."""
    digest = hashlib.sha256(f"{seed}:{item}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _minhash_signature(metadata: dict[str, Any], num_hashes: int) -> tuple[int, ...]:
    """Compute a MinHash signature for a record's metadata.

    Treats the metadata as a set of ``"key=value"`` string tokens and
    computes ``num_hashes`` independent minimum hash values over that
    set, approximating the Jaccard similarity between two records'
    metadata sets by the fraction of signature positions on which they
    agree.
    """
    items = [f"{key}={value}" for key, value in sorted(metadata.items())]
    if not items:
        # Empty metadata: distinct sentinel per position, so two empty
        # records agree everywhere and match nothing else.
        return tuple(-1 for _ in range(num_hashes))
    return tuple(min(_base_hash(item, seed) for item in items) for seed in range(num_hashes))


def find_near_duplicate_record_ids(
    records: Iterable[Record],
    *,
    num_hashes: int = 32,
    num_bands: int = 8,
) -> list[list[Any]]:
    r"""Group record ids whose metadata is *approximately* similar,
    using MinHash signatures and locality-sensitive hashing (LSH)
    banding.

    Unlike ``find_duplicate_record_ids`` (which only groups records
    with byte-for-byte identical metadata), this catches records whose
    metadata overlaps substantially but not completely - e.g. the same
    document re-ingested with one extra or corrected field, or
    metadata differing only in a timestamp key.

    Each record's metadata is treated as a set of ``"key=value"``
    tokens. A ``num_hashes``-sized MinHash signature approximates the
    Jaccard similarity between two records' token sets; signatures are
    then split into ``num_bands`` bands, and any two records sharing
    an identical band are considered candidate near-duplicates and
    merged into the same group (via union-find). More bands (with
    fewer rows each) increases recall (catches less similar pairs) at
    the cost of more false positives; fewer bands does the opposite.

    Records are consumed one at a time, so this works with generators
    or other iterables whose full contents cannot fit in memory for
    the signature computation itself, though - like
    ``find_duplicate_record_ids`` - the signatures and grouping
    structure are retained for the whole corpus, so memory usage
    grows with the number of records (O(number of records x
    num_hashes)).

    Args:
        records: A list, generator, or other iterable of
            ``persista.record.Record`` objects. Consumed exactly once;
            if a generator/iterator is passed in, it will be exhausted
            by this call.
        num_hashes: Number of hash functions in each MinHash
            signature. Must be evenly divisible by ``num_bands``.
        num_bands: Number of LSH bands the signature is split into.
            Must evenly divide ``num_hashes``.

    Returns:
        A list of groups of record ``id``s considered near-duplicates
        of each other, in the order their records were encountered.
        Each group contains two or more ids. Records with no
        near-duplicate are not included. Records with empty metadata
        are never grouped with each other or with anything else.

    Raises:
        ValueError: If ``num_hashes`` is not evenly divisible by
            ``num_bands``.

    Example:
        ```pycon
        >>> from persista.record import Record
        >>> from persista.record.analysis import find_near_duplicate_record_ids
        >>> records = [
        ...     Record(id="a", metadata={"source": "a.pdf", "page": 1, "lang": "en"}),
        ...     Record(id="b", metadata={"source": "a.pdf", "page": 1, "lang": "fr"}),
        ...     Record(id="c", metadata={"source": "z.pdf", "page": 9}),
        ... ]
        >>> find_near_duplicate_record_ids(records, num_hashes=4, num_bands=4)
        [['a', 'b']]

        ```

    See Also:
        ``find_duplicate_record_ids``: an exact variant that only
        groups records with identical metadata.
    """
    if num_hashes % num_bands != 0:
        msg = f"num_hashes ({num_hashes}) must be evenly divisible by num_bands ({num_bands})"
        raise ValueError(msg)
    rows_per_band = num_hashes // num_bands

    ids: list[Any] = []
    signatures: list[tuple[int, ...]] = []
    for record in records:
        ids.append(record.id)
        signatures.append(_minhash_signature(record.metadata or {}, num_hashes))

    n = len(ids)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i, root_j = find(i), find(j)
        if root_i != root_j:
            parent[root_j] = root_i

    for band in range(num_bands):
        start = band * rows_per_band
        end = start + rows_per_band
        buckets: dict[tuple[int, ...], int] = {}
        for i, signature in enumerate(signatures):
            if signature[start] == -1:
                # Sentinel signature (empty metadata) - never bucket together.
                continue
            band_key = signature[start:end]
            if band_key in buckets:
                union(i, buckets[band_key])
            else:
                buckets[band_key] = i

    groups: dict[int, list[Any]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(ids[i])
    return [group for group in groups.values() if len(group) > 1]
