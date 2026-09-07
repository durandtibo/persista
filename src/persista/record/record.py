r"""Provide a generic record container with a stable UUID identifier."""

from __future__ import annotations

__all__ = ["Record"]

from dataclasses import dataclass, field
from typing import Any

from persista.utils.hashing import hash_dict_uuid


@dataclass(frozen=True)
class Record:
    """A generic immutable record with a stable UUID identifier and
    arbitrary metadata.

    Use :meth:`from_metadata` as the preferred constructor to
    automatically derive a stable UUID from the metadata dict.

    Args:
        id: Unique identifier for the record, typically a UUID derived
            from the metadata via
            :func:`~persista.utils.hashing.hash_dict_uuid`.
        metadata: Arbitrary key-value metadata associated with the
            record.  Defaults to an empty dict.
    """

    id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> Record:
        """Construct a :class:`Record` from a metadata dict.

        Computes a stable UUID from ``metadata`` via
        :func:`~persista.utils.hashing.hash_dict_uuid` and uses it as
        the record's ``id``.  Two calls with the same ``metadata``
        contents (regardless of key insertion order) will produce the
        same ``id``.

        Args:
            metadata: Arbitrary key-value metadata to associate with
                the record.  Used to derive the ``id``.

        Returns:
            A new :class:`Record` with ``id`` derived from
            ``metadata``.

        Example:
            ```pycon
            >>> from persista.record import Record
            >>> record = Record.from_metadata({"source": "cats.txt", "page": 1})
            >>> record.id  # doctest: +ELLIPSIS
            '...'
            >>> record.metadata
            {'source': 'cats.txt', 'page': 1}

            ```
        """
        return cls(id=hash_dict_uuid(metadata), metadata=metadata)
