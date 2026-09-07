r"""Shared hashing helper for record metadata.

Used by ``persista.record.analysis.dedup`` and
``persista.record.analysis.dedup_approx``, which both need a stable
content hash for a record's metadata.
"""

from __future__ import annotations

__all__ = ["hash_metadata"]

import hashlib
import json
from typing import Any


def hash_metadata(metadata: dict[str, Any]) -> bytes:
    """Compute a stable content hash for a record's metadata.

    Serialises ``metadata`` via ``json.dumps`` with ``sort_keys=True``
    so the hash is independent of key insertion order, then hashes the
    resulting bytes with SHA-256. Values that are not JSON-serialisable
    are replaced by a ``"<type name>:<str(value)>"`` tag (via
    ``default``) so hashing never raises, and so that two distinct
    non-serialisable objects of different types whose ``str()``
    happens to coincide do not falsely hash the same (they still
    collide if both the type name and ``str()`` match, e.g. two
    distinct instances of the same class with the same ``__str__``).
    ``metadata`` is coerced to a plain ``dict`` first, so non-``dict``
    mappings (e.g. a ``MappingProxyType``, as used by
    ``persista.record.Record.metadata``) hash the same as an equivalent
    plain ``dict`` instead of falling back to their ``str()`` form.

    Args:
        metadata: The metadata mapping to hash.

    Returns:
        The 32-byte SHA-256 digest of the canonical serialization.
    """
    canonical = json.dumps(
        dict(metadata), sort_keys=True, default=lambda v: f"{type(v).__name__}:{v!s}"
    ).encode("utf-8")
    return hashlib.sha256(canonical).digest()
