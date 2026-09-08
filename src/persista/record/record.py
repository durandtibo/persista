r"""Provide a generic record container with a stable UUID identifier."""

from __future__ import annotations

__all__ = ["Record"]

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from coola.identifier import generate_stable_uuid5


@dataclass(frozen=True)
class Record:
    """A generic immutable record with a stable UUID identifier and
    arbitrary metadata.

    Use :meth:`from_metadata` as the preferred constructor to
    automatically derive a stable UUID from the metadata dict.

    Note:
        ``metadata`` is copied into a read-only
        :class:`~types.MappingProxyType` view during construction, so
        ``record.metadata["x"] = 1`` raises ``TypeError`` instead of
        silently mutating the record - the dict passed in to
        ``metadata`` is not itself frozen, so mutating it directly
        after construction still does not affect the record.
        Instances remain unhashable, since a ``MappingProxyType`` is
        itself unhashable and ``eq=True`` (the dataclass default)
        disables the auto-generated ``__hash__``.  Use ``record.id``
        as the hashable identifier instead.

    Args:
        id: Unique identifier for the record, typically a UUID derived
            from the metadata via
            :func:`~coola.identifier.generate_stable_uuid5`.
        metadata: Arbitrary key-value metadata associated with the
            record.  Defaults to an empty dict.  Copied into a
            read-only view; the original dict is left untouched.
    """

    id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def __repr__(self) -> str:
        # Defined explicitly (rather than relying on the dataclass-
        # generated __repr__) so ``metadata`` renders as a plain dict
        # (e.g. ``{'a': 1}``) instead of the ``MappingProxyType`` repr
        # (``mappingproxy({'a': 1})``).
        return f"{type(self).__name__}(id={self.id!r}, metadata={dict(self.metadata)!r})"

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> Record:
        """Construct a :class:`Record` from a metadata dict.

        Computes a stable UUID from ``metadata`` via
        :func:`~coola.identifier.generate_stable_uuid5` and uses it as
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
            >>> dict(record.metadata)
            {'source': 'cats.txt', 'page': 1}

            ```
        """
        return cls(id=generate_stable_uuid5(metadata), metadata=metadata)
