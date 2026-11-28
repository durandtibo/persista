r"""Provide a generic record container with a stable UUID identifier."""

from __future__ import annotations

__all__ = ["Record"]

import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from persista.record.equality import hash_metadata

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True)
class Record:
    """A generic immutable record: an identifier and a read-only mapping
    of metadata.

    Use :meth:`from_metadata` as the preferred constructor to
    automatically derive a stable UUID from the metadata.

    A record is a plain value:

    - ``metadata`` is copied into a read-only
      :class:`~types.MappingProxyType`, so
      ``record.metadata["x"] = 1`` raises ``TypeError``, and modifying the
      mapping given to the constructor does not change the record. Use
      ``dict(record.metadata)`` to get a modifiable copy, or an object
      that functions such as :func:`json.dumps` accept.
    - The copy is shallow: the values of the metadata, such as a nested
      list, are shared with the caller and are not read-only. Do not
      modify them.
    - Two records are equal if they have the same ``id`` and their
      metadata are equal with ``==``, like two ``dict`` (so
      ``{"x": 1}`` equals ``{"x": True}``). The identifiers of
      :meth:`from_metadata` and the analyses of
      :mod:`persista.record.analysis` use the stricter equality of
      :mod:`persista.record.equality`.
    - A record is hashed by its ``id``, so it can be used in a set or as a
      key of a ``dict``, whatever its metadata contains.
    - A record can be pickled and copied (``copy.copy`` and
      ``copy.deepcopy``), if its values can. A subclass that adds fields
      must override ``__reduce__`` to keep them.
    - ``dataclasses.asdict`` and ``dataclasses.astuple`` are not
      supported: they raise ``TypeError`` because they cannot copy the
      read-only mapping. Use ``record.id`` and ``dict(record.metadata)``.

    Args:
        id: Unique identifier for the record, typically a UUID derived
            from the metadata by :meth:`from_metadata`.
        metadata: Arbitrary key-value metadata associated with the
            record.  Defaults to an empty mapping.  Copied into a
            read-only view; the original mapping is left untouched.

    Example:
        ```pycon
        >>> import pickle
        >>> from persista.record import Record
        >>> record = Record(id="1", metadata={"tags": ["a"]})
        >>> pickle.loads(pickle.dumps(record)) == record
        True
        >>> len({record, record})
        1

        ```
    """

    id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def __hash__(self) -> int:
        # The metadata cannot be hashed. Equal records have the same id,
        # so the hash is consistent with the equality.
        return hash(self.id)

    def __reduce__(self) -> tuple[type[Record], tuple[str, dict[str, Any]]]:
        # A MappingProxyType cannot be pickled or deep-copied, so a record
        # is rebuilt from a dict.
        return type(self), (self.id, dict(self.metadata))

    def __repr__(self) -> str:
        # Defined explicitly (rather than relying on the dataclass-
        # generated __repr__) so ``metadata`` renders as a plain dict
        # (e.g. ``{'a': 1}``) instead of the ``MappingProxyType`` repr
        # (``mappingproxy({'a': 1})``).
        return f"{type(self).__name__}(id={self.id!r}, metadata={dict(self.metadata)!r})"

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, Any]) -> Record:
        """Construct a :class:`Record` from its metadata.

        The ``id`` is a UUID (version 5) derived from the canonical
        encoding of the metadata (see :mod:`persista.record.equality`),
        the same in any process. Equal metadata give the same ``id``: the
        order of the keys does not matter and ``1`` equals ``1.0``.
        Different metadata give different ids: for example ``1``, ``"1"``
        and ``True`` differ, and so do a list and a tuple. A JSON store
        reads a tuple back as a list, so the metadata that it returns
        for a record with a tuple give another ``id``.

        Args:
            metadata: Arbitrary key-value metadata to associate with
                the record.  Used to derive the ``id``.

        Returns:
            A new :class:`Record` with ``id`` derived from
            ``metadata``.

        Raises:
            TypeError: If ``metadata`` contains an object of a type that
                cannot be compared, such as a ``datetime``, a ``Decimal``,
                an instance of a subclass of a built-in type or of a
                custom class. Convert it first (for example with
                ``isoformat()``), or give the ``id`` to the constructor.
            ValueError: If ``metadata`` contains ``NaN``, or a value that
                contains itself.
            RecursionError: If ``metadata`` is nested too deeply for the
                recursion limit of Python.

        Example:
            ```pycon
            >>> from persista.record import Record
            >>> record = Record.from_metadata({"source": "cats.txt", "page": 1})
            >>> record.id
            '65671470-bf89-5ffd-a51e-78e06c01fd41'
            >>> dict(record.metadata)
            {'source': 'cats.txt', 'page': 1}

            ```
        """
        data = dict(metadata)
        return cls(id=str(uuid.uuid5(uuid.NAMESPACE_OID, hash_metadata(data))), metadata=data)
